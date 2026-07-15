from __future__ import annotations

from copy import deepcopy
import json
import os
from typing import Any


DEFAULT_MAX_OUTPUT_BYTES = 24 * 1024


def output_byte_limit() -> int:
    try:
        configured = int(os.getenv("ESHERIA_MCP_MAX_OUTPUT_BYTES", str(DEFAULT_MAX_OUTPUT_BYTES)))
    except ValueError:
        configured = DEFAULT_MAX_OUTPUT_BYTES
    return max(4096, min(64 * 1024, configured))


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8"))


def _pick(source: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: source[name] for name in names if name in source and source[name] not in (None, "", [], {})}


def _pack_summary(pack: Any) -> Any:
    if not isinstance(pack, dict):
        return pack
    return _pick(
        pack,
        (
            "domain_pack_id",
            "domain_pack_version",
            "jurisdiction",
            "legal_domain",
            "status",
            "readiness_label",
            "is_current",
            "publication_mode",
            "published_legal_status_count",
            "published_obligation_count",
            "published_row_counts_by_fact_type",
            "limitations",
        ),
    )


def _obligation_summary(obligation: Any) -> Any:
    if not isinstance(obligation, dict):
        return obligation
    return _pick(
        obligation,
        (
            "obligation_id",
            "published_fact_id",
            "domain_pack_id",
            "domain_pack_version",
            "instrument_id",
            "instrument_version",
            "title",
            "summary",
            "action_required",
            "duty_holder",
            "duty_holders",
            "duty_holder_type",
            "workflow_target",
            "trigger",
            "deadline",
            "frequency",
            "applicability_status",
            "result_status",
            "reason",
            "confidence",
            "citation_ids",
            "source_rule_ids",
            "limitations",
        ),
    )


def _specialize(tool_name: str, payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    result = deepcopy(payload)
    omitted: list[str] = []
    result.pop("principal", None)

    if tool_name == "esheria_list_packs" and isinstance(result.get("packs"), list):
        result["packs"] = [_pack_summary(pack) for pack in result["packs"]]
        omitted.append("non-essential pack manifest fields")
    elif tool_name in {
        "esheria_list_obligations",
        "esheria_check_applicability",
        "esheria_check_graph_applicability",
        "esheria_get_entity_profile",
        "esheria_preview_customer_lifecycle",
        "esheria_run_customer_applicability",
    }:
        for key in ("obligations", "applicable_obligations", "obligation_previews"):
            if isinstance(result.get(key), list):
                result[key] = [_obligation_summary(item) for item in result[key]]
                omitted.append(f"non-essential {key} fields")
        if isinstance(result.get("pack_results"), list):
            compact_pack_results = []
            for pack_result in result["pack_results"]:
                if not isinstance(pack_result, dict):
                    compact_pack_results.append(pack_result)
                    continue
                compact = _pick(
                    pack_result,
                    (
                        "domain_pack_id",
                        "domain_pack_version",
                        "result_status",
                        "applicable_obligations",
                        "citation_ids",
                        "limitations",
                    ),
                )
                if isinstance(compact.get("applicable_obligations"), list):
                    compact["applicable_obligations"] = [
                        _obligation_summary(item) for item in compact["applicable_obligations"]
                    ]
                compact_pack_results.append(compact)
            result["pack_results"] = compact_pack_results
            omitted.append("non-essential pack result fields")
    elif tool_name == "esheria_export_pack":
        compact = _pick(
            result,
            (
                "domain_pack",
                "manifest_summary",
                "readiness_label",
                "limitations",
                "trace_id",
            ),
        )
        compact["export_counts"] = {
            key: len(value)
            for key, value in result.items()
            if isinstance(value, list)
        }
        if isinstance(result.get("obligations"), list):
            compact["obligation_sample"] = [_obligation_summary(item) for item in result["obligations"][:10]]
        compact["complete_export"] = {
            "included": False,
            "reason": "MCP responses are bounded; use the Esheria API or CLI pack export for the complete artifact.",
        }
        result = compact
        omitted.append("complete pack export arrays")
    return result, omitted


def _bounded_copy(value: Any, *, max_list: int, max_string: int, depth: int = 0) -> tuple[Any, bool]:
    if depth > 8:
        return "[nested value omitted]", True
    if isinstance(value, str):
        if len(value) <= max_string:
            return value, False
        return value[:max_string] + "…", True
    if isinstance(value, list):
        bounded = []
        changed = len(value) > max_list
        for item in value[:max_list]:
            copied, item_changed = _bounded_copy(
                item,
                max_list=max_list,
                max_string=max_string,
                depth=depth + 1,
            )
            bounded.append(copied)
            changed = changed or item_changed
        return bounded, changed
    if isinstance(value, dict):
        bounded_dict: dict[str, Any] = {}
        max_keys = max(8, max_list * 4)
        changed = len(value) > max_keys
        items = list(value.items())
        if depth == 0 and "trace_id" in value:
            items = [("trace_id", value["trace_id"]), *[(key, item) for key, item in items if key != "trace_id"]]
        for key, item in items[:max_keys]:
            copied, item_changed = _bounded_copy(
                item,
                max_list=max_list,
                max_string=max_string,
                depth=depth + 1,
            )
            bounded_dict[str(key)] = copied
            changed = changed or item_changed
        return bounded_dict, changed
    return value, False


def _set_output_size(payload: dict[str, Any]) -> int:
    """Set output_bytes to the encoded size, accounting for its own digits."""

    for _attempt in range(4):
        size = _json_bytes(payload)
        if (payload.get("mcp") or {}).get("output_bytes") == size:
            return size
        payload["mcp"]["output_bytes"] = size
    return _json_bytes(payload)


def compact_tool_output(
    tool_name: str,
    payload: dict[str, Any],
    *,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    budget = max(4096, min(64 * 1024, int(max_bytes or output_byte_limit())))
    original_size = _json_bytes(payload)
    specialized, omitted = _specialize(tool_name, payload)
    specialized_changed = _json_bytes(specialized) < original_size

    selected: dict[str, Any] | None = None
    selected_changed = False
    for max_list, max_string in ((100, 4000), (50, 2000), (25, 1000), (10, 750), (5, 500), (2, 300), (1, 200)):
        candidate, changed = _bounded_copy(
            specialized,
            max_list=max_list,
            max_string=max_string,
        )
        if not isinstance(candidate, dict):  # pragma: no cover - payload is always a dict
            candidate = {"value": candidate}
        candidate.pop("mcp", None)
        candidate["mcp"] = {
            "bounded": True,
            "truncated": bool(specialized_changed or changed),
            "max_output_bytes": budget,
            "original_output_bytes": original_size,
            "omitted": sorted(set(omitted)),
            "complete_result": "Use the same Esheria API/CLI workflow when a complete artifact is required.",
        }
        if _set_output_size(candidate) <= budget:
            selected = candidate
            selected_changed = changed
            break

    if selected is None:
        selected = {
            "trace_id": str(payload.get("trace_id") or ""),
            "result_keys": sorted(str(key) for key in specialized if key not in {"trace_id", "mcp"})[:50],
            "mcp": {
                "bounded": True,
                "truncated": True,
                "max_output_bytes": budget,
                "original_output_bytes": original_size,
                "omitted": sorted(set(omitted + ["result exceeded the MCP byte budget"])),
                "complete_result": "Use the same Esheria API/CLI workflow when a complete artifact is required.",
            },
        }
    selected["mcp"]["truncated"] = bool(selected["mcp"]["truncated"] or selected_changed)
    if _set_output_size(selected) > budget:
        selected = {
            "trace_id": str(payload.get("trace_id") or ""),
            "mcp": {
                "bounded": True,
                "truncated": True,
                "max_output_bytes": budget,
                "original_output_bytes": original_size,
                "omitted": ["result exceeded the MCP byte budget"],
                "complete_result": "Use the same Esheria API/CLI workflow when a complete artifact is required.",
            },
        }
        _set_output_size(selected)
    return selected


def tool_result_text(tool_name: str, payload: dict[str, Any]) -> str:
    del tool_name
    # MCP recommends mirroring structuredContent as serialized JSON so clients
    # that only consume text content still receive the complete bounded result.
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True, default=str)
