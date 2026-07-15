from __future__ import annotations

from typing import Any


def object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


STRING_ARRAY = {"type": "array", "items": {"type": "string"}, "default": []}
CONFIRM = {
    "type": "boolean",
    "const": True,
    "description": "Must be true to confirm this state-changing operation.",
}


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "esheria_health": object_schema({}),
    "esheria_ready": object_schema({}),
    "esheria_list_packs": object_schema(
        {
            "jurisdiction": {"type": "string"},
            "legal_domain": {"type": "string"},
            "status": {"type": "string"},
            "readiness_label": {"type": "string"},
            "is_current": {"type": "boolean", "default": True},
            "detail": {"type": "string", "enum": ["summary", "full"], "default": "summary"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        }
    ),
    "esheria_get_pack": object_schema({"pack_id": {"type": "string"}}, ["pack_id"]),
    "esheria_list_pack_versions": object_schema(
        {
            "pack_id": {"type": "string"},
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        },
        ["pack_id"],
    ),
    "esheria_get_pack_diff": object_schema(
        {
            "pack_id": {"type": "string"},
            "from_version": {"type": "string"},
            "to_version": {"type": "string"},
            "publication_mode": {"type": "string"},
        },
        ["pack_id"],
    ),
    "esheria_list_change_events": object_schema(
        {
            "pack_id": {"type": "string"},
            "from_version": {"type": "string"},
            "to_version": {"type": "string"},
            "publication_mode": {"type": "string"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        },
        ["pack_id"],
    ),
    "esheria_list_obligations": object_schema(
        {
            "pack_id": {"type": "string"},
            "query": {"type": "string"},
            "duty_holder": {"type": "string"},
            "workflow_target": {"type": "string"},
            "instrument_id": {"type": "string"},
            "evidence_type": {"type": "string"},
            "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        },
        ["pack_id"],
    ),
    "esheria_check_applicability": object_schema(
        {
            "pack_id": {"type": "string"},
            "entity_roles": STRING_ARRAY,
            "activities": STRING_ARRAY,
            "sector_tags": STRING_ARRAY,
            "processing_characteristics": STRING_ARRAY,
            "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 500},
        },
        ["pack_id"],
    ),
    "esheria_verify_claim": object_schema(
        {
            "claim": {"type": "string"},
            "pack_id": {"type": "string"},
            "jurisdiction": {"type": "string"},
            "domain": {"type": "string"},
            "limit": {"type": "integer", "default": 3, "minimum": 1, "maximum": 10},
        },
        ["claim", "pack_id"],
    ),
    "esheria_get_filing_calendar": object_schema(
        {
            "pack_id": {"type": "string"},
            "duty_holder": {"type": "string"},
            "workflow_target": {"type": "string"},
            "instrument_id": {"type": "string"},
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
        },
        ["pack_id"],
    ),
    "esheria_get_evidence_register": object_schema(
        {
            "pack_id": {"type": "string"},
            "duty_holder": {"type": "string"},
            "workflow_target": {"type": "string"},
            "instrument_id": {"type": "string"},
        },
        ["pack_id"],
    ),
    "esheria_get_penalty_facts": object_schema(
        {
            "pack_id": {"type": "string"},
            "version": {"type": "string"},
            "regulator_or_enforcer": {"type": "string"},
            "consequence_type": {"type": "string"},
            "linked_obligation_id": {"type": "string"},
            "linked_provision_id": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        },
        ["pack_id"],
    ),
    "esheria_get_legal_review_audit": object_schema(
        {
            "pack_id": {"type": "string"},
            "version": {"type": "string"},
            "review_decision": {"type": "string"},
            "promotion_state": {"type": "string"},
            "promotion_tier": {"type": "string"},
            "fact_class": {"type": "string"},
            "customer_actionability": {"type": "string"},
            "duty_holder_type": {"type": "string"},
            "audience_type": {"type": "string"},
            "operability_class": {"type": "string"},
            "qa_status": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        },
        ["pack_id"],
    ),
    "esheria_list_relationships": object_schema(
        {
            "pack_id": {"type": "string"},
            "relationship_type": {"type": "string"},
            "source_pack_id": {"type": "string"},
            "target_pack_id": {"type": "string"},
            "evidence_basis": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        },
        ["pack_id"],
    ),
    "esheria_query_regulatory_graph": object_schema(
        {
            "pack_ids": STRING_ARRAY,
            "relationship_types": STRING_ARRAY,
            "source_pack_id": {"type": "string"},
            "target_pack_id": {"type": "string"},
            "evidence_basis": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        },
        ["pack_ids"],
    ),
    "esheria_check_graph_applicability": object_schema(
        {
            "pack_ids": STRING_ARRAY,
            "entity_roles": STRING_ARRAY,
            "activities": STRING_ARRAY,
            "sector_tags": STRING_ARRAY,
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
        },
        ["pack_ids"],
    ),
    "esheria_get_entity_profile": object_schema(
        {
            "pack_ids": STRING_ARRAY,
            "entity_roles": STRING_ARRAY,
            "activities": STRING_ARRAY,
            "sector_tags": STRING_ARRAY,
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
        },
        ["pack_ids"],
    ),
    "esheria_export_pack": object_schema(
        {
            "pack_id": {"type": "string"},
            "include_all_forms": {"type": "boolean", "default": False},
        },
        ["pack_id"],
    ),
    "esheria_get_citation_context": object_schema(
        {"pack_id": {"type": "string"}, "citation_id": {"type": "string"}},
        ["pack_id", "citation_id"],
    ),
    "esheria_create_source_watch": object_schema(
        {
            "confirm": CONFIRM,
            "domain_pack_id": {"type": "string"},
            "source_asset_id": {"type": "string"},
            "source_uri": {"type": "string"},
            "source_kind": {"type": "string", "default": "binding"},
            "authority_type": {"type": "string", "default": "binding"},
            "expected_hash_sha256": {"type": "string"},
            "expected_etag": {"type": "string"},
            "expected_last_modified": {"type": "string"},
            "check_interval_seconds": {"type": "integer", "default": 86400, "minimum": 60},
            "status": {"type": "string", "enum": ["active", "paused", "retired"], "default": "active"},
            "metadata": {"type": "object"},
        },
        ["confirm", "domain_pack_id", "source_uri"],
    ),
    "esheria_list_source_watches": object_schema(
        {
            "domain_pack_id": {"type": "string"},
            "status": {"type": "string"},
            "source_kind": {"type": "string"},
            "authority_type": {"type": "string"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        }
    ),
    "esheria_get_source_currentness": object_schema(
        {
            "domain_pack_id": {"type": "string"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        }
    ),
    "esheria_check_source_watches": object_schema(
        {
            "confirm": CONFIRM,
            "domain_pack_id": {"type": "string"},
            "status": {"type": "string", "default": "active"},
            "source_kind": {"type": "string"},
            "authority_type": {"type": "string"},
            "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 20},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        },
        ["confirm"],
    ),
    "esheria_list_source_change_events": object_schema(
        {
            "domain_pack_id": {"type": "string"},
            "source_kind": {"type": "string"},
            "authority_type": {"type": "string"},
            "change_type": {"type": "string"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        }
    ),
    "esheria_list_recompile_candidates": object_schema(
        {
            "domain_pack_id": {"type": "string"},
            "status": {"type": "string"},
            "candidate_type": {"type": "string"},
            "priority": {"type": "string"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        }
    ),
    "esheria_rebuild_graph_projection": object_schema(
        {
            "confirm": CONFIRM,
            "reason": {"type": "string", "default": "manual"},
            "requested_by": {"type": "string"},
            "metadata": {"type": "object"},
        },
        ["confirm"],
    ),
    "esheria_get_graph_coverage": object_schema(
        {
            "domain_pack_id": {"type": "string"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        }
    ),
    "esheria_create_customer_profile": object_schema(
        {
            "confirm": CONFIRM,
            "profile_name": {"type": "string"},
            "default_pack_ids": STRING_ARRAY,
            "entity_profile": {"type": "object"},
            "profile_facts": {"type": "array", "items": {"type": "object"}, "default": []},
            "metadata": {"type": "object"},
        },
        ["confirm", "profile_name"],
    ),
    "esheria_preview_customer_lifecycle": object_schema(
        {
            "pack_ids": STRING_ARRAY,
            "locked_pack_versions": {"type": "object"},
            "entity_roles": STRING_ARRAY,
            "activities": STRING_ARRAY,
            "sector_tags": STRING_ARRAY,
            "processing_characteristics": STRING_ARRAY,
            "entity_profile": {"type": "object"},
            "profile_facts": {"type": "array", "items": {"type": "object"}, "default": []},
            "include_change_impacts": {"type": "boolean", "default": True},
            "from_version": {"type": "string"},
            "to_version": {"type": "string"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
        },
        ["pack_ids"],
    ),
    "esheria_list_customer_profiles": object_schema(
        {
            "customer_profile_id": {
                "type": "string",
                "description": "When supplied, inspect this profile instead of listing profiles.",
            },
            "include_applicability_runs": {
                "type": "boolean",
                "default": False,
                "description": "Include prior applicability runs when customer_profile_id is supplied.",
            },
            "status": {"type": "string"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
            "run_status": {"type": "string"},
            "run_limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 100},
            "run_offset": {"type": "integer", "default": 0, "minimum": 0},
        }
    ),
    "esheria_run_customer_applicability": object_schema(
        {
            "confirm": CONFIRM,
            "customer_profile_id": {"type": "string"},
            "pack_ids": STRING_ARRAY,
            "locked_pack_versions": {"type": "object"},
            "entity_roles": STRING_ARRAY,
            "activities": STRING_ARRAY,
            "sector_tags": STRING_ARRAY,
            "processing_characteristics": STRING_ARRAY,
            "entity_profile": {"type": "object"},
            "profile_facts": {"type": "array", "items": {"type": "object"}, "default": []},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
        },
        ["confirm", "customer_profile_id"],
    ),
    "esheria_list_customer_obligation_instances": object_schema(
        {
            "customer_profile_id": {"type": "string"},
            "domain_pack_id": {"type": "string"},
            "status": {"type": "string"},
            "applicability_status": {"type": "string"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        }
    ),
    "esheria_update_customer_obligation_instance": object_schema(
        {
            "confirm": CONFIRM,
            "customer_obligation_instance_id": {"type": "string"},
            "status": {"type": "string", "enum": ["candidate", "accepted", "not_applicable", "monitoring", "retired"]},
            "owner_user_id": {"type": "string"},
            "owner_label": {"type": "string"},
            "due_date": {"type": "string"},
            "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
            "status_reason": {"type": "string"},
            "status_updated_by": {"type": "string"},
            "lifecycle_metadata": {"type": "object"},
        },
        ["confirm", "customer_obligation_instance_id"],
    ),
    "esheria_recompute_customer_change_impacts": object_schema(
        {
            "confirm": CONFIRM,
            "customer_profile_id": {"type": "string"},
            "domain_pack_id": {"type": "string"},
            "from_version": {"type": "string"},
            "to_version": {"type": "string"},
            "limit": {"type": "integer", "default": 500, "minimum": 1, "maximum": 1000},
        },
        ["confirm"],
    ),
    "esheria_list_customer_change_impacts": object_schema(
        {
            "customer_profile_id": {"type": "string"},
            "domain_pack_id": {"type": "string"},
            "status": {"type": "string"},
            "impact_type": {"type": "string"},
            "materiality": {"type": "string"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
        }
    ),
    "esheria_update_customer_change_impact": object_schema(
        {
            "confirm": CONFIRM,
            "customer_change_impact_id": {"type": "string"},
            "status": {"type": "string", "enum": ["open", "acknowledged", "resolved", "dismissed"]},
            "status_reason": {"type": "string"},
            "status_updated_by": {"type": "string"},
            "resolution_payload": {"type": "object"},
        },
        ["confirm", "customer_change_impact_id", "status"],
    ),
}
