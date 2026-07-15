from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
from typing import Any

import anyio
from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.auth.provider import AccessToken
from mcp.shared.message import SessionMessage

from api.mcp.esheria_mcp.server import create_mcp_server


class MockApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: Any) -> None:
        return None

    def do_GET(self) -> None:
        if self.path == "/api/v1/oauth/introspect":
            payload = {
                "status": "ok",
                "data": {
                    "principal_type": "api_token",
                    "workspace_id": "workspace-stdio",
                    "api_token_id": "token-stdio",
                    "token_type": "data",
                    "scopes": ["regulatory:read"],
                    "pack_entitlements": ["*"],
                },
                "errors": [],
                "trace_id": "trace-introspect",
            }
            self._json(200, payload)
            return
        if self.path.startswith("/api/v1/domain-packs"):
            payload = {
                "status": "ok",
                "data": {
                    "packs": [
                        {
                            "domain_pack_id": "UK-DATA-PROTECTION-PRIVACY",
                            "jurisdiction": "UK",
                            "legal_domain": "data_protection_privacy",
                            "readiness_label": "verified_published",
                        }
                    ],
                    "total": 1,
                    "limit": 10,
                    "offset": 0,
                },
                "errors": [],
                "trace_id": "trace-packs",
            }
            self._json(200, payload)
            return
        self._json(404, {"status": "error", "data": {}, "errors": [], "trace_id": "missing"})

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_official_sdk_stdio_initialize_ping_list_and_call() -> None:
    api_server = ThreadingHTTPServer(("127.0.0.1", 0), MockApiHandler)
    api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
    api_thread.start()
    host, port = api_server.server_address

    async def run() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "api.mcp.esheria_mcp",
                "serve",
                "--stdio",
                "--base-url",
                f"http://{host}:{port}",
                "--api-key",
                "test-token",
            ],
            cwd=Path.cwd(),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                tools = await session.list_tools()
                ping = await session.send_ping()
                result = await session.call_tool("esheria_list_packs", {"limit": 10})

        assert initialized.protocolVersion == "2025-11-25"
        assert len(tools.tools) == 29
        assert ping.model_dump(exclude_none=True) == {}
        assert result.isError is False
        assert result.structuredContent is not None
        assert result.structuredContent["packs"][0]["jurisdiction"] == "UK"

    try:
        anyio.run(run)
    finally:
        api_server.shutdown()
        api_server.server_close()
        api_thread.join(timeout=5)


def test_malformed_stdio_message_does_not_crash_the_server() -> None:
    class UnusedPool:
        def get(self, _token: str) -> Any:
            raise AssertionError("No tool call expected")

    server = create_mcp_server(
        profile_key="api_read",
        allowed_names=("esheria_health",),
        include_resources_and_prompts=False,
        client_pool=UnusedPool(),  # type: ignore[arg-type]
        static_token=AccessToken(token="test", client_id="test", scopes=["regulatory:read"]),
    )

    async def run() -> None:
        input_writer, input_reader = anyio.create_memory_object_stream(10)
        output_writer, output_reader = anyio.create_memory_object_stream(10)
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                server.run,
                input_reader,
                output_writer,
                server.create_initialization_options(),
            )
            await input_writer.send(ValueError("malformed stdio JSON"))
            initialize = types.JSONRPCMessage.model_validate(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "stdio-recovery", "version": "1"},
                    },
                }
            )
            await input_writer.send(SessionMessage(initialize))
            response = await output_reader.receive()
            dumped = response.message.model_dump(by_alias=True, exclude_none=True)
            assert dumped["result"]["protocolVersion"] == "2025-11-25"
            await input_writer.aclose()
            task_group.cancel_scope.cancel()

    anyio.run(run)
