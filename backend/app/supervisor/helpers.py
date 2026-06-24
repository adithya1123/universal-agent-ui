"""Shared types and helpers for langgraph_supervisor client.

Self-contained module -- no external dependencies on agent_bricks.
All types (AgentResult, StreamEvent, ErrorCategory) and helper functions
(error classification, CSV extraction, stream parsing) are defined here.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple
from datetime import datetime, timezone

try:
    import openai
except ImportError:
    openai = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Centralized truncation limits
# ---------------------------------------------------------------------------

class _Limits:
    """Single source of truth for all truncation thresholds (in characters)."""
    ERROR_BODY = 2000
    RAW_BODY = 5000
    MESSAGE_ERROR = 500
    TOOL_OUTPUT = 300
    ARGS_SUMMARY = 150
    DISPLAY_OUTCOME = 200
    DISPLAY_QUESTION = 70
    ERROR_DETECT = 300
    RAW_MESSAGE_MIN_LEN = 500  # minimum length for sub-agent messages to be considered for CSV extraction

# ---------------------------------------------------------------------------
# Volume writer abstraction (dual-mode: FUSE vs SDK)
# ---------------------------------------------------------------------------

class VolumeWriter(Protocol):
    """Abstraction for writing files to UC Volumes."""
    def write_file(self, file_path: str, content: bytes) -> None: ...
    def make_dirs(self, dir_path: str) -> None: ...


class FuseVolumeWriter:
    """Writes via local FUSE mount -- works on Databricks compute only."""

    def write_file(self, file_path: str, content: bytes) -> None:
        with open(file_path, "wb") as f:
            f.write(content)

    def make_dirs(self, dir_path: str) -> None:
        os.makedirs(dir_path, exist_ok=True)


class SdkVolumeWriter:
    """Writes via Databricks Files API -- works from any authenticated client."""

    def __init__(self, workspace_client: Any) -> None:
        self._client = workspace_client

    def write_file(self, file_path: str, content: bytes) -> None:
        # SDK files.upload expects path like /Volumes/catalog/schema/volume/...
        api_path = file_path.lstrip("/")
        self._client.files.upload(f"/{api_path}", io.BytesIO(content), overwrite=True)

    def make_dirs(self, dir_path: str) -> None:
        # SDK files API creates intermediate directories on upload;
        # explicit mkdir via create_directory for pre-creation.
        api_path = dir_path.lstrip("/")
        self._client.files.create_directory(f"/{api_path}")


def _create_volume_writer(
    workspace_client: Optional[Any] = None,
) -> VolumeWriter:
    """Return the appropriate volume writer.

    Priority: SDK writer (WorkspaceClient) is the primary mode -- works
    consistently on Databricks compute and external clients (App Service).
    Falls back to FUSE only when no WorkspaceClient is provided and the
    FUSE mount is available (legacy/test usage).
    """
    if workspace_client is not None:
        return SdkVolumeWriter(workspace_client)
    # Fallback: FUSE mount only if on Databricks compute with no client
    if os.path.isdir("/Volumes"):
        return FuseVolumeWriter()
    raise RuntimeError(
        "Cannot write to UC Volumes: no WorkspaceClient provided and "
        "FUSE mount not available."
    )




# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

class ErrorCategory(str, Enum):
    """Classification of errors from the agent or transport layer."""
    PERMISSION = "PERMISSION_DENIED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    TIMEOUT = "TIMEOUT"
    INVALID_REQUEST = "INVALID_REQUEST"
    PARSE_ERROR = "PARSE_ERROR"
    NETWORK = "NETWORK_ERROR"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# StreamEvent
# ---------------------------------------------------------------------------

@dataclass
class StreamEvent:
    """A single event from a streaming agent response.

    Event types:
        text_delta  -- Incremental text chunk from the agent's answer
        routing     -- Supervisor dispatching to a sub-agent (function_call)
        reasoning   -- Sub-agent reasoning/thinking step
        annotation  -- Source citation added to the response
        item_done   -- A complete output item (message, function_call, etc.)
        completed   -- Stream finished; final AgentResult available via .result
    """
    type: str
    text: str = ""
    agent: str = ""
    step: Any = 0
    item_type: str = ""
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# AgentResult
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """Structured result from a single supervisor agent invocation.

    Result file fields:
        result_file_path  -- Path to primary (largest) CSV, backward compatible
        result_meta       -- Metadata for primary CSV (row_count, col_count, etc.)
        result_files      -- All extracted CSVs when multiple tables found
    """

    question: str
    status_code: int
    latency_s: float
    final_answer: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    error_categories: Set[ErrorCategory] = field(default_factory=set)
    raw: Optional[Dict[str, Any]] = None
    message_id: Optional[str] = None
    result_file_path: Optional[str] = None
    result_meta: Optional[Dict[str, Any]] = None
    result_files: Optional[List[Dict[str, Any]]] = None
    trace_id: Optional[str] = None
    title: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.status_code == 200 and len(self.errors) == 0

    @property
    def num_steps(self) -> int:
        return len(self.tool_calls)

    @property
    def trace(self) -> List[str]:
        return [f"Step {tc['step']}: called {tc['agent']}" for tc in self.tool_calls]

    def to_dict(self, *, include_raw: bool = False) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "question": self.question,
            "status_code": self.status_code,
            "latency_s": round(self.latency_s, 2),
            "success": self.success,
            "final_answer": self.final_answer,
            "num_steps": self.num_steps,
            "tool_calls": self.tool_calls,
            "errors": self.errors,
            "error_categories": sorted(c.value for c in self.error_categories),
            "message_id": self.message_id,
            "result_file_path": self.result_file_path,
            "result_meta": self.result_meta,
            "result_files": self.result_files,
            "trace_id": self.trace_id,
            "title": self.title,
        }
        if include_raw and self.raw is not None:
            d["raw"] = self.raw
        return d

    def to_json(self, *, include_raw: bool = False, indent: int = 2) -> str:
        return json.dumps(self.to_dict(include_raw=include_raw), indent=indent)

    def display(self, *, verbose: bool = True) -> None:
        """Pretty-print result with routing trace, errors, and final answer."""
        tag = "PASS" if self.success else "FAIL"
        sep = "=" * 80
        print(sep)
        print(f"[{tag}] Status: {self.status_code} | "
              f"Latency: {self.latency_s:.1f}s | Steps: {self.num_steps}")
        if self.trace_id:
            print(f"Trace:    {self.trace_id}")
        print(f"Question: {self.question}")
        if self.title:
            print(f"Title:    {self.title}")
        print(sep)

        if verbose and self.tool_calls:
            print(f"\nAgent Routing ({self.num_steps} tool call(s)):")
            for tc in self.tool_calls:
                outcome = tc.get("outcome", "")
                icon = ">>" if "error" not in outcome.lower() else "!!"
                print(f"  {icon} Step {tc['step']}: {tc['agent']}")
                if tc.get("args_summary"):
                    print(f"     Args: {tc['args_summary']}")
                if outcome:
                    trunc = _trunc(outcome, _Limits.DISPLAY_OUTCOME)
                    print(f"     Result: {trunc}")

        if self.errors:
            cats = ", ".join(sorted(c.value for c in self.error_categories)) or "UNKNOWN"
            print(f"\nErrors ({len(self.errors)}) [{cats}]:")
            for err in self.errors:
                print(f"  !! {_trunc(err, _Limits.MESSAGE_ERROR)}")

        # Result files summary
        if self.result_files and len(self.result_files) > 1:
            print(f"\nResult Files ({len(self.result_files)} tables extracted):")
            for i, rf in enumerate(self.result_files):
                tag_str = "[primary]" if i == 0 else f"[{i}]"
                src = rf.get('source', '?')
                agent = rf.get('agent', '')
                agent_str = f" from {agent}" if agent else ""
                print(f"  {tag_str} {rf['row_count']} rows x {rf['col_count']} cols "
                      f"({src}{agent_str}) -> {rf['file_path']}")
        elif self.result_file_path and self.result_meta:
            src = self.result_meta.get('source', '?')
            print(f"\nResult CSV: {self.result_meta['row_count']} rows x "
                  f"{self.result_meta['col_count']} cols ({src}) -> {self.result_file_path}")

        print(f"\n{'- ' * 40}")
        print("Final Answer:")
        print(f"{'- ' * 40}")
        print(self.final_answer if self.final_answer else "(no final answer extracted)")
        print()

    def __str__(self) -> str:
        tag = "PASS" if self.success else "FAIL"
        return (f"AgentResult([{tag}] {self.status_code} | "
                f"{self.latency_s:.1f}s | steps={self.num_steps})")

    def __repr__(self) -> str:
        return (f"AgentResult(success={self.success}, status={self.status_code}, "
                f"latency={self.latency_s:.1f}s, errors={len(self.errors)})")


# ---------------------------------------------------------------------------
# TestReport
# ---------------------------------------------------------------------------

@dataclass
class TestReport:
    """Aggregated results from a batch of agent queries."""

    results: List[AgentResult] = field(default_factory=list)
    total_latency_s: float = 0.0

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total * 100) if self.total else 0.0

    @property
    def avg_latency_s(self) -> float:
        return (sum(r.latency_s for r in self.results) / self.total) if self.total else 0.0

    def display(self, *, verbose: bool = False) -> None:
        sep = "=" * 80
        print(f"\n{sep}")
        print(f"TEST REPORT: {self.passed}/{self.total} passed "
              f"({self.pass_rate:.0f}%) | "
              f"Total: {self.total_latency_s:.1f}s | "
              f"Avg: {self.avg_latency_s:.1f}s")
        print(sep)

        for i, r in enumerate(self.results, 1):
            tag = "PASS" if r.success else "FAIL"
            q_short = _trunc(r.question, _Limits.DISPLAY_QUESTION)
            print(f"  {i}. [{tag}] {r.latency_s:5.1f}s | {q_short}")
            if not r.success:
                cats = ", ".join(sorted(c.value for c in r.error_categories))
                print(f"     Errors: {cats}")

        all_cats = [c for r in self.results for c in r.error_categories]
        if all_cats:
            print("\nError Breakdown:")
            for cat, count in Counter(c.value for c in all_cats).most_common():
                print(f"  {cat}: {count}")
        print()

        if verbose:
            print("\nDetailed Results:\n")
            for r in self.results:
                r.display(verbose=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 1),
            "total_latency_s": round(self.total_latency_s, 1),
            "avg_latency_s": round(self.avg_latency_s, 1),
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Helper functions -- truncation, text extraction, argument summarization
# ---------------------------------------------------------------------------

def _trunc(text: str, limit: int) -> str:
    return (text[:limit] + "...") if len(text) > limit else text


def _extract_text_from_item(item: Any) -> str:
    """Extract text from a Response output item's content field."""
    content = getattr(item, "content", [])
    if isinstance(content, str):
        return content
    parts = []
    for c in content:
        if isinstance(c, dict):
            if c.get("type") == "output_text":
                parts.append(c.get("text", ""))
        elif hasattr(c, "type") and getattr(c, "type", "") == "output_text":
            parts.append(getattr(c, "text", ""))
    return "\n".join(parts).strip()


def _summarize_args(args_raw: str) -> str:
    try:
        parts = [str(v) for v in json.loads(args_raw).values()]
        combined = "; ".join(parts)
        return _trunc(combined, _Limits.ARGS_SUMMARY)
    except (json.JSONDecodeError, AttributeError):
        pass
    return _trunc(str(args_raw), _Limits.ARGS_SUMMARY)


def _summarize_tool_output(output_str: str) -> str:
    if not output_str:
        return ""
    try:
        data = json.loads(output_str) if isinstance(output_str, str) else output_str
        if isinstance(data, dict):
            if "error" in data:
                return f"Error: {data['error'][:_Limits.TOOL_OUTPUT]}"
            rows = data.get("rows", [])
            if rows:
                return f"{len(rows)} row(s), columns: {data.get('columns', [])}"
    except (json.JSONDecodeError, TypeError):
        pass
    s = str(output_str)
    return (s[:_Limits.TOOL_OUTPUT] + "...") if len(s) > _Limits.TOOL_OUTPUT else s


def _safe_to_dict(response: Any) -> Dict[str, Any]:
    """Safely convert a Response object to dict for raw storage."""
    try:
        return response.to_dict()
    except (AttributeError, TypeError):
        try:
            return response.model_dump()
        except (AttributeError, TypeError):
            return {"output": str(response)[:_Limits.RAW_BODY]}


# ---------------------------------------------------------------------------
# Error detection and classification helpers
# ---------------------------------------------------------------------------

def _categorize_message_error(text: str) -> Optional[ErrorCategory]:
    """Detect agent-level error patterns in supervisor message text."""
    if not text:
        return None
    t = text[:_Limits.ERROR_DETECT].upper()
    if "PERMISSION_DENIED" in t:
        return ErrorCategory.PERMISSION
    if "DOES NOT EXIST" in t or "NOT FOUND" in t:
        return ErrorCategory.RESOURCE_NOT_FOUND
    if "TIMEOUT" in t or "TIMED OUT" in t:
        return ErrorCategory.TIMEOUT
    if t[:20].startswith(("ERROR", "GENIE QUERY FAILED")):
        return ErrorCategory.UNKNOWN
    return None


def _categorize_exception(exc: Exception) -> ErrorCategory:
    """Map OpenAI SDK exceptions to ErrorCategory."""
    if openai is None:
        return ErrorCategory.UNKNOWN
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return ErrorCategory.AUTH_EXPIRED
    if isinstance(exc, openai.NotFoundError):
        return ErrorCategory.RESOURCE_NOT_FOUND
    if isinstance(exc, openai.BadRequestError):
        return ErrorCategory.INVALID_REQUEST
    if isinstance(exc, openai.APITimeoutError):
        return ErrorCategory.TIMEOUT
    if isinstance(exc, openai.APIConnectionError):
        return ErrorCategory.NETWORK
    return ErrorCategory.UNKNOWN


def _categorize_error_code(error_code: str) -> ErrorCategory:
    """Map Databricks/Responses API error codes to ErrorCategory."""
    code = str(error_code).upper()
    if code in ("UNAUTHORIZED", "UNAUTHENTICATED") or "AUTH" in code:
        return ErrorCategory.AUTH_EXPIRED
    if code in ("PERMISSION_DENIED", "FORBIDDEN"):
        return ErrorCategory.PERMISSION
    if "NOT_FOUND" in code:
        return ErrorCategory.RESOURCE_NOT_FOUND
    if code in ("BAD_REQUEST", "INVALID_PARAMETER_VALUE") or "INVALID" in code:
        return ErrorCategory.INVALID_REQUEST
    if "TIMEOUT" in code:
        return ErrorCategory.TIMEOUT
    return ErrorCategory.UNKNOWN


def _check_databricks_output(
    obj: Any, errors: List[str], error_cats: Set[ErrorCategory],
) -> None:
    """Extract errors from Databricks streaming error propagation.

    Mosaic AI propagates errors in the last streaming token under
    databricks_output.error with fields: error_code, message.
    """
    db_output = getattr(obj, "databricks_output", None)
    if db_output is None:
        return

    db_error = (
        db_output.get("error") if isinstance(db_output, dict)
        else getattr(db_output, "error", None)
    )
    if not db_error:
        return

    if isinstance(db_error, dict):
        error_code = db_error.get("error_code", "UNKNOWN")
        error_msg = db_error.get("message", str(db_error))
    else:
        error_code = getattr(db_error, "error_code", "UNKNOWN")
        error_msg = getattr(db_error, "message", str(db_error))

    errors.append(f"[{error_code}] {error_msg}"[:_Limits.ERROR_BODY])
    error_cats.add(_categorize_error_code(error_code))


def _extract_trace_id(obj: Any) -> Optional[str]:
    """Extract trace_id from databricks_output.trace.info.trace_id.

    Databricks serving endpoints include trace metadata in the
    databricks_output field when ``return_trace: True`` is requested.
    The trace_id appears on ``response.output_item.done`` (sub-agent
    traces) and ``response.completed`` (top-level supervisor trace).
    """
    db_output = getattr(obj, "databricks_output", None)
    if db_output is None:
        return None
    trace_info = (
        db_output.get("trace", {}).get("info", {})
        if isinstance(db_output, dict)
        else getattr(getattr(db_output, "trace", None), "info", None)
    )
    if trace_info is None:
        return None
    return (
        trace_info.get("trace_id")
        if isinstance(trace_info, dict)
        else getattr(trace_info, "trace_id", None)
    )


def _check_response_status(
    response: Any, errors: List[str], error_cats: Set[ErrorCategory],
) -> None:
    """Check Responses API status and error fields on the response object."""
    status = getattr(response, "status", "completed")

    if status == "failed":
        error_obj = getattr(response, "error", None)
        if error_obj:
            code = (
                getattr(error_obj, "code", None)
                or getattr(error_obj, "error_code", "UNKNOWN")
            )
            msg = getattr(error_obj, "message", str(error_obj))
            errors.append(f"Response failed: [{code}] {msg}"[:_Limits.ERROR_BODY])
            error_cats.add(_categorize_error_code(str(code)))
        else:
            errors.append("Response failed (no error details)")
            error_cats.add(ErrorCategory.UNKNOWN)

    elif status == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", "unknown") if details else "unknown"
        errors.append(f"Response incomplete: {reason}"[:_Limits.ERROR_BODY])
        error_cats.add(ErrorCategory.UNKNOWN)


# ---------------------------------------------------------------------------
# CSV extraction helpers
# ---------------------------------------------------------------------------

_RESULT_CSV_MIN_ROWS = 2  # minimum data rows to trigger CSV storage


def _parse_markdown_tables(text: str) -> List[Dict[str, Any]]:
    """Extract markdown tables from text. Returns list of {headers, rows} dicts."""
    tables: List[Dict[str, Any]] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and line.endswith("|") and "|" in line[1:-1]:
            headers = [h.strip() for h in line.split("|")[1:-1]]
            if i + 1 < len(lines) and re.match(r"^\|[\s\-:]+\|", lines[i + 1].strip()):
                i += 2  # skip separator
                rows: List[List[str]] = []
                while i < len(lines):
                    row_line = lines[i].strip()
                    if row_line.startswith("|") and row_line.endswith("|"):
                        row = [c.strip() for c in row_line.split("|")[1:-1]]
                        rows.append(row)
                        i += 1
                    else:
                        break
                if rows:
                    tables.append({"headers": headers, "rows": rows})
                continue
        i += 1
    return tables


def _parse_pipe_delimited_table(text: str) -> Optional[Dict[str, Any]]:
    """Parse pipe-delimited text that may lack a markdown separator row.

    Handles sub-agent responses where data is pipe-separated across multiple
    lines without the standard markdown |---|---| separator line.
    """
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    if len(lines) < 3 or "|" not in lines[0]:
        return None
    raw_headers = lines[0].split("|")
    headers = [h.strip() for h in raw_headers if h.strip()]
    if len(headers) < 2:
        return None
    start = 1
    if start < len(lines) and re.match(r'^[\|:\s\-]+$', lines[start]):
        start += 1
    rows: List[List[str]] = []
    for line in lines[start:]:
        if "|" not in line:
            continue
        cells = line.split("|")
        clean = [c.strip() for c in cells]
        if clean and clean[0] == '':
            clean = clean[1:]
        if clean and clean[-1] == '':
            clean = clean[:-1]
        if clean and abs(len(clean) - len(headers)) <= 1:
            if len(clean) != len(headers):
                logger.debug("Row column count mismatch: %d cols vs %d headers, padding/truncating", len(clean), len(headers))
            if len(clean) < len(headers):
                clean.extend([''] * (len(headers) - len(clean)))
            elif len(clean) > len(headers):
                clean = clean[:len(headers)]
            rows.append(clean)
    if len(rows) >= _RESULT_CSV_MIN_ROWS:
        return {"headers": headers, "rows": rows}
    return None


def _write_result_csv(
    base_path: str, thread_id: str, message_id: str,
    headers: List[str], rows: List[List[str]],
    writer: Optional[VolumeWriter] = None,
) -> Tuple[Dict[str, Any], str]:
    """Write CSV to Volumes and return (meta_dict, file_path).

    Uses the provided VolumeWriter (FUSE or SDK). Defaults to FuseVolumeWriter
    for backward compatibility when writer is None.
    """
    # Defensive path sanitization to prevent directory traversal
    for label, val in (("thread_id", thread_id), ("message_id", message_id)):
        if ".." in val or "/" in val or "\\" in val:
            raise ValueError(f"Invalid {label}: must not contain path separators or '..': {val!r}")
    dir_path = f"{base_path}/{thread_id}"
    file_path = f"{dir_path}/{message_id}.csv"
    _writer = writer or FuseVolumeWriter()
    _writer.make_dirs(dir_path)
    # Write CSV to in-memory buffer, then flush via writer
    buf = io.StringIO()
    csv_writer = csv.writer(buf)
    csv_writer.writerow(headers)
    csv_writer.writerows(rows)
    csv_bytes = buf.getvalue().encode("utf-8")
    _writer.write_file(file_path, csv_bytes)
    meta = {
        "row_count": len(rows),
        "col_count": len(headers),
        "columns": headers,
        "file_path": file_path,
        "file_size_bytes": len(csv_bytes),
    }
    return meta, file_path


def _extract_and_store_result(
    base_path: str, thread_id: str, message_id: str,
    tool_calls: List[Dict[str, Any]], final_answer: str,
    raw_messages: Optional[List[str]] = None,
    writer: Optional[VolumeWriter] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
    """Extract tabular data from ALL sources and write as CSV files.

    Collect-all strategy: gathers candidate tables from all 3 priorities
    (not a waterfall). Deduplicates by header set and writes each unique
    table as a separate CSV file.

    Priorities (all checked):
        1. Raw function_call_output that is a JSON array of dicts
        2. Sub-agent message tables (markdown/pipe-delimited)
        3. Markdown tables in final_answer

    Returns:
        (primary_meta, primary_file_path, all_files)
    """
    if not base_path:
        return None, None, []
    try:
        # Candidate tuples: (headers, rows, source, agent)
        candidates: List[Tuple[List[str], List[List[str]], str, str]] = []
        seen_headers: set = set()

        # Priority 1: Raw tool outputs (JSON array of dicts)
        for tc in (tool_calls or []):
            raw = tc.get("raw_output", "")
            if not raw:
                continue
            try:
                data = json.loads(raw)
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    if len(data) >= _RESULT_CSV_MIN_ROWS:
                        headers = list(data[0].keys())
                        hkey = frozenset(headers)
                        if hkey not in seen_headers:
                            rows = [[str(row.get(h, "")) for h in headers] for row in data]
                            candidates.append((headers, rows, "raw_tool_output", tc.get("agent", "")))
                            seen_headers.add(hkey)
            except (json.JSONDecodeError, TypeError):
                continue

        # Priority 2: Sub-agent message tables (markdown or pipe-delimited)
        if raw_messages:
            for text in raw_messages:
                tables = _parse_markdown_tables(text)
                for tbl in tables:
                    if len(tbl["rows"]) >= _RESULT_CSV_MIN_ROWS:
                        hkey = frozenset(tbl["headers"])
                        if hkey not in seen_headers:
                            candidates.append((tbl["headers"], tbl["rows"], "subagent_message", ""))
                            seen_headers.add(hkey)
                pdt = _parse_pipe_delimited_table(text)
                if pdt and len(pdt["rows"]) >= _RESULT_CSV_MIN_ROWS:
                    hkey = frozenset(pdt["headers"])
                    if hkey not in seen_headers:
                        candidates.append((pdt["headers"], pdt["rows"], "subagent_message", ""))
                        seen_headers.add(hkey)

        # Priority 3: Markdown tables in final_answer
        if final_answer:
            tables = _parse_markdown_tables(final_answer)
            for tbl in tables:
                if len(tbl["rows"]) >= _RESULT_CSV_MIN_ROWS:
                    hkey = frozenset(tbl["headers"])
                    if hkey not in seen_headers:
                        candidates.append((tbl["headers"], tbl["rows"], "markdown_table", ""))
                        seen_headers.add(hkey)

        if not candidates:
            return None, None, []

        # Sort by row count descending -- largest becomes primary
        candidates.sort(key=lambda c: len(c[1]), reverse=True)

        all_files: List[Dict[str, Any]] = []
        primary_meta = None
        primary_fpath = None

        for idx, (headers, rows, source, agent) in enumerate(candidates):
            suffix = "" if idx == 0 else f"_{idx}"
            file_message_id = f"{message_id}{suffix}"
            meta, fpath = _write_result_csv(
                base_path, thread_id, file_message_id, headers, rows,
                writer=writer,
            )
            meta["source"] = source
            if agent:
                meta["agent"] = agent
            all_files.append(meta)
            if idx == 0:
                primary_meta = meta
                primary_fpath = fpath
                logger.info("Result CSV (primary, %s): %s (%d rows x %d cols)",
                           source, fpath, meta["row_count"], meta["col_count"])
            else:
                logger.info("Result CSV (%s #%d): %s (%d rows x %d cols)",
                           source, idx, fpath, meta["row_count"], meta["col_count"])

        # Backward compat: additional_files reference in primary_meta
        if len(all_files) > 1:
            primary_meta["additional_files"] = all_files[1:]

        return primary_meta, primary_fpath, all_files
    except Exception as exc:
        logger.warning("Failed to write result CSV: %s", exc)
        return None, None, []


def _strip_raw_outputs(tool_calls: List[Dict[str, Any]]) -> None:
    """Remove raw_output from tool_calls to avoid memory bloat after CSV extraction."""
    for tc in (tool_calls or []):
        tc.pop("raw_output", None)


def _extract_raw_messages(response: Any) -> List[str]:
    """Extract large text content from intermediate message items in Responses API output.

    Sub-agent responses appear as MESSAGE items in the response output array.
    This helper extracts those large text payloads for tabular data parsing.
    Excludes the final message (the assistant's summary) and short messages.
    """
    texts: List[str] = []
    try:
        output = getattr(response, 'output', None) or []
        message_texts: List[str] = []
        for item in output:
            itype = getattr(item, 'type', '') if not isinstance(item, dict) else item.get('type', '')
            if itype == 'message':
                item_content = getattr(item, 'content', []) if not isinstance(item, dict) else item.get('content', [])
                for c in item_content:
                    text = getattr(c, 'text', '') if not isinstance(c, dict) else c.get('text', '')
                    if text:
                        message_texts.append(text)
        # Exclude the last message (final_answer) and short texts
        if message_texts:
            for text in message_texts[:-1]:
                if len(text) > _Limits.RAW_MESSAGE_MIN_LEN:
                    texts.append(text)
    except Exception:
        pass
    return texts



# ---------------------------------------------------------------------------
# Shared constants and config helpers (used by streaming and client modules)
# ---------------------------------------------------------------------------

_NS_THREADS = ("threads",)
_NS_BY_USER = ("by_user",)
_NS_BY_CORRELATION = ("by_correlation",)
_NS_MESSAGES = ("messages",)


def _sanitize_ns(value: str) -> str:
    """Sanitize a value for use as a store namespace component.

    Dots are not allowed in LangGraph store namespace tuples.
    """
    return value.replace(".", "-")


def _now_iso() -> str:
    """UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _build_config(
    thread_id: str,
    *,
    checkpoint_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict:
    """Build a LangGraph RunnableConfig with configurable fields."""
    config: dict = {"configurable": {"thread_id": thread_id}}
    if checkpoint_id:
        config["configurable"]["checkpoint_id"] = checkpoint_id
    if user_id:
        config["configurable"]["user_id"] = user_id
    return config


# Public API: only non-private names are exported via `import *`.
# The client imports private helpers explicitly by name.
__all__ = [
    "AgentResult",
    "ErrorCategory",
    "FuseVolumeWriter",
    "SdkVolumeWriter",
    "StreamEvent",
    "TestReport",
    "VolumeWriter",
]
