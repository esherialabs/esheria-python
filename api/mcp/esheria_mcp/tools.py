from __future__ import annotations

from typing import Any

from api.clients.esheria_regulatory import EsheriaRegulatoryClient
from api.clients.esheria_regulatory.models import EsheriaResult
from api.mcp.esheria_mcp.output import compact_tool_output
from api.mcp.esheria_mcp.schemas import TOOL_SCHEMAS


TOOL_DESCRIPTIONS = {
    "esheria_health": "Verify Esheria Regulatory Pack API liveness.",
    "esheria_ready": "Verify Esheria Regulatory Pack API readiness and dependencies.",
    "esheria_list_packs": "Discover current regulatory packs available through the API.",
    "esheria_get_pack": "Inspect one pack's compact manifest, readiness, counts, and limitations.",
    "esheria_list_pack_versions": "List loaded historical versions for a regulatory pack.",
    "esheria_get_pack_diff": "Diff canonical facts between two regulatory pack versions.",
    "esheria_list_change_events": "List stored or generated legal change events for a regulatory pack.",
    "esheria_list_obligations": "Retrieve published obligations by pack and filters.",
    "esheria_check_applicability": "Check which published obligations potentially apply to an entity profile.",
    "esheria_verify_claim": "Verify a generated claim against published pack facts and citations.",
    "esheria_get_filing_calendar": "Retrieve published deadline and filing calendar items.",
    "esheria_get_evidence_register": "Retrieve evidence and control requirements by evidence type.",
    "esheria_get_penalty_facts": "Retrieve source-traced penalty and consequence facts.",
    "esheria_get_legal_review_audit": "Retrieve canonical legal review and publication audit metadata.",
    "esheria_list_relationships": "Retrieve published relationship facts for a pack.",
    "esheria_query_regulatory_graph": "Query cross-pack published relationship facts.",
    "esheria_check_graph_applicability": "Return pack applicability results with published relationship context.",
    "esheria_get_entity_profile": "Summarize regulatory context for an entity profile.",
    "esheria_export_pack": "Export published pack data.",
    "esheria_get_citation_context": "Return quote and source metadata for a citation ID.",
    "esheria_create_source_watch": "Create or update a regulatory source watch.",
    "esheria_list_source_watches": "List regulatory source watches.",
    "esheria_get_source_currentness": "List source currentness from monitoring snapshots.",
    "esheria_check_source_watches": "Run source snapshot and change detection.",
    "esheria_list_source_change_events": "List recorded source-change events.",
    "esheria_list_recompile_candidates": "List source or fact changes queued for pack recompile.",
    "esheria_rebuild_graph_projection": "Rebuild graph projection tables from published serving facts.",
    "esheria_get_graph_coverage": "Return graph node coverage reports for published facts.",
    "esheria_create_customer_profile": "Create an opt-in workspace-scoped customer regulatory profile.",
    "esheria_list_customer_profiles": (
        "List workspace-scoped customer profiles, or inspect one profile and optionally its applicability-run history."
    ),
    "esheria_preview_customer_lifecycle": "Preview customer applicability and change impacts without storing customer state.",
    "esheria_run_customer_applicability": "Run and persist customer-specific applicability against locked pack versions.",
    "esheria_list_customer_obligation_instances": "List customer obligation instances referencing published facts.",
    "esheria_update_customer_obligation_instance": "Update tenant-owned lifecycle state for a customer obligation instance.",
    "esheria_recompute_customer_change_impacts": "Recompute customer impacts from pack change events.",
    "esheria_list_customer_change_impacts": "List workspace customer change impacts.",
    "esheria_update_customer_change_impact": "Update tenant-owned lifecycle state for a customer change impact.",
}

DIRECTORY_TOOL_NAMES = (
    "esheria_health",
    "esheria_ready",
    "esheria_list_packs",
    "esheria_get_pack",
    "esheria_list_pack_versions",
    "esheria_get_pack_diff",
    "esheria_list_change_events",
    "esheria_list_obligations",
    "esheria_check_applicability",
    "esheria_verify_claim",
    "esheria_get_filing_calendar",
    "esheria_get_evidence_register",
    "esheria_get_penalty_facts",
    "esheria_get_legal_review_audit",
    "esheria_list_relationships",
    "esheria_query_regulatory_graph",
    "esheria_check_graph_applicability",
    "esheria_get_entity_profile",
    "esheria_export_pack",
    "esheria_get_citation_context",
)

MUTATION_TOOL_SCOPES = {
    "esheria_create_source_watch": "monitoring:write",
    "esheria_check_source_watches": "monitoring:write",
    "esheria_rebuild_graph_projection": "graph:write",
    "esheria_create_customer_profile": "customer:write",
    "esheria_run_customer_applicability": "customer:write",
    "esheria_update_customer_obligation_instance": "customer:write",
    "esheria_recompute_customer_change_impacts": "customer:write",
    "esheria_update_customer_change_impact": "customer:write",
}

READ_TOOL_NAMES = tuple(name for name in TOOL_SCHEMAS if name not in MUTATION_TOOL_SCOPES)
ALL_TOOL_NAMES = tuple(TOOL_SCHEMAS)

TOOL_ANNOTATIONS: dict[str, dict[str, bool]] = {
    name: {
        "readOnlyHint": name not in MUTATION_TOOL_SCOPES,
        "destructiveHint": name
        in {
            "esheria_rebuild_graph_projection",
            "esheria_update_customer_obligation_instance",
            "esheria_update_customer_change_impact",
        },
        "idempotentHint": name
        not in {
            "esheria_check_source_watches",
            "esheria_rebuild_graph_projection",
            "esheria_create_customer_profile",
            "esheria_run_customer_applicability",
            "esheria_recompute_customer_change_impacts",
        },
        "openWorldHint": True,
    }
    for name in TOOL_SCHEMAS
}

TOOL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "trace_id": {"type": "string"},
        "mcp": {
            "type": "object",
            "properties": {
                "bounded": {"type": "boolean"},
                "truncated": {"type": "boolean"},
                "output_bytes": {"type": "integer"},
                "max_output_bytes": {"type": "integer"},
            },
            "required": ["bounded", "truncated", "output_bytes", "max_output_bytes"],
            "additionalProperties": True,
        },
    },
    "required": ["trace_id", "mcp"],
    "additionalProperties": True,
}


def _tool_title(name: str) -> str:
    words = name.removeprefix("esheria_").replace("_", " ").split()
    return " ".join(word.upper() if word in {"api"} else word.capitalize() for word in words)


def allowed_tool_names(*, principal_type: str, scopes: set[str] | frozenset[str]) -> tuple[str, ...]:
    if principal_type == "oauth_access_token":
        return DIRECTORY_TOOL_NAMES
    allowed = set(READ_TOOL_NAMES)
    for name, required_scope in MUTATION_TOOL_SCOPES.items():
        if required_scope in scopes:
            allowed.add(name)
    return tuple(name for name in ALL_TOOL_NAMES if name in allowed)


def tool_definitions(
    *,
    profile: str = "api_read",
    allowed_tools: set[str] | frozenset[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    if allowed_tools is not None:
        allowed = set(allowed_tools)
        names = tuple(name for name in ALL_TOOL_NAMES if name in allowed)
    elif profile == "directory":
        names = DIRECTORY_TOOL_NAMES
    elif profile == "operator":
        names = ALL_TOOL_NAMES
    else:
        names = READ_TOOL_NAMES
    tools: list[dict[str, Any]] = []
    for name in names:
        tool = {
            "name": name,
            "title": _tool_title(name),
            "description": TOOL_DESCRIPTIONS[name],
            "inputSchema": TOOL_SCHEMAS[name],
            "outputSchema": TOOL_OUTPUT_SCHEMA,
            "annotations": TOOL_ANNOTATIONS[name],
        }
        tools.append(tool)
    return tools


class EsheriaToolRunner:
    def __init__(
        self,
        client: EsheriaRegulatoryClient,
        *,
        profile: str = "api_read",
        allowed_tools: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.client = client
        self.profile = profile
        self.allowed_tools = frozenset(READ_TOOL_NAMES if allowed_tools is None else allowed_tools)

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in self.allowed_tools:
            raise PermissionError(f"Esheria MCP tool `{name}` is not authorized for this token")
        args = arguments or {}
        if name in MUTATION_TOOL_SCOPES:
            if args.get("confirm") is not True:
                raise ValueError(f"Esheria MCP tool `{name}` requires confirm=true")
            args = self._without(args, "confirm")
        return compact_tool_output(name, self._call_unbounded(name, args))

    def _call_unbounded(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "esheria_health":
            return self._payload(self.client.health())
        if name == "esheria_ready":
            return self._payload(self.client.ready())
        if name == "esheria_list_packs":
            return self._payload(self.client.list_packs(self._clean(args)))
        if name == "esheria_get_pack":
            return self._payload(self.client.get_pack(str(args["pack_id"])))
        if name == "esheria_list_pack_versions":
            return self._payload(self.client.list_pack_versions(str(args["pack_id"]), self._without(args, "pack_id")))
        if name == "esheria_get_pack_diff":
            return self._payload(self.client.diff_pack_versions(str(args["pack_id"]), self._without(args, "pack_id")))
        if name == "esheria_list_change_events":
            return self._payload(self.client.list_change_events(str(args["pack_id"]), self._without(args, "pack_id")))
        if name == "esheria_list_obligations":
            return self._payload(self.client.list_obligations(str(args["pack_id"]), self._without(args, "pack_id")))
        if name == "esheria_check_applicability":
            return self._payload(self.client.check_applicability(str(args["pack_id"]), self._without(args, "pack_id")))
        if name == "esheria_verify_claim":
            payload = self._clean(args)
            if "jurisdiction" not in payload or "domain" not in payload:
                pack = self.client.get_pack(str(payload["pack_id"])).data
                payload.setdefault("jurisdiction", pack.get("jurisdiction"))
                payload.setdefault("domain", pack.get("legal_domain"))
            if not payload.get("jurisdiction"):
                raise ValueError(
                    f"Pack `{payload['pack_id']}` does not declare a jurisdiction; provide `jurisdiction` explicitly"
                )
            if not payload.get("domain"):
                raise ValueError(
                    f"Pack `{payload['pack_id']}` does not declare a legal domain; provide `domain` explicitly"
                )
            return self._payload(self.client.verify_claim(payload))
        if name == "esheria_get_filing_calendar":
            return self._payload(self.client.get_filing_calendar(str(args["pack_id"]), self._without(args, "pack_id")))
        if name == "esheria_get_evidence_register":
            return self._payload(self.client.get_evidence_register(str(args["pack_id"]), self._without(args, "pack_id")))
        if name == "esheria_get_penalty_facts":
            return self._payload(self.client.get_penalty_facts(str(args["pack_id"]), self._without(args, "pack_id")))
        if name == "esheria_get_legal_review_audit":
            return self._payload(self.client.get_legal_review_audit(str(args["pack_id"]), self._without(args, "pack_id")))
        if name == "esheria_list_relationships":
            payload = self._without(args, "pack_id")
            if payload.get("relationship_type"):
                payload["relationship_types"] = [payload.pop("relationship_type")]
            return self._payload(self.client.list_relationships(str(args["pack_id"]), payload))
        if name == "esheria_query_regulatory_graph":
            return self._payload(self.client.query_graph(self._clean(args)))
        if name == "esheria_check_graph_applicability":
            return self._payload(self.client.check_graph_applicability(self._clean(args)))
        if name == "esheria_get_entity_profile":
            return self._payload(self.client.get_entity_profile(self._clean(args)))
        if name == "esheria_export_pack":
            return self._payload(self.client.export_pack(str(args["pack_id"]), self._without(args, "pack_id")))
        if name == "esheria_get_citation_context":
            return self._payload(self.client.get_citation_context(str(args["pack_id"]), str(args["citation_id"])))
        if name == "esheria_create_source_watch":
            return self._payload(self.client.create_source_watch(self._clean(args)))
        if name == "esheria_list_source_watches":
            return self._payload(self.client.list_source_watches(self._clean(args)))
        if name == "esheria_get_source_currentness":
            return self._payload(self.client.get_source_currentness(self._clean(args)))
        if name == "esheria_check_source_watches":
            return self._payload(self.client.check_source_watches(self._clean(args)))
        if name == "esheria_list_source_change_events":
            return self._payload(self.client.list_source_change_events(self._clean(args)))
        if name == "esheria_list_recompile_candidates":
            return self._payload(self.client.list_recompile_candidates(self._clean(args)))
        if name == "esheria_rebuild_graph_projection":
            return self._payload(self.client.rebuild_graph_projection(self._clean(args)))
        if name == "esheria_get_graph_coverage":
            return self._payload(self.client.get_graph_coverage(self._clean(args)))
        if name == "esheria_create_customer_profile":
            return self._payload(self.client.create_customer_profile(self._clean(args)))
        if name == "esheria_preview_customer_lifecycle":
            return self._payload(self.client.preview_customer_lifecycle(self._clean(args)))
        if name == "esheria_list_customer_profiles":
            customer_profile_id = str(args.get("customer_profile_id") or "").strip()
            include_runs = args.get("include_applicability_runs") is True
            if include_runs and not customer_profile_id:
                raise ValueError("include_applicability_runs requires customer_profile_id")
            if not customer_profile_id:
                return self._payload(
                    self.client.list_customer_profiles(
                        self._without(
                            args,
                            "customer_profile_id",
                            "include_applicability_runs",
                            "run_status",
                            "run_limit",
                            "run_offset",
                        )
                    )
                )
            profile = self._payload(self.client.get_customer_profile(customer_profile_id))
            if include_runs:
                run_filters = {
                    "status": args.get("run_status"),
                    "limit": args.get("run_limit"),
                    "offset": args.get("run_offset"),
                }
                runs = self._payload(
                    self.client.list_customer_applicability_runs(
                        customer_profile_id,
                        self._clean(run_filters),
                    )
                )
                profile["applicability_runs"] = runs.get("applicability_runs") or []
                profile["applicability_run_total"] = runs.get("total", len(profile["applicability_runs"]))
                profile["applicability_runs_trace_id"] = runs.get("trace_id", "")
            return profile
        if name == "esheria_run_customer_applicability":
            return self._payload(
                self.client.run_customer_applicability(
                    str(args["customer_profile_id"]),
                    self._without(args, "customer_profile_id"),
                )
            )
        if name == "esheria_list_customer_obligation_instances":
            return self._payload(self.client.list_customer_obligation_instances(self._clean(args)))
        if name == "esheria_update_customer_obligation_instance":
            return self._payload(
                self.client.update_customer_obligation_instance(
                    str(args["customer_obligation_instance_id"]),
                    self._without(args, "customer_obligation_instance_id"),
                )
            )
        if name == "esheria_recompute_customer_change_impacts":
            return self._payload(self.client.recompute_customer_change_impacts(self._clean(args)))
        if name == "esheria_list_customer_change_impacts":
            return self._payload(self.client.list_customer_change_impacts(self._clean(args)))
        if name == "esheria_update_customer_change_impact":
            return self._payload(
                self.client.update_customer_change_impact(
                    str(args["customer_change_impact_id"]),
                    self._without(args, "customer_change_impact_id"),
                )
            )
        raise KeyError(f"Unknown Esheria MCP tool `{name}`")

    @staticmethod
    def _payload(result: EsheriaResult) -> dict[str, Any]:
        payload = dict(result.data)
        payload.setdefault("trace_id", result.trace_id)
        return payload

    @classmethod
    def _without(cls, values: dict[str, Any], *keys: str) -> dict[str, Any]:
        return {key: value for key, value in cls._clean(values).items() if key not in keys}

    @staticmethod
    def _clean(values: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in values.items()
            if value is not None and value != "" and value != []
        }
