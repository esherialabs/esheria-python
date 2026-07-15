from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from api.clients.esheria_regulatory.client import EsheriaRegulatoryClient
from api.clients.esheria_regulatory.config import EsheriaClientConfig


def envelope(data: Any, *, trace_id: str = "test-trace") -> dict[str, Any]:
    return {"status": "ok", "data": data, "errors": [], "trace_id": trace_id}


def error_envelope(code: str, message: str, *, trace_id: str = "test-trace") -> dict[str, Any]:
    return {
        "status": "error",
        "data": None,
        "errors": [{"code": code, "message": message}],
        "trace_id": trace_id,
    }


def mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> EsheriaRegulatoryClient:
    http_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver")
    return EsheriaRegulatoryClient(
        EsheriaClientConfig(
            base_url="http://testserver", api_key="test-key", retry_count=0  # pragma: allowlist secret
        ),
        http_client=http_client,
    )
