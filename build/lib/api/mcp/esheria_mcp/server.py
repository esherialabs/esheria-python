from __future__ import annotations

import argparse
import asyncio
from collections import OrderedDict, deque
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import sys
import threading
import time
from typing import Any

import anyio
import httpx
from mcp import types
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser, BearerAuthBackend
from mcp.server.auth.provider import AccessToken
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.applications import Starlette
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send
import uvicorn

from api.clients.esheria_regulatory import EsheriaClientConfig, EsheriaRegulatoryClient
from api.clients.esheria_regulatory.errors import EsheriaApiError, EsheriaError
from api.clients.esheria_regulatory.version import MCP_USER_AGENT, PACKAGE_VERSION
from api.mcp.esheria_mcp.instructions import SERVER_INSTRUCTIONS
from api.mcp.esheria_mcp.output import compact_tool_output, tool_result_text
from api.mcp.esheria_mcp.prompts import get_prompt, prompt_definitions
from api.mcp.esheria_mcp.resources import (
    read_resource,
    resource_definitions,
    resource_template_definitions,
)
from api.mcp.esheria_mcp.tools import (
    DIRECTORY_TOOL_NAMES,
    EsheriaToolRunner,
    allowed_tool_names,
    tool_definitions,
)


MCP_SERVER_VERSION = PACKAGE_VERSION
SERVER_INFO = {"name": "esheria-mcp", "version": MCP_SERVER_VERSION}
OAUTH_RESOURCE_METADATA_URL = "https://mcp.esheria.ai/.well-known/oauth-protected-resource"
OAUTH_WWW_AUTHENTICATE = f'Bearer resource_metadata="{OAUTH_RESOURCE_METADATA_URL}"'
DIRECTORY_PROFILE = "directory"
API_READ_PROFILE = "api_read"
WRITE_SCOPES = ("monitoring:write", "graph:write", "customer:write")
DATA_PRINCIPAL_KIND = "data"

LOGGER = logging.getLogger("esheria.mcp")

MCP_HTTP_REQUESTS = Counter(
    "esheria_mcp_http_requests_total",
    "Hosted MCP HTTP requests.",
    ("method", "path", "status"),
)
MCP_HTTP_LATENCY = Histogram(
    "esheria_mcp_http_request_duration_seconds",
    "Hosted MCP HTTP request latency.",
    ("method", "path"),
)
MCP_ACTIVE_REQUESTS = Gauge(
    "esheria_mcp_active_requests",
    "Hosted MCP requests currently executing.",
)
MCP_TOOL_CALLS = Counter(
    "esheria_mcp_tool_calls_total",
    "MCP tool executions.",
    ("tool", "status"),
)
MCP_TOOL_LATENCY = Histogram(
    "esheria_mcp_tool_duration_seconds",
    "MCP tool execution latency.",
    ("tool",),
)
MCP_AUTH_RESULTS = Counter(
    "esheria_mcp_auth_results_total",
    "MCP bearer-token validation results.",
    ("status",),
)
MCP_RATE_LIMITED = Counter(
    "esheria_mcp_rate_limited_total",
    "MCP requests rejected by rate or concurrency limits.",
    ("reason",),
)


def _json_log(event: str, **fields: Any) -> None:
    LOGGER.info(json.dumps({"event": event, **fields}, sort_keys=True, separators=(",", ":"), default=str))


def _harden_dependency_logging() -> None:
    # HTTPX INFO logs include full query strings. Keep token introspection,
    # source filters, and customer-profile inputs out of default service logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _csv_env(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="esheria-mcp",
        description="Esheria Regulatory Pack API MCP server",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument(
        "--stdio",
        action="store_true",
        help="Serve MCP over stdio. This is the default local transport.",
    )
    serve.add_argument(
        "--http",
        action="store_true",
        help="Serve the current MCP Streamable HTTP transport.",
    )
    serve.add_argument("--host", default=os.getenv("ESHERIA_MCP_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.getenv("ESHERIA_MCP_PORT", "8081")))
    serve.add_argument("--path", default=os.getenv("ESHERIA_MCP_PATH", "/mcp"))
    serve.add_argument("--base-url")
    serve.add_argument("--api-key")
    serve.add_argument("--timeout", type=float)
    serve.add_argument("--retry-count", type=int)
    return parser


def config_from_args(args: argparse.Namespace, *, api_key: str | None = None) -> EsheriaClientConfig:
    configured = EsheriaClientConfig.from_env().with_overrides(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout_seconds=args.timeout,
        retry_count=args.retry_count,
        user_agent=MCP_USER_AGENT,
    )
    if api_key is None:
        return configured
    return configured.with_overrides(api_key=api_key)


def _normalize_http_path(path: str) -> str:
    normalized = path.strip() or "/mcp"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized


@dataclass(frozen=True)
class McpPrincipal:
    principal_type: str
    workspace_id: str
    token_id: str
    token_type: str
    scopes: tuple[str, ...]
    pack_entitlements: tuple[str, ...]

    @property
    def scope_set(self) -> frozenset[str]:
        return frozenset(self.scopes)

    @property
    def profile_key(self) -> str:
        if self.principal_type == "oauth_access_token":
            return DIRECTORY_PROFILE
        enabled = [scope.split(":", 1)[0] for scope in WRITE_SCOPES if scope in self.scope_set]
        return API_READ_PROFILE if not enabled else "api_" + "_".join(enabled)

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        return allowed_tool_names(principal_type=self.principal_type, scopes=self.scope_set)

    def access_token(self, raw_token: str, *, resource: str) -> AccessToken:
        client_id = self.token_id or hashlib.sha256(raw_token.encode("utf-8")).hexdigest()[:24]
        return AccessToken(
            token=raw_token,
            client_id=client_id,
            scopes=list(self.scopes),
            resource=resource,
            subject=self.workspace_id or None,
            claims={
                "principal_type": self.principal_type,
                "workspace_id": self.workspace_id,
                "token_id": self.token_id,
                "token_type": self.token_type,
                "pack_entitlements": list(self.pack_entitlements),
                "profile_key": self.profile_key,
                "iss": resource.rsplit("/mcp", 1)[0],
            },
        )


def _principal_from_envelope(envelope: Any) -> McpPrincipal | None:
    data = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(data, dict):
        return None
    principal_type = str(data.get("principal_type") or "")
    token_type = str(data.get("token_type") or "")
    scopes = tuple(str(scope) for scope in (data.get("scopes") or []) if str(scope).strip())
    if principal_type not in {"api_token", "oauth_access_token"}:
        return None
    # "data" is an API token classification, not credential material.
    if token_type != DATA_PRINCIPAL_KIND or "regulatory:read" not in set(scopes):
        return None
    return McpPrincipal(
        principal_type=principal_type,
        workspace_id=str(data.get("workspace_id") or ""),
        token_id=str(data.get("api_token_id") or data.get("token_id") or ""),
        token_type=token_type,
        scopes=scopes,
        pack_entitlements=tuple(
            str(item) for item in (data.get("pack_entitlements") or []) if str(item).strip()
        ),
    )


class EsheriaTokenVerifier:
    def __init__(
        self,
        config: EsheriaClientConfig,
        *,
        protected_resource: str,
        cache_ttl_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config.with_overrides(api_key="")
        self.protected_resource = protected_resource
        self.cache_ttl_seconds = max(
            0.0,
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else float(os.getenv("ESHERIA_MCP_AUTH_CACHE_SECONDS", "15")),
        )
        self._owned_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=self.config.normalized_base_url,
            timeout=httpx.Timeout(self.config.timeout_seconds, connect=min(5.0, self.config.timeout_seconds)),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32, keepalive_expiry=30),
            headers={"accept": "application/json", "user-agent": MCP_USER_AGENT},
        )
        self._cache: dict[str, tuple[float, McpPrincipal | None]] = {}
        self._cache_lock = asyncio.Lock()

    async def verify_token(self, token: str) -> AccessToken | None:
        raw_token = str(token or "").strip()
        if not raw_token or len(raw_token) > 4096 or any(character in raw_token for character in ("\r", "\n")):
            MCP_AUTH_RESULTS.labels(status="invalid").inc()
            return None
        digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        now = time.monotonic()
        async with self._cache_lock:
            cached = self._cache.get(digest)
            if cached and cached[0] > now:
                principal = cached[1]
                MCP_AUTH_RESULTS.labels(status="cached_valid" if principal else "cached_invalid").inc()
                return principal.access_token(raw_token, resource=self.protected_resource) if principal else None

        principal: McpPrincipal | None = None
        try:
            response = await self._client.get(
                "/api/v1/oauth/introspect",
                headers={"authorization": f"Bearer {raw_token}"},
            )
            if response.status_code == 200:
                principal = _principal_from_envelope(response.json())
        except (httpx.HTTPError, ValueError):
            principal = None

        async with self._cache_lock:
            if len(self._cache) >= 2048:
                expired = [key for key, value in self._cache.items() if value[0] <= now]
                for key in expired[:1024]:
                    self._cache.pop(key, None)
                if len(self._cache) >= 2048:
                    self._cache.pop(next(iter(self._cache)))
            self._cache[digest] = (now + self.cache_ttl_seconds, principal)
        MCP_AUTH_RESULTS.labels(status="valid" if principal else "invalid").inc()
        return principal.access_token(raw_token, resource=self.protected_resource) if principal else None

    async def api_readiness(self) -> tuple[bool, dict[str, Any]]:
        try:
            response = await self._client.get("/readyz")
            payload = response.json()
            return response.status_code == 200, payload if isinstance(payload, dict) else {}
        except (httpx.HTTPError, ValueError):
            return False, {}

    async def close(self) -> None:
        if self._owned_client:
            await self._client.aclose()


def introspect_token(config: EsheriaClientConfig, raw_token: str) -> McpPrincipal | None:
    try:
        with httpx.Client(
            base_url=config.normalized_base_url,
            timeout=config.timeout_seconds,
            follow_redirects=False,
            headers={"accept": "application/json", "user-agent": MCP_USER_AGENT},
        ) as client:
            response = client.get(
                "/api/v1/oauth/introspect",
                headers={"authorization": f"Bearer {raw_token}"},
            )
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        return _principal_from_envelope(response.json())
    except ValueError:
        return None


class EsheriaClientPool:
    def __init__(self, base_config: EsheriaClientConfig, *, max_clients: int = 128) -> None:
        self.base_config = base_config.with_overrides(api_key="")
        self.max_clients = max(8, min(512, max_clients))
        self._clients: OrderedDict[str, EsheriaRegulatoryClient] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, raw_token: str) -> EsheriaRegulatoryClient:
        digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        with self._lock:
            client = self._clients.pop(digest, None)
            if client is None:
                client = EsheriaRegulatoryClient(self.base_config.with_overrides(api_key=raw_token))
            self._clients[digest] = client
            while len(self._clients) > self.max_clients:
                _old_digest, old_client = self._clients.popitem(last=False)
                old_client.close()
            return client

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            client.close()


def _access_token_from_request(server: Server[Any, Any], static_token: AccessToken | None) -> AccessToken:
    if static_token is not None:
        return static_token
    request = server.request_context.request
    user = request.scope.get("user") if request is not None else None
    if not isinstance(user, AuthenticatedUser):
        raise PermissionError("Authenticated MCP token is unavailable")
    return user.access_token


def _safe_tool_error(exc: Exception) -> tuple[str, dict[str, Any]]:
    if isinstance(exc, EsheriaApiError):
        payload = {
            "error": "esheria_api_error",
            "message": exc.message,
            "error_code": exc.error_code or "api_error",
            "http_status": exc.status_code,
            "trace_id": exc.trace_id or "",
            "endpoint": exc.endpoint_path or "",
        }
        return str(exc), payload
    if isinstance(exc, (ValueError, KeyError, PermissionError, EsheriaError)):
        return str(exc), {"error": exc.__class__.__name__, "message": str(exc)}
    return "Esheria MCP tool execution failed", {"error": "internal_error", "message": "Tool execution failed"}


def _tool_type(definition: dict[str, Any]) -> types.Tool:
    return types.Tool.model_validate(definition)


def create_mcp_server(
    *,
    profile_key: str,
    allowed_names: tuple[str, ...],
    include_resources_and_prompts: bool,
    client_pool: EsheriaClientPool,
    static_token: AccessToken | None = None,
) -> Server[Any, Any]:
    server: Server[Any, Any] = Server(
        SERVER_INFO["name"],
        version=SERVER_INFO["version"],
        instructions=SERVER_INSTRUCTIONS,
        website_url="https://docs.esheria.ai/agent-tools/mcp",
    )
    allowed = frozenset(allowed_names)
    tool_timeout = max(5.0, float(os.getenv("ESHERIA_MCP_TOOL_TIMEOUT_SECONDS", "60")))

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [_tool_type(item) for item in tool_definitions(allowed_tools=allowed)]

    @server.call_tool(validate_input=True)
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> Any:
        metric_tool = name if name in allowed else "_unknown_or_unauthorized"
        started = time.monotonic()
        try:
            access_token = _access_token_from_request(server, static_token)
            client = client_pool.get(access_token.token)
            runner = EsheriaToolRunner(client, profile=profile_key, allowed_tools=allowed)
            with anyio.fail_after(tool_timeout):
                payload = await anyio.to_thread.run_sync(
                    lambda: runner.call(name, arguments or {}),
                    abandon_on_cancel=True,
                )
        except TimeoutError:
            error_payload = compact_tool_output(
                name,
                {
                    "error": "timeout",
                    "message": f"Esheria MCP tool exceeded the {tool_timeout:g}-second execution limit",
                    "trace_id": "",
                },
            )
            MCP_TOOL_CALLS.labels(tool=metric_tool, status="timeout").inc()
            _json_log("mcp_tool", tool=metric_tool, status="timeout", duration_ms=int((time.monotonic() - started) * 1000))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=tool_result_text(name, error_payload))],
                structuredContent=error_payload,
                isError=True,
            )
        except Exception as exc:
            _message, raw_error_payload = _safe_tool_error(exc)
            raw_error_payload.setdefault("trace_id", "")
            error_payload = compact_tool_output(name, raw_error_payload)
            MCP_TOOL_CALLS.labels(tool=metric_tool, status="error").inc()
            _json_log(
                "mcp_tool",
                tool=metric_tool,
                status="error",
                error=error_payload.get("error"),
                trace_id=error_payload.get("trace_id", ""),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=tool_result_text(name, error_payload))],
                structuredContent=error_payload,
                isError=True,
            )
        duration = time.monotonic() - started
        MCP_TOOL_CALLS.labels(tool=metric_tool, status="ok").inc()
        MCP_TOOL_LATENCY.labels(tool=metric_tool).observe(duration)
        _json_log(
            "mcp_tool",
            tool=metric_tool,
            status="ok",
            trace_id=payload.get("trace_id", ""),
            output_bytes=(payload.get("mcp") or {}).get("output_bytes", 0),
            truncated=(payload.get("mcp") or {}).get("truncated", False),
            duration_ms=int(duration * 1000),
        )
        return ([types.TextContent(type="text", text=tool_result_text(name, payload))], payload)

    if include_resources_and_prompts:

        @server.list_resources()
        async def list_resources() -> list[types.Resource]:
            return [types.Resource.model_validate(item) for item in resource_definitions()]

        @server.list_resource_templates()
        async def list_resource_templates() -> list[types.ResourceTemplate]:
            return [types.ResourceTemplate.model_validate(item) for item in resource_template_definitions()]

        @server.read_resource()
        async def handle_read_resource(uri: Any) -> list[ReadResourceContents]:
            access_token = _access_token_from_request(server, static_token)
            runner = EsheriaToolRunner(client_pool.get(access_token.token), profile=profile_key, allowed_tools=allowed)
            payload = await anyio.to_thread.run_sync(
                lambda: read_resource(str(uri), runner),
                abandon_on_cancel=True,
            )
            return [
                ReadResourceContents(
                    content=json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
                    mime_type="application/json",
                )
            ]

        @server.list_prompts()
        async def list_prompts() -> list[types.Prompt]:
            return [types.Prompt.model_validate(item) for item in prompt_definitions()]

        @server.get_prompt()
        async def handle_get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
            return types.GetPromptResult.model_validate(get_prompt(name, arguments or {}))

    return server


def _all_profile_scopes() -> list[frozenset[str]]:
    profiles: list[frozenset[str]] = []
    for mask in range(1 << len(WRITE_SCOPES)):
        profiles.append(frozenset(scope for index, scope in enumerate(WRITE_SCOPES) if mask & (1 << index)))
    return profiles


def _profile_servers(client_pool: EsheriaClientPool) -> dict[str, Server[Any, Any]]:
    servers = {
        DIRECTORY_PROFILE: create_mcp_server(
            profile_key=DIRECTORY_PROFILE,
            allowed_names=DIRECTORY_TOOL_NAMES,
            include_resources_and_prompts=False,
            client_pool=client_pool,
        )
    }
    for write_scopes in _all_profile_scopes():
        principal = McpPrincipal(
            principal_type="api_token",
            workspace_id="",
            # Synthetic profile objects do not identify a real credential.
            token_id=str(),
            token_type=DATA_PRINCIPAL_KIND,
            scopes=("regulatory:read", *[scope for scope in WRITE_SCOPES if scope in write_scopes]),
            pack_entitlements=(),
        )
        servers[principal.profile_key] = create_mcp_server(
            profile_key=principal.profile_key,
            allowed_names=principal.allowed_tools,
            include_resources_and_prompts=True,
            client_pool=client_pool,
        )
    return servers


class ProfileRouter:
    def __init__(
        self,
        managers: dict[str, StreamableHTTPSessionManager],
        *,
        max_sessions: int,
        max_sessions_per_profile: int,
    ) -> None:
        self.managers = managers
        self.max_sessions = max(1, max_sessions)
        self.max_sessions_per_profile = max(1, max_sessions_per_profile)
        self._session_lock = asyncio.Lock()
        self._pending_sessions = 0
        self._pending_by_profile: dict[str, int] = {}

    @staticmethod
    def _active_sessions(manager: StreamableHTTPSessionManager) -> int:
        return len(getattr(manager, "_server_instances", {}))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        user = scope.get("user")
        if not isinstance(user, AuthenticatedUser):
            await JSONResponse(
                {"error": "invalid_token", "error_description": "Authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": OAUTH_WWW_AUTHENTICATE},
            )(scope, receive, send)
            return
        profile_key = str((user.access_token.claims or {}).get("profile_key") or "")
        manager = self.managers.get(profile_key)
        if manager is None:
            await JSONResponse(
                {"error": "insufficient_scope", "error_description": "Token is not authorized for MCP"},
                status_code=403,
                headers={"WWW-Authenticate": OAUTH_WWW_AUTHENTICATE},
            )(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers") or []}
        creating_session = b"mcp-session-id" not in headers
        if not creating_session:
            await manager.handle_request(scope, receive, send)
            return

        reserved = False
        async with self._session_lock:
            total = sum(self._active_sessions(item) for item in self.managers.values())
            profile_total = self._active_sessions(manager)
            pending_profile = self._pending_by_profile.get(profile_key, 0)
            if (
                total + self._pending_sessions >= self.max_sessions
                or profile_total + pending_profile >= self.max_sessions_per_profile
            ):
                MCP_RATE_LIMITED.labels(reason="session_capacity").inc()
            else:
                self._pending_sessions += 1
                self._pending_by_profile[profile_key] = pending_profile + 1
                reserved = True
        if not reserved:
            await JSONResponse(
                {"error": "server_busy", "error_description": "MCP session capacity reached"},
                status_code=503,
                headers={"Retry-After": "5"},
            )(scope, receive, send)
            return
        try:
            await manager.handle_request(scope, receive, send)
        finally:
            async with self._session_lock:
                self._pending_sessions = max(0, self._pending_sessions - 1)
                remaining = max(0, self._pending_by_profile.get(profile_key, 1) - 1)
                if remaining:
                    self._pending_by_profile[profile_key] = remaining
                else:
                    self._pending_by_profile.pop(profile_key, None)


class ApiKeyToBearerMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = list(scope.get("headers") or [])
        authorization = next((value for key, value in headers if key.lower() == b"authorization"), b"")
        api_key = next((value for key, value in headers if key.lower() == b"x-api-key"), b"")
        if authorization and api_key:
            bearer = authorization[7:].strip() if authorization.lower().startswith(b"bearer ") else b""
            if not bearer or bearer != api_key.strip():
                await JSONResponse(
                    {"error": "invalid_request", "error_description": "Conflicting authentication headers"},
                    status_code=400,
                )(scope, receive, send)
                return
        elif api_key:
            headers.append((b"authorization", b"Bearer " + api_key.strip()))
        if api_key:
            headers = [(key, value) for key, value in headers if key.lower() != b"x-api-key"]
            scope = {**scope, "headers": headers}
        await self.app(scope, receive, send)


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers") or []}
        try:
            declared = int(headers.get(b"content-length", b"0") or b"0")
        except ValueError:
            declared = 0
        if declared > self.max_bytes:
            await JSONResponse({"error": "request_too_large"}, status_code=413)(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                await JSONResponse({"error": "request_too_large"}, status_code=413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)


@dataclass
class _LimitState:
    semaphore: asyncio.Semaphore
    request_times: deque[float]
    last_seen: float
    active: int = 0


class PreAuthProtectionMiddleware:
    """Bound unauthenticated/introspection load by client address."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        mcp_path: str,
        global_limit: int,
        per_ip_limit: int,
        requests_per_minute: int,
        max_ips: int,
    ) -> None:
        self.app = app
        self.mcp_path = mcp_path
        self.global_semaphore = asyncio.Semaphore(max(1, global_limit))
        self.per_ip_limit = max(1, per_ip_limit)
        self.requests_per_minute = max(1, requests_per_minute)
        self.max_ips = max(16, max_ips)
        self.states: OrderedDict[str, _LimitState] = OrderedDict()
        self.lock = asyncio.Lock()

    @staticmethod
    def _client_address(scope: Scope) -> str:
        client = scope.get("client")
        if isinstance(client, (tuple, list)) and client:
            return str(client[0])
        return "unknown"

    def _prune_locked(self, now: float) -> None:
        for key, state in list(self.states.items()):
            while state.request_times and state.request_times[0] <= now - 60:
                state.request_times.popleft()
            if not state.request_times and state.active == 0 and state.last_seen <= now - 60:
                self.states.pop(key, None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != self.mcp_path:
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        address = self._client_address(scope)
        rejection: tuple[int, str, str] | None = None
        state: _LimitState | None = None
        async with self.lock:
            self._prune_locked(now)
            state = self.states.get(address)
            if state is None:
                if len(self.states) >= self.max_ips:
                    rejection = (503, "preauth_capacity", "MCP authentication capacity reached")
                else:
                    state = _LimitState(
                        semaphore=asyncio.Semaphore(self.per_ip_limit),
                        request_times=deque(),
                        last_seen=now,
                    )
                    self.states[address] = state
            if state is not None:
                self.states.move_to_end(address)
                while state.request_times and state.request_times[0] <= now - 60:
                    state.request_times.popleft()
                if len(state.request_times) >= self.requests_per_minute:
                    rejection = (429, "preauth_rate", "MCP authentication request rate exceeded")
                else:
                    state.request_times.append(now)
                    state.last_seen = now

        if rejection is not None:
            status_code, reason, description = rejection
            MCP_RATE_LIMITED.labels(reason=reason).inc()
            await JSONResponse(
                {"error": "rate_limited" if status_code == 429 else "server_busy", "error_description": description},
                status_code=status_code,
                headers={"Retry-After": "60" if status_code == 429 else "5"},
            )(scope, receive, send)
            return

        if state is None:  # pragma: no cover - guarded by the reservation branch above
            await JSONResponse(
                {"error": "server_busy", "error_description": "MCP authentication capacity reached"},
                status_code=503,
                headers={"Retry-After": "5"},
            )(scope, receive, send)
            return
        global_acquired = False
        ip_acquired = False
        try:
            await asyncio.wait_for(self.global_semaphore.acquire(), timeout=0.1)
            global_acquired = True
            await asyncio.wait_for(state.semaphore.acquire(), timeout=0.1)
            ip_acquired = True
        except TimeoutError:
            MCP_RATE_LIMITED.labels(reason="preauth_concurrency").inc()
            if global_acquired:
                self.global_semaphore.release()
            await JSONResponse(
                {"error": "server_busy", "error_description": "MCP authentication concurrency limit reached"},
                status_code=503,
                headers={"Retry-After": "1"},
            )(scope, receive, send)
            return

        async with self.lock:
            state.active += 1
            state.last_seen = time.monotonic()
        try:
            await self.app(scope, receive, send)
        finally:
            if ip_acquired:
                state.semaphore.release()
                async with self.lock:
                    state.active = max(0, state.active - 1)
                    state.last_seen = time.monotonic()
            if global_acquired:
                self.global_semaphore.release()


class RateConcurrencyMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        mcp_path: str,
        global_limit: int,
        per_principal_limit: int,
        requests_per_minute: int,
        max_principals: int = 4096,
    ) -> None:
        self.app = app
        self.mcp_path = mcp_path
        self.global_semaphore = asyncio.Semaphore(max(1, global_limit))
        self.per_principal_limit = max(1, per_principal_limit)
        self.requests_per_minute = max(1, requests_per_minute)
        self.max_principals = max(128, max_principals)
        self.states: OrderedDict[str, _LimitState] = OrderedDict()
        self.rate_lock = asyncio.Lock()

    @staticmethod
    def _principal_key(scope: Scope) -> str:
        user = scope.get("user")
        if isinstance(user, AuthenticatedUser):
            token = user.access_token
            return f"{token.client_id}:{token.subject or ''}"
        return "anonymous"

    def _prune_locked(self, now: float) -> None:
        for key, state in list(self.states.items()):
            while state.request_times and state.request_times[0] <= now - 60:
                state.request_times.popleft()
            if not state.request_times and state.active == 0 and state.last_seen <= now - 60:
                self.states.pop(key, None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != self.mcp_path:
            await self.app(scope, receive, send)
            return
        principal = self._principal_key(scope)
        now = time.monotonic()
        rejection: tuple[int, str, str] | None = None
        state: _LimitState | None = None
        async with self.rate_lock:
            self._prune_locked(now)
            state = self.states.get(principal)
            if state is None:
                if len(self.states) >= self.max_principals:
                    rejection = (503, "principal_capacity", "MCP principal capacity reached")
                else:
                    state = _LimitState(
                        semaphore=asyncio.Semaphore(self.per_principal_limit),
                        request_times=deque(),
                        last_seen=now,
                    )
                    self.states[principal] = state
            if state is not None:
                self.states.move_to_end(principal)
                while state.request_times and state.request_times[0] <= now - 60:
                    state.request_times.popleft()
                if len(state.request_times) >= self.requests_per_minute:
                    rejection = (429, "rate", "MCP request rate exceeded")
                else:
                    state.request_times.append(now)
                    state.last_seen = now

        if rejection is not None:
            status_code, reason, description = rejection
            MCP_RATE_LIMITED.labels(reason=reason).inc()
            await JSONResponse(
                {"error": "rate_limited" if status_code == 429 else "server_busy", "error_description": description},
                status_code=status_code,
                headers={"Retry-After": "60" if status_code == 429 else "5"},
            )(scope, receive, send)
            return

        if state is None:  # pragma: no cover - guarded by the reservation branch above
            await JSONResponse(
                {"error": "server_busy", "error_description": "MCP principal capacity reached"},
                status_code=503,
                headers={"Retry-After": "5"},
            )(scope, receive, send)
            return
        global_acquired = False
        principal_acquired = False
        try:
            await asyncio.wait_for(self.global_semaphore.acquire(), timeout=0.1)
            global_acquired = True
            await asyncio.wait_for(state.semaphore.acquire(), timeout=0.1)
            principal_acquired = True
            async with self.rate_lock:
                state.active += 1
                state.last_seen = time.monotonic()
        except TimeoutError:
            MCP_RATE_LIMITED.labels(reason="concurrency").inc()
            if global_acquired:
                self.global_semaphore.release()
                global_acquired = False
            await JSONResponse(
                {"error": "server_busy", "error_description": "MCP concurrency limit reached"},
                status_code=503,
                headers={"Retry-After": "1"},
            )(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            if principal_acquired:
                state.semaphore.release()
                async with self.rate_lock:
                    state.active = max(0, state.active - 1)
                    state.last_seen = time.monotonic()
            if global_acquired:
                self.global_semaphore.release()


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                existing = {key.lower() for key, _value in headers}
                additions = {
                    b"cache-control": b"no-store",
                    b"x-content-type-options": b"nosniff",
                    b"referrer-policy": b"no-referrer",
                    b"strict-transport-security": b"max-age=31536000; includeSubDomains",
                }
                headers.extend((key, value) for key, value in additions.items() if key not in existing)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestObservabilityMiddleware:
    def __init__(self, app: ASGIApp, *, mcp_path: str) -> None:
        self.app = app
        self.mcp_path = mcp_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method") or "")
        raw_path = str(scope.get("path") or "")
        metric_method = method if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "_other"
        metric_path = raw_path if raw_path in {self.mcp_path, "/healthz", "/readyz", "/metrics"} else "_other"
        status = 500
        started = time.monotonic()

        async def observe_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message.get("status") or 500)
            await send(message)

        MCP_ACTIVE_REQUESTS.inc()
        try:
            await self.app(scope, receive, observe_send)
        finally:
            MCP_ACTIVE_REQUESTS.dec()
            duration = time.monotonic() - started
            MCP_HTTP_REQUESTS.labels(method=metric_method, path=metric_path, status=str(status)).inc()
            MCP_HTTP_LATENCY.labels(method=metric_method, path=metric_path).observe(duration)
            _json_log(
                "mcp_http",
                method=metric_method,
                path=metric_path,
                status=status,
                duration_ms=int(duration * 1000),
            )


@dataclass
class McpHttpRuntime:
    app: ASGIApp
    verifier: EsheriaTokenVerifier
    client_pool: EsheriaClientPool
    servers: dict[str, Server[Any, Any]]
    managers: dict[str, StreamableHTTPSessionManager]


def build_http_runtime(
    args: argparse.Namespace,
    *,
    token_verifier: EsheriaTokenVerifier | None = None,
    client_pool: EsheriaClientPool | None = None,
) -> McpHttpRuntime:
    path = _normalize_http_path(str(args.path or "/mcp"))
    config = config_from_args(args, api_key="")
    public_resource = os.getenv("OAUTH_PROTECTED_RESOURCE", "https://mcp.esheria.ai/mcp").strip()
    verifier = token_verifier or EsheriaTokenVerifier(config, protected_resource=public_resource)
    pool = client_pool or EsheriaClientPool(
        config,
        max_clients=int(os.getenv("ESHERIA_MCP_CLIENT_POOL_SIZE", "128")),
    )
    servers = _profile_servers(pool)
    allowed_hosts = _csv_env(
        "ESHERIA_MCP_ALLOWED_HOSTS",
        "mcp.esheria.ai,127.0.0.1:*,localhost:*",
    )
    allowed_origins = _csv_env(
        "ESHERIA_MCP_ALLOWED_ORIGINS",
        "https://mcp.esheria.ai,https://claude.ai,https://claude.com,http://127.0.0.1:*,http://localhost:*",
    )
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )
    managers = {
        key: StreamableHTTPSessionManager(
            app=server,
            json_response=True,
            stateless=False,
            security_settings=security,
            session_idle_timeout=float(os.getenv("ESHERIA_MCP_SESSION_IDLE_SECONDS", "900")),
        )
        for key, server in servers.items()
    }
    router = ProfileRouter(
        managers,
        max_sessions=int(os.getenv("ESHERIA_MCP_MAX_SESSIONS", "512")),
        max_sessions_per_profile=int(os.getenv("ESHERIA_MCP_MAX_SESSIONS_PER_PROFILE", "256")),
    )

    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok", "server": SERVER_INFO})

    async def ready(_request: Request) -> Response:
        api_ready, api_payload = await verifier.api_readiness()
        return JSONResponse(
            {
                "status": "ready" if api_ready else "not_ready",
                "api_ready": api_ready,
                "api_trace_id": str(api_payload.get("trace_id") or ""),
                "profiles": len(managers),
            },
            status_code=200 if api_ready else 503,
        )

    async def metrics(_request: Request) -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        async with AsyncExitStack() as stack:
            for manager in managers.values():
                await stack.enter_async_context(manager.run())
            try:
                yield
            finally:
                pool.close()
                await verifier.close()

    core = Starlette(
        routes=[
            Route(path, endpoint=router),
            Route("/healthz", endpoint=health, methods=["GET"]),
            Route("/readyz", endpoint=ready, methods=["GET"]),
            Route("/metrics", endpoint=metrics, methods=["GET"]),
        ],
        lifespan=lifespan,
    )
    app: ASGIApp = AuthContextMiddleware(core)
    app = RateConcurrencyMiddleware(
        app,
        mcp_path=path,
        global_limit=int(os.getenv("ESHERIA_MCP_MAX_CONCURRENCY", "32")),
        per_principal_limit=int(os.getenv("ESHERIA_MCP_MAX_CONCURRENCY_PER_TOKEN", "4")),
        requests_per_minute=int(os.getenv("ESHERIA_MCP_REQUESTS_PER_MINUTE", "120")),
        max_principals=int(os.getenv("ESHERIA_MCP_MAX_TRACKED_PRINCIPALS", "4096")),
    )
    app = AuthenticationMiddleware(app, backend=BearerAuthBackend(verifier))
    app = ApiKeyToBearerMiddleware(app)
    app = BodyLimitMiddleware(
        app,
        max_bytes=int(os.getenv("ESHERIA_MCP_MAX_REQUEST_BYTES", str(512 * 1024))),
    )
    app = PreAuthProtectionMiddleware(
        app,
        mcp_path=path,
        global_limit=int(os.getenv("ESHERIA_MCP_PREAUTH_MAX_CONCURRENCY", "64")),
        per_ip_limit=int(os.getenv("ESHERIA_MCP_PREAUTH_MAX_CONCURRENCY_PER_IP", "16")),
        requests_per_minute=int(os.getenv("ESHERIA_MCP_PREAUTH_REQUESTS_PER_MINUTE", "300")),
        max_ips=int(os.getenv("ESHERIA_MCP_MAX_TRACKED_IPS", "4096")),
    )
    app = SecurityHeadersMiddleware(app)
    app = RequestObservabilityMiddleware(app, mcp_path=path)
    return McpHttpRuntime(app=app, verifier=verifier, client_pool=pool, servers=servers, managers=managers)


def build_http_app(
    args: argparse.Namespace,
    *,
    token_verifier: EsheriaTokenVerifier | None = None,
    client_pool: EsheriaClientPool | None = None,
) -> ASGIApp:
    return build_http_runtime(args, token_verifier=token_verifier, client_pool=client_pool).app


async def _serve_stdio_async(server: Server[Any, Any]) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
            raise_exceptions=False,
        )


def serve_stdio(args: argparse.Namespace) -> int:
    config = config_from_args(args)
    raw_token = config.api_key
    if not raw_token:
        print("Esheria MCP stdio requires ESHERIA_API_TOKEN or --api-key", file=sys.stderr)
        return 3
    principal = introspect_token(config.with_overrides(api_key=""), raw_token)
    if principal is None:
        print("Esheria MCP token validation failed; use a regulatory data token", file=sys.stderr)
        return 3
    pool = EsheriaClientPool(config.with_overrides(api_key=""), max_clients=8)
    static_access_token = principal.access_token(
        raw_token,
        resource=os.getenv("OAUTH_PROTECTED_RESOURCE", "https://mcp.esheria.ai/mcp"),
    )
    server = create_mcp_server(
        profile_key=principal.profile_key,
        allowed_names=principal.allowed_tools,
        include_resources_and_prompts=principal.principal_type != "oauth_access_token",
        client_pool=pool,
        static_token=static_access_token,
    )
    try:
        anyio.run(_serve_stdio_async, server)
    finally:
        pool.close()
    return 0


def serve_http(args: argparse.Namespace) -> int:
    runtime = build_http_runtime(args)
    uvicorn.run(
        runtime.app,
        host=str(args.host),
        port=int(args.port),
        log_level=os.getenv("ESHERIA_MCP_LOG_LEVEL", "info").lower(),
        access_log=False,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1,::1",
        backlog=int(os.getenv("ESHERIA_MCP_BACKLOG", "256")),
        limit_concurrency=int(os.getenv("ESHERIA_MCP_UVICORN_CONCURRENCY", "128")),
        timeout_keep_alive=int(os.getenv("ESHERIA_MCP_KEEPALIVE_SECONDS", "10")),
        server_header=False,
        date_header=True,
    )
    return 0


def extract_http_api_key(headers: Any) -> str:
    authorization = str(headers.get("Authorization") or headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return str(headers.get("X-API-Key") or headers.get("x-api-key") or "").strip()


def main(argv: list[str] | None = None) -> int:
    _harden_dependency_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "serve":
        parser.error("Only `serve` is supported")
    if args.http and args.stdio:
        parser.error("Choose only one transport: --stdio or --http")
    if args.http:
        if args.api_key:
            parser.error("--api-key is only valid for stdio; hosted HTTP requires a credential on every request")
        return serve_http(args)
    return serve_stdio(args)
