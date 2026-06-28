"""Streaming primitives for the LangGraph supervisor client.

Contains:
    - AsyncStreamingResponse: parses a single Responses API stream
    - _ApprovalLoopStream: auto-approves MCP tool approval requests
    - _PersistingStreamWrapper: persists state after stream consumption
"""

from __future__ import annotations

import json
import logging
import mlflow
import re
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional, Set

try:
    from databricks_langchain import AsyncDatabricksStore
except ImportError:
    raise ImportError(
        "databricks-langchain[memory] is required. "
        "Install with: pip install 'databricks-langchain[memory]' --upgrade"
    )

try:
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
except ImportError:
    raise ImportError(
        "langchain-core is required. "
        "Install with: pip install langchain-core --upgrade"
    )

try:
    from langgraph.store.base import GetOp, PutOp
except ImportError:
    raise ImportError(
        "langgraph is required. "
        "Install with: pip install langgraph --upgrade"
    )

from app.memory import MemoryExtractor, UserMemoryService
from app.supervisor.helpers import (
    AgentResult,
    ErrorCategory,
    StreamEvent,
    VolumeWriter,
    _Limits,
    _categorize_exception,
    _categorize_message_error,
    _check_databricks_output,
    _check_response_status,
    _extract_and_store_result,
    _extract_text_from_item,
    _extract_trace_id,
    _NS_BY_CORRELATION,
    _NS_BY_USER,
    _NS_THREADS,
    _safe_to_dict,
    _sanitize_ns,
    _strip_raw_outputs,
    _summarize_args,
    _summarize_tool_output,
    _trunc,
)

logger = logging.getLogger(__name__)

_StreamFactory = Callable[[List[Dict[str, Any]]], Awaitable[Any]]


def _extract_plotly_spec(text: str) -> Optional[dict]:
    """Walk a string for the first JSON payload containing a plotly_spec key."""
    if not text or "plotly_spec" not in text:
        return None
    try:
        parsed = json.loads(text)
        if "plotly_spec" in parsed:
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    for m in re.finditer(r"\{", text):
        try:
            parsed = json.loads(text[m.start():])
            if "plotly_spec" in parsed:
                return parsed
        except (json.JSONDecodeError, ValueError):
            continue
    return None

def _item_get(item: Any, key: str, default: Any = None) -> Any:
    """Read an attribute from either an SDK object or a plain dict."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _serialize_output_item(item: Any) -> Dict[str, Any]:
    """Convert a Responses output item to a plain dict for replay."""
    if isinstance(item, dict):
        return item
    try:
        if hasattr(item, "model_dump"):
            return item.model_dump(exclude_none=True)
        if hasattr(item, "to_dict"):
            return item.to_dict()
    except Exception:
        pass

    raw = _safe_to_dict(item)
    if raw and raw != {"output": str(item)[:_Limits.RAW_BODY]}:
        return raw

    result: Dict[str, Any] = {"type": _item_get(item, "type", "unknown")}
    for field in (
        "id",
        "name",
        "server_label",
        "arguments",
        "status",
        "output",
        "step",
        "approval_request_id",
        "approve",
        "content",
    ):
        value = _item_get(item, field)
        if value is not None:
            result[field] = value
    return result


def _build_approval_response(approval_request_id: str) -> Dict[str, Any]:
    """Build the Supervisor API MCP approval response payload."""
    return {
        "type": "mcp_approval_response",
        "id": approval_request_id,
        "approval_request_id": approval_request_id,
        "approve": True,
    }


class AsyncStreamingResponse:
    """Async iterable streaming response that yields StreamEvent objects.

    Full async streaming implementation: ``async for`` over the OpenAI async
    stream, full error detection, and assembled AgentResult accessible via
    ``.result`` after iteration.
    """

    def __init__(
        self,
        openai_stream: Any,
        question: str,
        start_time: float,
        store_raw: bool = False,
    ) -> None:
        self._stream = openai_stream
        self._question = question
        self._start_time = start_time
        self._store_raw = store_raw
        self._result: Optional[AgentResult] = None
        self._trace_id: Optional[str] = None
        self._consumed = False
        self._message_texts: List[str] = []
        self._output_items: List[Dict[str, Any]] = []
        self._approval_requests: List[Dict[str, Any]] = []

    @classmethod
    def _from_error(cls, result: AgentResult) -> "AsyncStreamingResponse":
        """Create a pre-failed response for connection-level errors."""
        sr = cls.__new__(cls)
        sr._stream = None
        sr._question = result.question
        sr._start_time = 0
        sr._store_raw = False
        sr._result = result
        sr._trace_id = None
        sr._consumed = True
        sr._message_texts = []
        sr._output_items = []
        sr._approval_requests = []
        return sr

    async def __aiter__(self) -> AsyncGenerator[StreamEvent, None]:
        if self._consumed:
            return

        tool_calls: List[Dict[str, Any]] = []
        errors: List[str] = []
        error_cats: Set[ErrorCategory] = set()
        final_answer = ""
        raw_events: Optional[List[Dict[str, Any]]] = [] if self._store_raw else None
        message_texts: List[str] = []
        plotly_blocks: List[str] = []

        _db_output_checked = False

        try:
            async for event in self._stream:
                event_type = getattr(event, "type", "")
                logger.debug("RAW EVENT: type=%s", event_type)

                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    final_answer += delta
                    yield StreamEvent(type="text_delta", text=delta)

                elif event_type == "response.output_item.done":
                    item = getattr(event, "item", None)
                    if item:
                        self._output_items.append(_serialize_output_item(item))
                        itype = _item_get(item, "type", "")
                        if itype == "function_call":
                            name = _item_get(item, "name", "unknown")
                            step = _item_get(item, "step", "?")
                            args = _item_get(item, "arguments", "{}")
                            tool_calls.append({
                                "step": step,
                                "agent": name,
                                "args_summary": _summarize_args(args),
                                "outcome": "",
                            })
                            yield StreamEvent(
                                type="routing",
                                agent=name,
                                step=step,
                                item_type="function_call",
                            )
                        elif itype == "function_call_output":
                            output = _item_get(item, "output", "")
                            err_cat = _categorize_message_error(output)
                            if err_cat:
                                errors.append(output[:_Limits.MESSAGE_ERROR])
                                error_cats.add(err_cat)
                            if tool_calls:
                                tool_calls[-1]["outcome"] = _summarize_tool_output(output)
                                tool_calls[-1]["raw_output"] = output
                            yield StreamEvent(
                                type="item_done",
                                item_type="function_call_output",
                                text=_trunc(output, 200),
                            )
                            for candidate_text in [output] + [
                                (isinstance(b, dict) and (b.get("text") or b.get("output") or ""))
                                or (hasattr(b, "text") and getattr(b, "text", ""))
                                or (hasattr(b, "output") and getattr(b, "output", ""))
                                or ""
                                for b in (_item_get(item, "content") or [])
                            ]:
                                pspec = _extract_plotly_spec(candidate_text)
                                if pspec:
                                    plotly_blocks.append(
                                        f"\n\n```plotly\n{json.dumps(pspec)}\n```\n\n"
                                    )
                                    yield StreamEvent(
                                        type="plotly_spec",
                                        text=json.dumps(pspec),
                                    )
                        elif itype == "message":
                            text = _extract_text_from_item(item)
                            if text:
                                err_cat = _categorize_message_error(text)
                                if err_cat:
                                    errors.append(text[:_Limits.MESSAGE_ERROR])
                                    error_cats.add(err_cat)
                                if not text.startswith("<name>"):
                                    final_answer = text
                                    message_texts.append(text)
                            yield StreamEvent(
                                type="item_done",
                                item_type="message",
                                text=_trunc(text or "", 200),
                            )
                            for candidate_text in [text or ""] + [
                                (isinstance(b, dict) and (b.get("text") or b.get("output") or ""))
                                or (hasattr(b, "text") and getattr(b, "text", ""))
                                or (hasattr(b, "output") and getattr(b, "output", ""))
                                or ""
                                for b in (_item_get(item, "content") or [])
                            ]:
                                pspec = _extract_plotly_spec(candidate_text)
                                if pspec:
                                    plotly_blocks.append(
                                        f"\n\n```plotly\n{json.dumps(pspec)}\n```\n\n"
                                    )
                                    yield StreamEvent(
                                        type="plotly_spec",
                                        text=json.dumps(pspec),
                                    )
                        elif itype == "mcp_approval_request":
                            request = {
                                "id": _item_get(item, "id"),
                                "name": _item_get(item, "name", "unknown"),
                                "server_label": _item_get(item, "server_label", ""),
                                "arguments": _item_get(item, "arguments", "{}"),
                                "status": _item_get(item, "status", "completed"),
                            }
                            self._approval_requests.append(request)
                            yield StreamEvent(
                                type="tool_approval",
                                agent=request["name"],
                                item_type="mcp_approval_request",
                                text=f"Approval requested for {request['name']}",
                                metadata=request,
                            )
                        else:
                            yield StreamEvent(
                                type="item_done",
                                item_type=itype,
                            )

                elif event_type == "response.reasoning_summary_text.delta":
                    delta = getattr(event, "delta", "")
                    yield StreamEvent(type="reasoning", text=delta)

                elif event_type == "response.output_text.annotation.added":
                    yield StreamEvent(type="annotation")

                elif event_type == "response.completed":
                    resp = getattr(event, "response", None)
                    if resp:
                        _check_response_status(resp, errors, error_cats)
                        _check_databricks_output(resp, errors, error_cats)
                        _db_output_checked = True
                    yield StreamEvent(type="completed")

                elif event_type == "response.failed":
                    resp = getattr(event, "response", None)
                    if resp:
                        _check_response_status(resp, errors, error_cats)
                        _check_databricks_output(resp, errors, error_cats)
                    else:
                        errors.append("Response failed (no details)")
                        error_cats.add(ErrorCategory.UNKNOWN)
                    _db_output_checked = True
                    yield StreamEvent(type="completed")

                elif event_type == "response.incomplete":
                    resp = getattr(event, "response", None)
                    details = getattr(resp, "incomplete_details", None) if resp else None
                    reason = getattr(details, "reason", "unknown") if details else "unknown"
                    errors.append(f"Response incomplete: {reason}"[:_Limits.ERROR_BODY])
                    error_cats.add(ErrorCategory.UNKNOWN)
                    if resp:
                        _check_databricks_output(resp, errors, error_cats)
                    _db_output_checked = True
                    yield StreamEvent(type="completed")

                _evt_trace_id = _extract_trace_id(event)
                if _evt_trace_id:
                    self._trace_id = _evt_trace_id

                if not _db_output_checked:
                    _check_databricks_output(event, errors, error_cats)

                _db_output_checked = False
                if raw_events is not None:
                    raw_events.append({"type": event_type})

        except Exception as e:
            error_cats.add(_categorize_exception(e))
            errors.append(str(e)[:_Limits.ERROR_BODY])
            logger.error("Async stream error: %s", e)
        latency = time.time() - self._start_time
        if plotly_blocks:
            final_answer += "".join(plotly_blocks)
        self._result = AgentResult(
            question=self._question,
            status_code=200 if not errors else 500,
            latency_s=latency,
            final_answer=final_answer,
            tool_calls=tool_calls,
            errors=errors,
            error_categories=error_cats,
            raw={"events": raw_events, "count": len(raw_events)} if self._store_raw and raw_events else None,
        )
        self._result.trace_id = self._trace_id
        self._message_texts = message_texts
        self._consumed = True

    @property
    def result(self) -> AgentResult:
        """Get the final AgentResult. Must iterate first (async for)."""
        if not self._consumed:
            raise RuntimeError(
                "Stream not consumed. Use 'async for event in stream' before accessing .result"
            )
        return self._result

    @property
    def trace_id(self) -> Optional[str]:
        """Top-level trace_id from databricks_output after stream consumption."""
        return self._trace_id


class _ApprovalLoopStream(AsyncStreamingResponse):
    """Wrapper stream that auto-approves Supervisor MCP approval requests."""

    def __init__(
        self,
        stream_factory: _StreamFactory,
        initial_input: List[Dict[str, Any]],
        question: str,
        start_time: float,
        store_raw: bool = False,
        max_approval_rounds: int = 5,
    ) -> None:
        self._stream_factory = stream_factory
        self._initial_input = list(initial_input)
        self._question = question
        self._start_time = start_time
        self._store_raw = store_raw
        self._max_approval_rounds = max_approval_rounds
        self._result: Optional[AgentResult] = None
        self._trace_id: Optional[str] = None
        self._consumed = False
        self._message_texts: List[str] = []
        self._output_items: List[Dict[str, Any]] = []
        self._approval_requests: List[Dict[str, Any]] = []

    async def __aiter__(self) -> AsyncGenerator[StreamEvent, None]:
        if self._consumed:
            return

        conversation_items = list(self._initial_input)
        all_tool_calls: List[Dict[str, Any]] = []
        all_errors: List[str] = []
        all_error_cats: Set[ErrorCategory] = set()
        all_raw_events: Optional[List[Dict[str, Any]]] = [] if self._store_raw else None
        final_answer = ""
        round_idx = 0

        while True:
            try:
                openai_stream = await self._stream_factory(conversation_items)
            except Exception as e:
                all_error_cats.add(_categorize_exception(e))
                all_errors.append(str(e)[:_Limits.ERROR_BODY])
                logger.error("Approval loop stream creation failed: %s", e)
                break

            round_stream = AsyncStreamingResponse(
                openai_stream,
                self._question,
                self._start_time,
                self._store_raw,
            )

            async for event in round_stream:
                if event.type != "completed":
                    yield event

            round_result = round_stream.result
            all_tool_calls.extend(round_result.tool_calls)
            all_errors.extend(round_result.errors)
            all_error_cats.update(round_result.error_categories)
            if round_result.final_answer:
                final_answer = round_result.final_answer
            if round_result.raw and all_raw_events is not None:
                all_raw_events.extend(round_result.raw.get("events", []))
            if round_stream.trace_id:
                self._trace_id = round_stream.trace_id

            self._message_texts.extend(getattr(round_stream, "_message_texts", []) or [])
            self._output_items.extend(getattr(round_stream, "_output_items", []) or [])
            self._approval_requests = getattr(round_stream, "_approval_requests", []) or []
            conversation_items.extend(getattr(round_stream, "_output_items", []) or [])

            if not self._approval_requests:
                break

            round_idx += 1
            if round_idx > self._max_approval_rounds:
                all_errors.append(
                    f"Exceeded MCP approval round limit: {self._max_approval_rounds}"[:_Limits.ERROR_BODY]
                )
                all_error_cats.add(ErrorCategory.UNKNOWN)
                break

            for request in self._approval_requests:
                if request.get("id"):
                    conversation_items.append(_build_approval_response(request["id"]))
                    yield StreamEvent(
                        type="tool_approval",
                        agent=request.get("name", "unknown"),
                        item_type="mcp_approval_response",
                        text=f"Auto-approved {request.get('name', 'tool')}",
                        metadata=request,
                    )

        latency = time.time() - self._start_time
        self._result = AgentResult(
            question=self._question,
            status_code=200 if not all_errors else 500,
            latency_s=latency,
            final_answer=final_answer,
            tool_calls=all_tool_calls,
            errors=all_errors,
            error_categories=all_error_cats,
            raw={"events": all_raw_events, "count": len(all_raw_events)} if self._store_raw and all_raw_events else None,
        )
        self._result.trace_id = self._trace_id
        self._consumed = True
        yield StreamEvent(type="completed")


class _PersistingStreamWrapper(AsyncStreamingResponse):
    """Persist assistant state and derived metadata after stream consumption."""

    def __init__(
        self,
        inner: AsyncStreamingResponse,
        graph: Any,
        store: AsyncDatabricksStore,
        config: dict,
        messages: List[BaseMessage],
        thread_id: str,
        message_id: str,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        result_volume: str = "",
        title: Optional[str] = None,
        volume_writer: Optional[VolumeWriter] = None,
        memory_extractor: Optional[MemoryExtractor] = None,
        user_memory_service: Optional[UserMemoryService] = None,
        extraction_disabled_ref: Optional[List[bool]] = None,
    ) -> None:
        self._inner = inner
        self._result: Optional[AgentResult] = None
        self._trace_id: Optional[str] = None
        self._consumed = False
        self._graph_ref = graph
        self._store_ref = store
        self._config = config
        self._messages = messages
        self._thread_id = thread_id
        self._message_id = message_id
        self._user_id = user_id
        self._correlation_id = correlation_id
        self._result_volume = result_volume
        self._title = title
        self._volume_writer = volume_writer
        self._memory_extractor = memory_extractor
        self._user_memory_service = user_memory_service
        self._extraction_disabled_ref = extraction_disabled_ref

    @property
    def _question(self) -> str:
        """Delegate to inner stream for backward compatibility."""
        return self._inner._question

    async def __aiter__(self) -> AsyncGenerator[StreamEvent, None]:
        async for event in self._inner:
            yield event

        self._result = self._inner._result
        self._trace_id = self._inner._trace_id
        self._consumed = True

        is_first_turn = False
        if self._result:
            self._result.message_id = self._result.trace_id or self._message_id
            message_texts = getattr(self._inner, "_message_texts", None) or []
            raw_messages = None
            if len(message_texts) > 1:
                raw_messages = [
                    text for text in message_texts[:-1]
                    if len(text) > _Limits.RAW_MESSAGE_MIN_LEN
                ]
            meta, fpath, all_files = _extract_and_store_result(
                self._result_volume,
                self._thread_id,
                self._message_id,
                self._result.tool_calls,
                self._result.final_answer or "",
                raw_messages=raw_messages,
                writer=self._volume_writer,
            )
            _strip_raw_outputs(self._result.tool_calls)
            self._result.result_meta = meta
            self._result.result_file_path = fpath
            self._result.result_files = all_files if all_files else None

        if self._result:
            # Check if first turn + load existing results_index in one read
            is_first_turn = False
            existing_results = []
            try:
                if self._graph_ref:
                    snap = await self._graph_ref.aget_state(self._config)
                    state_vals = snap.values or {}
                    prior_msg_count = len(state_vals.get("messages", []))
                    existing_results = list(state_vals.get("results_index", []))
                    is_first_turn = prior_msg_count == 0
            except Exception:
                pass

            answer = self._result.final_answer or "[No response from agent]"
            self._messages.append(AIMessage(content=answer))

            turn_entry = {
                "message_id": self._message_id,
                "question": self._result.question[:500],
                "csv_path": self._result.result_file_path,
                "result_meta": self._result.result_meta,
                "all_files": [
                    f["file_path"] for f in (self._result.result_files or [])
                ] if self._result.result_files else [],
                "latency_s": round(self._result.latency_s, 2),
                "num_steps": self._result.num_steps,
                "success": self._result.success,
            }
            existing_results.append(turn_entry)

            try:
                await self._graph_ref.aupdate_state(
                    self._config,
                    {"messages": self._messages, "results_index": existing_results},
                    as_node="passthrough",
                )
            except Exception as e:
                logger.warning("Failed to persist AI response to checkpoint: %s", e)

            if is_first_turn and self._user_id:
                title = self._question.strip().replace("\n", " ")[:100]
                try:
                    user_ns = (*_NS_BY_USER, _sanitize_ns(self._user_id))
                    get_results = await self._store_ref.abatch([
                        GetOp(namespace=_NS_THREADS, key=self._thread_id),
                        GetOp(namespace=user_ns, key=self._thread_id),
                    ])
                    existing_thread, existing_user = get_results

                    put_ops = []
                    if existing_thread:
                        put_ops.append(PutOp(
                            namespace=_NS_THREADS,
                            key=self._thread_id,
                            value={**existing_thread.value, "title": title},
                        ))
                    if existing_user:
                        put_ops.append(PutOp(
                            namespace=user_ns,
                            key=self._thread_id,
                            value={**existing_user.value, "title": title},
                        ))

                    corr_id = existing_thread.value.get("correlation_id") if existing_thread else None
                    if corr_id:
                        corr_ns = (*_NS_BY_CORRELATION, _sanitize_ns(corr_id))
                        existing_corr = await self._store_ref.aget(corr_ns, self._thread_id)
                        if existing_corr:
                            put_ops.append(PutOp(
                                namespace=corr_ns,
                                key=self._thread_id,
                                value={**existing_corr.value, "title": title},
                            ))

                    if put_ops:
                        await self._store_ref.abatch(put_ops)
                except Exception as e:
                    logger.warning("Failed to update thread title: %s", e)

        if self._result:
            self._result.title = self._question.strip().replace("\n", " ")[:100] if is_first_turn else self._title

        # -- Memory extraction (auto-detect storable facts from conversation) --
        if self._memory_extractor and self._user_id and self._user_memory_service:
            try:
                from app.config import settings

                # Gate 1: skip if assistant response is too short (routing-only turns)
                assistant_len = 0
                for m in reversed(self._messages):
                    if not isinstance(m, HumanMessage):
                        assistant_len = len(getattr(m, "content", "") or "")
                        break
                if 0 < assistant_len < settings.memory_extraction_min_message_length:
                    logger.debug(
                        "Skipping memory extraction: short response (%d chars)",
                        assistant_len,
                    )
                else:
                    # Gate 2: rate-limit via cooldown
                    cooldown_key = "_system_extraction_cooldown"
                    last = await self._user_memory_service.get_memory(self._user_id, cooldown_key)
                    last_ts = (last or {}).get("value", "")
                    cooldown_active = False
                    if last_ts:
                        try:
                            delta = datetime.now(timezone.utc) - datetime.fromisoformat(last_ts)
                            if delta < timedelta(minutes=settings.memory_extraction_cooldown_minutes):
                                cooldown_active = True
                        except (ValueError, TypeError):
                            pass  # broken timestamp → proceed

                    if cooldown_active:
                        logger.debug(
                            "Skipping memory extraction: within cooldown",
                        )
                    else:
                        await self._do_memory_extraction(settings)
            except PermissionError:
                logger.warning(
                    "Memory extraction disabled: App Service Principal lacks "
                    "'Can Query' on serving endpoint '%s'. Skipping extraction.",
                    self._thread_id,
                )
                self._memory_extractor = None
                if self._extraction_disabled_ref is not None:
                    self._extraction_disabled_ref[0] = True
            except Exception as e:
                logger.warning("Memory extraction failed for thread %s: %s", self._thread_id, e)

        if not self._trace_id:
            logger.info("No trace_id available from stream — mlflow tags skipped")
        else:
            for attempt in range(2):
                try:
                    mlflow.set_trace_tag(self._trace_id, "thread_id", self._thread_id)
                    if self._user_id:
                        mlflow.set_trace_tag(self._trace_id, "user_id", self._user_id)
                    if self._correlation_id:
                        mlflow.set_trace_tag(self._trace_id, "correlation_id", self._correlation_id)
                    logger.info("Successfully set mlflow trace tags for %s", self._trace_id)
                    break
                except Exception:
                    if attempt == 0:
                        await __import__("asyncio").sleep(1)
                    else:
                        logger.warning("Failed to set trace tags for %s: %s", self._trace_id, traceback.format_exc())

    async def _do_memory_extraction(self, settings) -> None:
        cooldown_key = "_system_extraction_cooldown"
        await self._user_memory_service.save_memory(
            self._user_id, cooldown_key,
            {"value": datetime.now(timezone.utc).isoformat(), "category": "system"},
        )

        recent = [
            {"role": "user" if isinstance(m, HumanMessage) else "assistant",
             "content": getattr(m, "content", "") or ""}
            for m in self._messages[-settings.memory_extraction_window:]
        ]
        existing_keys = await self._user_memory_service.list_keys(self._user_id)
        new_facts = await self._memory_extractor.extract_from_turn(
            recent, existing_keys=existing_keys,
        )
        saved = 0
        for fact in new_facts:
            ok = await self._user_memory_service.save_memory(
                self._user_id, fact["key"], fact,
            )
            if ok:
                saved += 1

        if saved > 0:
            await self._user_memory_service._evict_stale(
                self._user_id,
                ttl_days=settings.memory_ttl_days,
                min_access=settings.memory_ttl_min_access,
            )

        if saved:
            logger.info(
                "Extracted and saved %d new memories for user=%s",
                saved, self._user_id,
            )


__all__ = [
    "AsyncStreamingResponse",
    "_ApprovalLoopStream",
    "_PersistingStreamWrapper",
]
