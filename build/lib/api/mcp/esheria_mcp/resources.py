from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit

from api.mcp.esheria_mcp.tools import EsheriaToolRunner


def resource_definitions() -> list[dict[str, Any]]:
    """Return concrete resources.

    Pack resources require a caller-selected pack ID, so they are advertised as
    templates rather than pretending template URIs are concrete resources.
    """

    return []


def resource_template_definitions() -> list[dict[str, Any]]:
    return [
        {
            "uriTemplate": "esheria://packs/{pack_id}/manifest",
            "name": "Pack manifest summary",
            "description": "Compact published pack manifest and readiness summary.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "esheria://packs/{pack_id}/readiness",
            "name": "Pack readiness",
            "description": "Pack readiness label, limitations, and published row counts.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "esheria://packs/{pack_id}/openapi-summary",
            "name": "OpenAPI summary",
            "description": "Static summary of supported Regulatory Pack API workflows.",
            "mimeType": "application/json",
        },
    ]


def read_resource(uri: str, runner: EsheriaToolRunner) -> dict[str, Any]:
    parsed = urlsplit(uri)
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if parsed.scheme != "esheria" or parsed.netloc != "packs" or len(parts) != 2:
        raise KeyError(f"Unknown Esheria resource `{uri}`")
    pack_id, resource = parts
    pack = runner.call("esheria_get_pack", {"pack_id": pack_id})
    if resource == "manifest":
        return {"uri": uri, "pack_id": pack_id, "manifest_summary": pack.get("manifest_summary"), "trace_id": pack.get("trace_id")}
    if resource == "readiness":
        return {
            "uri": uri,
            "pack_id": pack_id,
            "readiness_label": pack.get("readiness_label"),
            "limitations": pack.get("limitations"),
            "published_legal_status_count": pack.get("published_legal_status_count"),
            "trace_id": pack.get("trace_id"),
        }
    if resource == "openapi-summary":
        return {
            "uri": uri,
            "pack_id": pack_id,
            "workflows": [
                "health",
                "ready",
                "domain pack discovery",
                "pack versions",
                "pack diffs",
                "change events",
                "obligations",
                "applicability",
                "claim verification",
                "filing calendar",
                "evidence register",
                "penalty facts",
                "legal review audit",
                "relationships",
                "regulatory graph",
                "pack export",
            ],
            "trace_id": pack.get("trace_id"),
        }
    raise KeyError(f"Unknown Esheria resource `{uri}`")
