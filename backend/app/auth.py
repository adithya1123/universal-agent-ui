import asyncio
import base64
import json
import time
from enum import Enum

import httpx

from app.config import settings


class AuthMethod(str, Enum):
    OAUTH = "oauth"
    PAT = "pat"
    CLI = "cli"
    NONE = "none"


_token_lock: asyncio.Lock = asyncio.Lock()

_oauth_token: str | None = None
_oauth_token_expires_at: float = 0

_pat_token: str | None = None
_pat_token_expires_at: float = 0

_cli_token: str | None = None
_cli_token_expires_at: float = 0


def detect_auth_method() -> AuthMethod:
    if (
        settings.databricks_client_id
        and settings.databricks_client_secret
        and settings.databricks_host
    ):
        return AuthMethod.OAUTH
    if settings.databricks_token and settings.databricks_host:
        return AuthMethod.PAT
    if settings.databricks_config_profile:
        return AuthMethod.CLI
    if settings.databricks_host:
        return AuthMethod.CLI
    return AuthMethod.NONE


async def get_oauth_token() -> str:
    global _oauth_token, _oauth_token_expires_at

    if _oauth_token and time.monotonic() < _oauth_token_expires_at:
        return _oauth_token

    async with _token_lock:
        if _oauth_token and time.monotonic() < _oauth_token_expires_at:
            return _oauth_token

        host = settings.databricks_host.rstrip("/")
        token_url = f"{host}/oidc/v1/token"

        client_id = settings.databricks_client_id
        client_secret = settings.databricks_client_secret

        basic_auth = base64.b64encode(
            f"{client_id}:{client_secret}".encode()
        ).decode()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    token_url,
                    data={"grant_type": "client_credentials", "scope": "all-apis"},
                    headers={
                        "Authorization": f"Basic {basic_auth}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"OAuth token request failed: {e.response.status_code} {e.response.text}"
            )
        except (httpx.RequestError, json.JSONDecodeError, KeyError) as e:
            raise RuntimeError(f"OAuth token request failed: {e}")

        _oauth_token = data.get("access_token")
        if not _oauth_token:
            raise RuntimeError(
                f"OAuth response missing access_token: {data}"
            )

        expires_in = data.get("expires_in", 3600)
        buffer = min(600, expires_in // 5)
        _oauth_token_expires_at = time.monotonic() + (expires_in - buffer)

        return _oauth_token


async def get_pat_token() -> str:
    global _pat_token, _pat_token_expires_at

    if _pat_token and time.monotonic() < _pat_token_expires_at:
        return _pat_token

    async with _token_lock:
        if _pat_token and time.monotonic() < _pat_token_expires_at:
            return _pat_token

        _pat_token = settings.databricks_token
        _pat_token_expires_at = time.monotonic() + 3600

        return _pat_token


async def get_cli_token() -> str:
    global _cli_token, _cli_token_expires_at

    if _cli_token and time.monotonic() < _cli_token_expires_at:
        return _cli_token

    async with _token_lock:
        if _cli_token and time.monotonic() < _cli_token_expires_at:
            return _cli_token

        args = ["databricks", "auth", "token", "--output", "json"]
        profile = settings.databricks_config_profile
        if profile:
            args.extend(["--profile", profile])
        if settings.databricks_host:
            host = settings.databricks_host.replace("https://", "").replace("http://", "").rstrip("/")
            args.extend(["--host", host])

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(
                f"Databricks CLI auth token failed: {stderr.decode().strip()}"
            )

        stdout_str = stdout.decode()
        try:
            data = json.loads(stdout_str)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"Databricks CLI returned invalid JSON: {stdout_str.strip()}"
            )
        _cli_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        buffer = min(300, expires_in // 6)
        _cli_token_expires_at = time.monotonic() + (expires_in - buffer)

        return _cli_token


async def get_databricks_token() -> str:
    method = detect_auth_method()

    if method == AuthMethod.OAUTH:
        return await get_oauth_token()
    elif method == AuthMethod.PAT:
        return await get_pat_token()
    elif method == AuthMethod.CLI:
        return await get_cli_token()

    raise RuntimeError(
        "No Databricks authentication configured. Set one of:\n"
        "- DATABRICKS_HOST + DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET (OAuth)\n"
        "- DATABRICKS_HOST + DATABRICKS_TOKEN (PAT)\n"
        "- DATABRICKS_CONFIG_PROFILE (CLI auth)"
    )
