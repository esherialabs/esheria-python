from __future__ import annotations

from typing import Any


PROMPTS: dict[str, str] = {
    "build_compliance_obligation_register": (
        "Use Esheria applicability and obligation tools to build a citation-backed obligation register. "
        "Surface citation_ids, quote_spans, readiness_label, limitations, and trace_id."
    ),
    "build_filing_calendar": (
        "Use Esheria filing calendar and applicability tools to build calendar tasks. "
        "Do not infer deadlines that are not returned by tools."
    ),
    "build_evidence_register": (
        "Use Esheria evidence register and obligation tools to group evidence/control requirements. "
        "Keep citations attached to each evidence type."
    ),
    "verify_generated_answer": (
        "Use Esheria claim verification before showing a generated regulatory answer. "
        "If unsupported or corrected, surface the issue labels and corrections."
    ),
    "compare_pack_duties": (
        "Use Esheria graph and obligation tools to compare published duties across packs. "
        "Report sparse graph results as a limitation, not as no legal overlap."
    ),
}


def prompt_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": text,
            "arguments": [
                {"name": "pack_id", "description": "Primary regulatory pack ID.", "required": False},
                {"name": "entity_profile", "description": "Entity roles, activities, and sectors.", "required": False},
            ],
        }
        for name, text in PROMPTS.items()
    ]


def get_prompt(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    if name not in PROMPTS:
        raise KeyError(f"Unknown Esheria prompt `{name}`")
    args = arguments or {}
    suffix = f"\nInputs: {args}" if args else ""
    return {
        "description": PROMPTS[name],
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": PROMPTS[name] + suffix,
                },
            }
        ],
    }
