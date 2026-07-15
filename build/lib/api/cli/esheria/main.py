from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import yaml

from api.clients.esheria_regulatory import (
    EsheriaApiError,
    EsheriaAuthenticationError,
    EsheriaAuthorizationError,
    EsheriaClientConfig,
    EsheriaRegulatoryClient,
    EsheriaTimeoutError,
    EsheriaTransportError,
)
from api.clients.esheria_regulatory.models import EsheriaResult
from api.clients.esheria_regulatory.version import CLI_USER_AGENT, PACKAGE_VERSION


EXIT_API_ERROR = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_NETWORK = 4
EXIT_NOT_READY = 5

NDJSON_LIST_KEYS = (
    "packs",
    "versions",
    "changes",
    "change_events",
    "obligations",
    "applicable_obligations",
    "calendar_items",
    "evidence_register",
    "penalty_facts",
    "legal_review_items",
    "relationships",
    "tokens",
    "usage",
    "plans",
    "source_watches",
    "source_currentness",
    "checks",
    "source_change_events",
    "recompile_candidates",
    "coverage_reports",
    "customer_profiles",
    "applicability_runs",
    "customer_obligation_instances",
    "customer_change_impacts",
    "obligation_previews",
    "impact_previews",
)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _add_output_flags(parser: argparse.ArgumentParser, *, global_defaults: bool = False) -> None:
    parser.add_argument(
        "--format",
        choices=["table", "json", "ndjson", "yaml"],
        default="table" if global_defaults else argparse.SUPPRESS,
        help="Output format.",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        default=False if global_defaults else argparse.SUPPRESS,
        help="Show API trace IDs in human-readable output.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False if global_defaults else argparse.SUPPRESS,
        help="Suppress non-essential human-readable output.",
    )
    payload_group = parser.add_mutually_exclusive_group()
    payload_group.add_argument(
        "--raw",
        action="store_true",
        default=False if global_defaults else argparse.SUPPRESS,
        help="Print only the API data object.",
    )
    payload_group.add_argument(
        "--envelope",
        action="store_true",
        default=False if global_defaults else argparse.SUPPRESS,
        help="Print the full API envelope.",
    )


def _add_pack_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--jurisdiction")
    parser.add_argument("--domain", dest="legal_domain")
    parser.add_argument("--legal-domain", dest="legal_domain")
    parser.add_argument("--status")
    parser.add_argument("--readiness", dest="readiness_label")
    parser.add_argument("--detail", choices=["summary", "full"])
    parser.add_argument("--limit", type=_positive_int, default=100)
    parser.add_argument("--offset", type=_non_negative_int, default=0)


def _add_obligation_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--version")
    parser.add_argument("-q", "--query")
    parser.add_argument("--duty-holder")
    parser.add_argument("--workflow-target")
    parser.add_argument("--instrument", dest="instrument_id")
    parser.add_argument("--evidence-type")
    parser.add_argument("--fact-class")
    parser.add_argument("--customer-actionability")
    parser.add_argument("--limit", type=_positive_int, default=50)
    parser.add_argument("--offset", type=_non_negative_int, default=0)


def _add_version_range_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--from-version")
    parser.add_argument("--to-version")
    parser.add_argument("--publication-mode")


def _add_penalty_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-q", "--query")
    parser.add_argument("--version")
    parser.add_argument("--regulator-or-enforcer")
    parser.add_argument("--consequence-type")
    parser.add_argument("--linked-obligation-id")
    parser.add_argument("--linked-provision-id")
    parser.add_argument("--limit", type=_positive_int, default=50)
    parser.add_argument("--offset", type=_non_negative_int, default=0)


def _add_legal_review_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-q", "--query")
    parser.add_argument("--version")
    parser.add_argument("--review-decision")
    parser.add_argument("--promotion-state")
    parser.add_argument("--promotion-tier")
    parser.add_argument("--fact-class")
    parser.add_argument("--customer-actionability")
    parser.add_argument("--duty-holder-type")
    parser.add_argument("--audience-type")
    parser.add_argument("--operability-class")
    parser.add_argument("--qa-status")
    parser.add_argument("--limit", type=_positive_int, default=50)
    parser.add_argument("--offset", type=_non_negative_int, default=0)


def _add_profile_flags(
    parser: argparse.ArgumentParser,
    *,
    include_processing: bool = True,
    include_profile_file: bool = True,
) -> None:
    parser.add_argument("--role", dest="entity_roles", action="append", default=[])
    parser.add_argument("--activity", dest="activities", action="append", default=[])
    parser.add_argument("--sector", dest="sector_tags", action="append", default=[])
    if include_processing:
        parser.add_argument("--processing-characteristic", dest="processing_characteristics", action="append", default=[])
    if include_profile_file:
        parser.add_argument("--profile-file")
    parser.add_argument("--limit", type=_positive_int, default=100)


def _add_relationship_filters(parser: argparse.ArgumentParser, *, multiple_types: bool) -> None:
    if multiple_types:
        parser.add_argument("--relationship-type", dest="relationship_types", action="append", default=[])
    else:
        parser.add_argument("--relationship-type")
    parser.add_argument("--source-pack", dest="source_pack_id")
    parser.add_argument("--target-pack", dest="target_pack_id")
    parser.add_argument("--evidence-basis")
    parser.add_argument("--query")
    parser.add_argument("--limit", type=_positive_int, default=100)
    parser.add_argument("--offset", type=_non_negative_int, default=0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="esheria",
        description="Esheria Regulatory Pack API CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {PACKAGE_VERSION}")
    parser.add_argument("--base-url", default=None, help="Override ESHERIA_API_BASE_URL.")
    parser.add_argument(
        "--api-key",
        default=None,
        help="Override ESHERIA_API_KEY. Prefer the environment variable to avoid shell history and process-list exposure.",
    )
    parser.add_argument("--timeout", type=_positive_float, default=None, help="Request timeout in seconds.")
    parser.add_argument("--retry-count", type=_non_negative_int, default=None, help="Transient retry count.")
    parser.add_argument("--user-agent", default=None, help=argparse.SUPPRESS)
    _add_output_flags(parser, global_defaults=True)
    sub = parser.add_subparsers(dest="command", required=True)

    health = sub.add_parser("health", help="Check API liveness.")
    _add_output_flags(health)
    health.set_defaults(func=cmd_health)

    ready = sub.add_parser("ready", help="Check API dependency readiness.")
    _add_output_flags(ready)
    ready.set_defaults(func=cmd_ready)

    mcp = sub.add_parser("mcp", help="Run the packaged MCP server.")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_serve = mcp_sub.add_parser(
        "serve",
        help="Serve MCP over stdio or Streamable HTTP.",
        description="Run the packaged Esheria MCP server over stdio or Streamable HTTP.",
    )
    transport = mcp_serve.add_mutually_exclusive_group()
    transport.add_argument("--stdio", action="store_true", help="Serve MCP over stdio (default).")
    transport.add_argument("--http", action="store_true", help="Serve MCP over Streamable HTTP.")
    mcp_serve.add_argument("--host")
    mcp_serve.add_argument("--port", type=int)
    mcp_serve.add_argument("--path")
    mcp_serve.add_argument("--base-url")
    mcp_serve.add_argument("--api-key")
    mcp_serve.add_argument("--timeout", type=float)
    mcp_serve.add_argument("--retry-count", type=int)
    mcp_serve.set_defaults(func=cmd_mcp_serve, requires_client=False)

    doctor = sub.add_parser("doctor", help="Validate configuration and API access.")
    doctor.add_argument("--pack", help="Also make a minimal authenticated request for this pack.")
    _add_output_flags(doctor)
    doctor.set_defaults(func=cmd_doctor)

    packs = sub.add_parser("packs", help="Discover, inspect, compare, and export regulatory packs.")
    packs_sub = packs.add_subparsers(dest="packs_command", required=True)
    packs_list = packs_sub.add_parser("list", help="List current regulatory packs.")
    _add_pack_filters(packs_list)
    _add_output_flags(packs_list)
    packs_list.set_defaults(func=cmd_packs_list)
    packs_inspect = packs_sub.add_parser("inspect", help="Inspect one regulatory pack.")
    packs_inspect.add_argument("pack_id")
    _add_output_flags(packs_inspect)
    packs_inspect.set_defaults(func=cmd_packs_inspect)
    packs_export = packs_sub.add_parser("export", help="Export a published regulatory pack.")
    packs_export.add_argument("pack_id")
    packs_export.add_argument("--version")
    packs_export.add_argument("--include-all-forms", action="store_true")
    packs_export.add_argument("--out")
    _add_output_flags(packs_export)
    packs_export.set_defaults(func=cmd_packs_export)
    packs_versions = packs_sub.add_parser("versions", help="List loaded historical pack versions.")
    packs_versions.add_argument("pack_id")
    packs_versions.add_argument("--limit", type=_positive_int, default=50)
    packs_versions.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(packs_versions)
    packs_versions.set_defaults(func=cmd_packs_versions)
    packs_diff = packs_sub.add_parser("diff", help="Diff canonical facts between pack versions.")
    packs_diff.add_argument("pack_id")
    _add_version_range_filters(packs_diff)
    _add_output_flags(packs_diff)
    packs_diff.set_defaults(func=cmd_packs_diff)
    packs_change_events = packs_sub.add_parser("change-events", help="List legal change events between pack versions.")
    packs_change_events.add_argument("pack_id")
    _add_version_range_filters(packs_change_events)
    packs_change_events.add_argument("--limit", type=_positive_int, default=100)
    packs_change_events.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(packs_change_events)
    packs_change_events.set_defaults(func=cmd_packs_change_events)

    obligations = sub.add_parser("obligations", help="List published regulatory obligations.")
    obligations_sub = obligations.add_subparsers(dest="obligations_command", required=True)
    obligations_list = obligations_sub.add_parser("list", help="List and filter obligations for a pack.")
    obligations_list.add_argument("pack_id")
    _add_obligation_filters(obligations_list)
    _add_output_flags(obligations_list)
    obligations_list.set_defaults(func=cmd_obligations_list)

    applicability = sub.add_parser("applicability", help="Check which obligations may apply to an entity profile.")
    applicability_sub = applicability.add_subparsers(dest="applicability_command", required=True)
    applicability_check = applicability_sub.add_parser("check", help="Run a pack applicability check.")
    applicability_check.add_argument("pack_id")
    _add_profile_flags(applicability_check)
    _add_output_flags(applicability_check)
    applicability_check.set_defaults(func=cmd_applicability_check)

    claims = sub.add_parser("claims", help="Verify legal claims against published facts.")
    claims_sub = claims.add_subparsers(dest="claims_command", required=True)
    claims_verify = claims_sub.add_parser("verify", help="Verify one claim against a supported pack evaluator.")
    claims_verify.add_argument("--pack", dest="pack_id", required=True)
    claims_verify.add_argument("--jurisdiction")
    claims_verify.add_argument("--domain")
    claims_verify.add_argument("--limit", type=_positive_int, default=3)
    claims_verify.add_argument("claim")
    _add_output_flags(claims_verify)
    claims_verify.set_defaults(func=cmd_claims_verify)

    workspace = sub.add_parser("workspace", help="Inspect or update the current workspace with a management token.")
    workspace_sub = workspace.add_subparsers(dest="workspace_command", required=True)
    workspace_show = workspace_sub.add_parser("show", help="Show current workspace settings.")
    _add_output_flags(workspace_show)
    workspace_show.set_defaults(func=cmd_workspace_show)
    workspace_update = workspace_sub.add_parser("update", help="Update current workspace settings.")
    workspace_update.add_argument("--display-name", required=True)
    workspace_update.add_argument("--billing-contact-email")
    workspace_update.add_argument("--metadata-json")
    _add_output_flags(workspace_update)
    workspace_update.set_defaults(func=cmd_workspace_update)

    tokens = sub.add_parser("tokens", help="Manage data tokens with a management token.")
    tokens_sub = tokens.add_subparsers(dest="tokens_command", required=True)
    tokens_list = tokens_sub.add_parser("list", help="List workspace API tokens without secrets.")
    tokens_list.add_argument("--status")
    tokens_list.add_argument("--type", dest="token_type")
    tokens_list.add_argument("--limit", type=_positive_int, default=100)
    tokens_list.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(tokens_list)
    tokens_list.set_defaults(func=cmd_tokens_list)
    tokens_create = tokens_sub.add_parser("create", help="Create a data token and display its one-time secret.")
    tokens_create.add_argument("--name", required=True)
    tokens_create.add_argument(
        "--scope",
        dest="scopes",
        action="append",
        default=[],
        metavar="SCOPE",
        help=(
            "Repeat for explicit data-token scopes: regulatory:read, monitoring:write, "
            "graph:write, or customer:write. Defaults to regulatory:read."
        ),
    )
    tokens_create.add_argument("--pack", dest="pack_entitlements", action="append", default=[])
    tokens_create.add_argument("--expires-at")
    tokens_create.add_argument("--metadata-json")
    _add_output_flags(tokens_create)
    tokens_create.set_defaults(func=cmd_tokens_create)
    tokens_revoke = tokens_sub.add_parser("revoke", help="Revoke a workspace API token.")
    tokens_revoke.add_argument("token_id")
    _add_output_flags(tokens_revoke)
    tokens_revoke.set_defaults(func=cmd_tokens_revoke)

    billing = sub.add_parser("billing", help="Inspect credits, usage, plans, and subscription state.")
    billing_sub = billing.add_subparsers(dest="billing_command", required=True)
    billing_balance = billing_sub.add_parser("balance", help="Show current workspace credit balance.")
    _add_output_flags(billing_balance)
    billing_balance.set_defaults(func=cmd_billing_balance)
    billing_usage = billing_sub.add_parser("usage", help="List metered API usage.")
    billing_usage.add_argument("--token-id")
    billing_usage.add_argument("--endpoint-family")
    billing_usage.add_argument("--pack-id")
    billing_usage.add_argument("--date-from")
    billing_usage.add_argument("--date-to")
    billing_usage.add_argument("--limit", type=_positive_int, default=100)
    billing_usage.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(billing_usage)
    billing_usage.set_defaults(func=cmd_billing_usage)
    billing_plans = billing_sub.add_parser("plans", help="List available billing plans.")
    _add_output_flags(billing_plans)
    billing_plans.set_defaults(func=cmd_billing_plans)
    billing_topup = billing_sub.add_parser(
        "checkout",
        aliases=["topup"],
        help="Create Stripe Checkout from a server-owned billing SKU.",
    )
    billing_topup.add_argument("--sku-id", help="SKU from `esheria billing plans`.")
    billing_topup.add_argument("--credits", type=_positive_int, help=argparse.SUPPRESS)
    billing_topup.add_argument("--plan-id", help=argparse.SUPPRESS)
    billing_topup.add_argument("--subscription", action="store_true", help=argparse.SUPPRESS)
    _add_output_flags(billing_topup)
    billing_topup.set_defaults(func=cmd_billing_topup)
    billing_subscription = billing_sub.add_parser("subscription", help="Show the current workspace subscription.")
    _add_output_flags(billing_subscription)
    billing_subscription.set_defaults(func=cmd_billing_subscription)
    billing_cancel = billing_sub.add_parser("cancel-subscription", help="Cancel the current workspace subscription.")
    billing_cancel.add_argument(
        "--at-period-end",
        action="store_true",
        help="Cancel at the end of the billing period instead of immediately.",
    )
    billing_cancel.add_argument("--yes", action="store_true", help="Confirm the cancellation request.")
    _add_output_flags(billing_cancel)
    billing_cancel.set_defaults(func=cmd_billing_cancel_subscription)

    calendar = sub.add_parser("calendar", help="List filing and deadline calendar items.")
    calendar_sub = calendar.add_subparsers(dest="calendar_command", required=True)
    calendar_list = calendar_sub.add_parser("list", help="List filing and deadline items for a pack.")
    calendar_list.add_argument("pack_id")
    calendar_list.add_argument("--version")
    calendar_list.add_argument("--duty-holder")
    calendar_list.add_argument("--workflow-target")
    calendar_list.add_argument("--instrument", dest="instrument_id")
    calendar_list.add_argument("--limit", type=_positive_int, default=100)
    _add_output_flags(calendar_list)
    calendar_list.set_defaults(func=cmd_calendar_list)

    evidence = sub.add_parser("evidence", help="List evidence requirements for a pack.")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_list = evidence_sub.add_parser("list", help="List grouped evidence requirements.")
    evidence_list.add_argument("pack_id")
    evidence_list.add_argument("--version")
    evidence_list.add_argument("--duty-holder")
    evidence_list.add_argument("--workflow-target")
    evidence_list.add_argument("--instrument", dest="instrument_id")
    _add_output_flags(evidence_list)
    evidence_list.set_defaults(func=cmd_evidence_list)

    penalties = sub.add_parser("penalties", help="List source-backed penalty and consequence facts.")
    penalties_sub = penalties.add_subparsers(dest="penalties_command", required=True)
    penalties_list = penalties_sub.add_parser("list", help="List penalty and consequence facts for a pack.")
    penalties_list.add_argument("pack_id")
    _add_penalty_filters(penalties_list)
    _add_output_flags(penalties_list)
    penalties_list.set_defaults(func=cmd_penalties_list)

    legal_review = sub.add_parser("legal-review", help="Inspect legal review and publication audit metadata.")
    legal_review_sub = legal_review.add_subparsers(dest="legal_review_command", required=True)
    legal_review_audit = legal_review_sub.add_parser("audit", help="List legal review audit rows.")
    legal_review_audit.add_argument("pack_id")
    _add_legal_review_filters(legal_review_audit)
    _add_output_flags(legal_review_audit)
    legal_review_audit.set_defaults(func=cmd_legal_review_audit)

    citations = sub.add_parser("citations", help="Resolve published citation context.")
    citations_sub = citations.add_subparsers(dest="citations_command", required=True)
    citations_get = citations_sub.add_parser("get", help="Resolve one citation from a published pack export.")
    citations_get.add_argument("pack_id")
    citations_get.add_argument("--citation-id", required=True)
    _add_output_flags(citations_get)
    citations_get.set_defaults(func=cmd_citations_get)

    relationships = sub.add_parser("relationships", help="List stored regulatory relationship facts.")
    relationships_sub = relationships.add_subparsers(dest="relationships_command", required=True)
    relationships_list = relationships_sub.add_parser("list", help="List relationships involving a pack.")
    relationships_list.add_argument("pack_id")
    relationships_list.add_argument("--version")
    _add_relationship_filters(relationships_list, multiple_types=False)
    _add_output_flags(relationships_list)
    relationships_list.set_defaults(func=cmd_relationships_list)

    graph = sub.add_parser("graph", help="Query and operate the regulatory relationship graph.")
    graph_sub = graph.add_subparsers(dest="graph_command", required=True)
    graph_query = graph_sub.add_parser("query", help="Query cross-pack relationships.")
    graph_query.add_argument("--pack", dest="pack_ids", action="append", required=True)
    _add_relationship_filters(graph_query, multiple_types=True)
    _add_output_flags(graph_query)
    graph_query.set_defaults(func=cmd_graph_query)
    graph_applicability = graph_sub.add_parser("applicability", help="Run multi-pack applicability with relationship context.")
    graph_applicability.add_argument("--pack", dest="pack_ids", action="append", required=True)
    _add_profile_flags(graph_applicability, include_processing=False, include_profile_file=False)
    _add_output_flags(graph_applicability)
    graph_applicability.set_defaults(func=cmd_graph_applicability)
    graph_profile = graph_sub.add_parser("entity-profile", help="Summarize an entity profile across packs.")
    graph_profile.add_argument("--pack", dest="pack_ids", action="append", required=True)
    _add_profile_flags(graph_profile, include_processing=False, include_profile_file=False)
    _add_output_flags(graph_profile)
    graph_profile.set_defaults(func=cmd_graph_entity_profile)
    graph_rebuild = graph_sub.add_parser(
        "rebuild-projection",
        help="Operator action: rebuild graph projections from published facts.",
    )
    graph_rebuild.add_argument("--reason", default="manual")
    graph_rebuild.add_argument("--requested-by", default="esheria_cli")
    graph_rebuild.add_argument("--metadata-json")
    graph_rebuild.add_argument("--yes", action="store_true", help="Confirm the graph projection rebuild.")
    _add_output_flags(graph_rebuild)
    graph_rebuild.set_defaults(func=cmd_graph_rebuild_projection)
    graph_coverage = graph_sub.add_parser("coverage", help="Inspect published-fact graph coverage.")
    graph_coverage.add_argument("--domain-pack-id")
    graph_coverage.add_argument("--limit", type=_positive_int, default=100)
    graph_coverage.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(graph_coverage)
    graph_coverage.set_defaults(func=cmd_graph_coverage)

    monitoring = sub.add_parser("monitoring", help="Inspect and operate regulatory source monitoring.")
    monitoring_sub = monitoring.add_subparsers(dest="monitoring_command", required=True)
    monitoring_watches = monitoring_sub.add_parser("watches", help="List configured source watches.")
    monitoring_watches.add_argument("--domain-pack-id")
    monitoring_watches.add_argument("--status", choices=["active", "paused", "retired"])
    monitoring_watches.add_argument("--source-kind", choices=["binding", "guidance", "watchlist", "context"])
    monitoring_watches.add_argument("--authority-type", choices=["binding", "non_binding", "watchlist", "context"])
    monitoring_watches.add_argument("--limit", type=_positive_int, default=100)
    monitoring_watches.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(monitoring_watches)
    monitoring_watches.set_defaults(func=cmd_monitoring_watches)
    monitoring_create_watch = monitoring_sub.add_parser(
        "create-watch",
        help="Operator action: create or update a regulatory source watch.",
    )
    monitoring_create_watch.add_argument("--domain-pack-id", required=True)
    monitoring_create_watch.add_argument("--source-uri", required=True)
    monitoring_create_watch.add_argument("--source-asset-id", default="")
    monitoring_create_watch.add_argument(
        "--source-kind",
        choices=["binding", "guidance", "watchlist", "context"],
        default="binding",
    )
    monitoring_create_watch.add_argument(
        "--authority-type",
        choices=["binding", "non_binding", "watchlist", "context"],
        default="binding",
    )
    monitoring_create_watch.add_argument("--expected-hash-sha256", default="")
    monitoring_create_watch.add_argument("--expected-etag", default="")
    monitoring_create_watch.add_argument("--expected-last-modified", default="")
    monitoring_create_watch.add_argument("--check-interval-seconds", type=_positive_int, default=86400)
    monitoring_create_watch.add_argument("--status", choices=["active", "paused", "retired"], default="active")
    monitoring_create_watch.add_argument("--metadata-json")
    _add_output_flags(monitoring_create_watch)
    monitoring_create_watch.set_defaults(func=cmd_monitoring_create_watch)
    monitoring_currentness = monitoring_sub.add_parser("currentness", help="List latest source-currentness snapshots.")
    monitoring_currentness.add_argument("--domain-pack-id")
    monitoring_currentness.add_argument("--limit", type=_positive_int, default=100)
    monitoring_currentness.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(monitoring_currentness)
    monitoring_currentness.set_defaults(func=cmd_monitoring_currentness)
    monitoring_check = monitoring_sub.add_parser("check", help="Operator action: run configured source checks.")
    monitoring_check.add_argument("--domain-pack-id")
    monitoring_check.add_argument("--status", choices=["active", "paused", "retired"])
    monitoring_check.add_argument("--source-kind", choices=["binding", "guidance", "watchlist", "context"])
    monitoring_check.add_argument("--authority-type", choices=["binding", "non_binding", "watchlist", "context"])
    monitoring_check.add_argument("--limit", type=_positive_int, default=100)
    monitoring_check.add_argument("--offset", type=_non_negative_int, default=0)
    monitoring_check.add_argument("--yes", action="store_true", help="Confirm the source-check run.")
    _add_output_flags(monitoring_check)
    monitoring_check.set_defaults(func=cmd_monitoring_check)
    monitoring_changes = monitoring_sub.add_parser("changes", help="List recorded source-change events.")
    monitoring_changes.add_argument("--domain-pack-id")
    monitoring_changes.add_argument("--source-kind", choices=["binding", "guidance", "watchlist", "context"])
    monitoring_changes.add_argument("--authority-type", choices=["binding", "non_binding", "watchlist", "context"])
    monitoring_changes.add_argument("--change-type")
    monitoring_changes.add_argument("--limit", type=_positive_int, default=100)
    monitoring_changes.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(monitoring_changes)
    monitoring_changes.set_defaults(func=cmd_monitoring_changes)
    monitoring_recompile = monitoring_sub.add_parser("recompile-candidates", help="List open or historical recompile candidates.")
    monitoring_recompile.add_argument("--domain-pack-id")
    monitoring_recompile.add_argument("--status")
    monitoring_recompile.add_argument("--candidate-type")
    monitoring_recompile.add_argument("--priority")
    monitoring_recompile.add_argument("--limit", type=_positive_int, default=100)
    monitoring_recompile.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(monitoring_recompile)
    monitoring_recompile.set_defaults(func=cmd_monitoring_recompile_candidates)

    customers = sub.add_parser("customers", help="Preview or manage workspace-scoped regulatory lifecycle state.")
    customers_sub = customers.add_subparsers(dest="customers_command", required=True)
    customers_preview = customers_sub.add_parser("preview", help="Preview applicability and change impacts without writes.")
    customers_preview.add_argument("--pack", dest="pack_ids", action="append", required=True)
    customers_preview.add_argument("--profile-file")
    customers_preview.add_argument("--role", dest="entity_roles", action="append", default=[])
    customers_preview.add_argument("--activity", dest="activities", action="append", default=[])
    customers_preview.add_argument("--sector", dest="sector_tags", action="append", default=[])
    customers_preview.add_argument("--processing", dest="processing_characteristics", action="append", default=[])
    customers_preview.add_argument("--from-version")
    customers_preview.add_argument("--to-version")
    customers_preview.add_argument("--no-change-impacts", action="store_true")
    customers_preview.add_argument("--limit", type=_positive_int, default=100)
    _add_output_flags(customers_preview)
    customers_preview.set_defaults(func=cmd_customers_preview)
    customers_profiles_list = customers_sub.add_parser("profiles", help="List workspace customer profiles.")
    customers_profiles_list.add_argument("--status")
    customers_profiles_list.add_argument("--limit", type=_positive_int, default=100)
    customers_profiles_list.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(customers_profiles_list)
    customers_profiles_list.set_defaults(func=cmd_customers_profiles)
    customers_inspect_profile = customers_sub.add_parser("inspect-profile", help="Inspect one workspace customer profile.")
    customers_inspect_profile.add_argument("customer_profile_id")
    _add_output_flags(customers_inspect_profile)
    customers_inspect_profile.set_defaults(func=cmd_customers_inspect_profile)
    customers_create_profile = customers_sub.add_parser("create-profile", help="Create an opt-in workspace customer profile.")
    customers_create_profile.add_argument("--name", dest="profile_name", required=True)
    customers_create_profile.add_argument("--pack", dest="default_pack_ids", action="append", default=[])
    customers_create_profile.add_argument("--profile-file")
    _add_output_flags(customers_create_profile)
    customers_create_profile.set_defaults(func=cmd_customers_create_profile)
    customers_run = customers_sub.add_parser("run-applicability", help="Run and persist applicability against locked pack versions.")
    customers_run.add_argument("customer_profile_id")
    customers_run.add_argument("--pack", dest="pack_ids", action="append", default=[])
    customers_run.add_argument("--profile-file")
    customers_run.add_argument("--limit", type=_positive_int, default=100)
    _add_output_flags(customers_run)
    customers_run.set_defaults(func=cmd_customers_run_applicability)
    customers_runs = customers_sub.add_parser("applicability-runs", help="List persisted applicability runs for a profile.")
    customers_runs.add_argument("customer_profile_id")
    customers_runs.add_argument("--limit", type=_positive_int, default=100)
    customers_runs.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(customers_runs)
    customers_runs.set_defaults(func=cmd_customers_applicability_runs)
    customers_obligations = customers_sub.add_parser("obligations", help="List workspace customer obligation instances.")
    customers_obligations.add_argument("--customer-profile-id")
    customers_obligations.add_argument("--domain-pack-id")
    customers_obligations.add_argument("--status")
    customers_obligations.add_argument("--applicability-status")
    customers_obligations.add_argument("--limit", type=_positive_int, default=100)
    customers_obligations.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(customers_obligations)
    customers_obligations.set_defaults(func=cmd_customers_obligations)
    customers_update_obligation = customers_sub.add_parser("update-obligation", help="Update obligation lifecycle state.")
    customers_update_obligation.add_argument("customer_obligation_instance_id")
    customers_update_obligation.add_argument("--status", choices=["candidate", "accepted", "not_applicable", "monitoring", "retired"])
    customers_update_obligation.add_argument("--owner-user-id")
    customers_update_obligation.add_argument("--owner-label")
    customers_update_obligation.add_argument("--due-date")
    customers_update_obligation.add_argument("--priority", choices=["low", "normal", "high", "urgent"])
    customers_update_obligation.add_argument("--status-reason")
    customers_update_obligation.add_argument("--status-updated-by")
    customers_update_obligation.add_argument("--metadata-json")
    _add_output_flags(customers_update_obligation)
    customers_update_obligation.set_defaults(func=cmd_customers_update_obligation)
    customers_impacts = customers_sub.add_parser("impacts", help="List workspace customer change impacts.")
    customers_impacts.add_argument("--customer-profile-id")
    customers_impacts.add_argument("--domain-pack-id")
    customers_impacts.add_argument("--status")
    customers_impacts.add_argument("--impact-type")
    customers_impacts.add_argument("--materiality")
    customers_impacts.add_argument("--limit", type=_positive_int, default=100)
    customers_impacts.add_argument("--offset", type=_non_negative_int, default=0)
    _add_output_flags(customers_impacts)
    customers_impacts.set_defaults(func=cmd_customers_impacts)
    customers_recompute = customers_sub.add_parser("recompute-impacts", help="Recompute workspace customer change impacts.")
    customers_recompute.add_argument("--customer-profile-id")
    customers_recompute.add_argument("--domain-pack-id")
    customers_recompute.add_argument("--from-version")
    customers_recompute.add_argument("--to-version")
    customers_recompute.add_argument("--limit", type=_positive_int, default=500)
    _add_output_flags(customers_recompute)
    customers_recompute.set_defaults(func=cmd_customers_recompute_impacts)
    customers_update_impact = customers_sub.add_parser("update-impact", help="Update customer change-impact lifecycle state.")
    customers_update_impact.add_argument("customer_change_impact_id")
    customers_update_impact.add_argument("--status", required=True, choices=["open", "acknowledged", "resolved", "dismissed"])
    customers_update_impact.add_argument("--status-reason")
    customers_update_impact.add_argument("--status-updated-by")
    customers_update_impact.add_argument("--resolution-json")
    _add_output_flags(customers_update_impact)
    customers_update_impact.set_defaults(func=cmd_customers_update_impact)

    smoke = sub.add_parser("smoke", help="Run a release-oriented API smoke suite for one pack.")
    smoke.add_argument("--pack", required=True)
    smoke.add_argument("--expected-published-rows", type=_non_negative_int)
    _add_output_flags(smoke)
    smoke.set_defaults(func=cmd_smoke)
    return parser


def client_from_args(args: argparse.Namespace) -> EsheriaRegulatoryClient:
    config = EsheriaClientConfig.from_env().with_overrides(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout_seconds=args.timeout,
        retry_count=args.retry_count,
        user_agent=args.user_agent or CLI_USER_AGENT,
    )
    return EsheriaRegulatoryClient(config)


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)


def _payload_for_output(result: EsheriaResult | dict[str, Any], args: argparse.Namespace) -> Any:
    if isinstance(result, EsheriaResult):
        if args.envelope:
            return result.envelope.model_dump(mode="json")
        if args.raw:
            return result.data
        payload = dict(result.data)
        payload.setdefault("trace_id", result.trace_id)
        return payload
    return result


def emit(
    result: EsheriaResult | dict[str, Any],
    args: argparse.Namespace,
    *,
    table: str | None = None,
) -> None:
    payload = _payload_for_output(result, args)
    output_format = getattr(args, "format", "table")
    if output_format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))
    elif output_format == "yaml":
        print(yaml.safe_dump(payload, sort_keys=False))
    elif output_format == "ndjson":
        if isinstance(payload, list):
            for item in payload:
                print(json.dumps(item, sort_keys=True, default=_json_default))
        elif isinstance(payload, dict):
            emitted = False
            for key in NDJSON_LIST_KEYS:
                items = payload.get(key)
                if isinstance(items, list):
                    for item in items:
                        print(json.dumps(item, sort_keys=True, default=_json_default))
                    emitted = True
                    break
            if not emitted:
                print(json.dumps(payload, sort_keys=True, default=_json_default))
        else:
            print(json.dumps(payload, sort_keys=True, default=_json_default))
    elif not getattr(args, "quiet", False):
        print(table if table is not None else json.dumps(payload, indent=2, sort_keys=True, default=_json_default))


def _table(rows: list[dict[str, Any]], columns: list[tuple[str, str]], *, empty: str = "No rows.") -> str:
    if not rows:
        return empty
    widths = {
        key: max(len(label), *(len(_cell(row.get(key))) for row in rows))
        for key, label in columns
    }
    lines = ["  ".join(label.ljust(widths[key]) for key, label in columns)]
    for row in rows:
        lines.append("  ".join(_cell(row.get(key)).ljust(widths[key]) for key, _label in columns))
    return "\n".join(lines)


def _cell(value: Any) -> str:
    if isinstance(value, list):
        value = ",".join(str(item) for item in value)
    if isinstance(value, dict):
        value = json.dumps(value, sort_keys=True)
    text = str(value if value is not None else "")
    return text if len(text) <= 80 else text[:77] + "..."


def _filters(args: argparse.Namespace, keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: getattr(args, key) for key in keys if hasattr(args, key) and getattr(args, key) not in (None, "", [])}


def _json_object(value: str, *, label: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return parsed


def _json_object_file(path: str, *, label: str) -> dict[str, Any]:
    return _json_object(Path(path).read_text(encoding="utf-8"), label=label)


def _profile(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "profile_file", None):
        data = _json_object_file(args.profile_file, label="Profile file")
    else:
        data = {}
    for key in ("entity_roles", "activities", "sector_tags", "processing_characteristics"):
        if not hasattr(args, key):
            continue
        cli_values = list(getattr(args, key) or [])
        if cli_values:
            existing = data.get(key) if isinstance(data.get(key), list) else []
            data[key] = list(dict.fromkeys([*existing, *cli_values]))
        else:
            data.setdefault(key, [])
    data["limit"] = getattr(args, "limit", data.get("limit", 100))
    return data


def _packs_table(result: EsheriaResult) -> str:
    rows = [
        {
            "pack_id": pack.get("domain_pack_id"),
            "jurisdiction": pack.get("jurisdiction"),
            "domain": pack.get("legal_domain"),
            "readiness": pack.get("readiness_label"),
            "published": pack.get("published_legal_status_count"),
        }
        for pack in result.data.get("packs", [])
    ]
    return _table(
        rows,
        [
            ("pack_id", "PACK ID"),
            ("jurisdiction", "JURISDICTION"),
            ("domain", "DOMAIN"),
            ("readiness", "READINESS"),
            ("published", "PUBLISHED"),
        ],
        empty="No packs found.",
    )


def _obligations_table(result: EsheriaResult) -> str:
    rows = []
    publication_mode = (result.data.get("domain_pack") or {}).get("publication_mode", "")
    for item in result.data.get("obligations", []):
        rows.append(
            {
                "semantic_obligation_id": item.get("semantic_obligation_id"),
                "duty_holders": item.get("duty_holders", []),
                "legal_action": item.get("plain_language_action") or item.get("legal_action"),
                "citation_count": len(item.get("citation_ids") or []),
                "publication_mode": publication_mode,
            }
        )
    return _table(
        rows,
        [
            ("semantic_obligation_id", "SEMANTIC OBLIGATION ID"),
            ("duty_holders", "DUTY HOLDERS"),
            ("legal_action", "LEGAL ACTION"),
            ("citation_count", "CITATIONS"),
            ("publication_mode", "MODE"),
        ],
        empty="No obligations found.",
    )


def cmd_health(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.health()
    trace = f" trace_id={result.trace_id}" if args.trace else ""
    emit(result, args, table=f"{result.status} {result.environment}{trace}".strip())
    return 0


def cmd_ready(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.ready()
    trace = f" trace_id={result.trace_id}" if args.trace else ""
    emit(result, args, table=f"{result.status}{trace}".strip())
    return 0 if result.status == "ready" else EXIT_NOT_READY


def cmd_doctor(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    report: dict[str, Any] = {"status": "ok", "config": client.config.redacted(), "checks": []}
    exit_code = 0
    if client.config.api_key:
        report["checks"].append({"name": "api_key", "status": "ok", "detail": "configured"})
    else:
        report["checks"].append({"name": "api_key", "status": "error", "detail": "ESHERIA_API_KEY is missing"})
        exit_code = EXIT_AUTH

    try:
        health = client.health()
        report["checks"].append({"name": "health", "status": health.status, "trace_id": health.trace_id})
    except (EsheriaApiError, EsheriaTransportError) as exc:
        report["checks"].append({"name": "health", "status": "error", "detail": str(exc)})
        exit_code = _exit_for_error(exc)

    try:
        ready = client.ready()
        report["checks"].append({"name": "ready", "status": ready.status, "trace_id": ready.trace_id})
        if ready.status != "ready" and exit_code in {0, EXIT_AUTH}:
            exit_code = EXIT_NOT_READY
    except (EsheriaApiError, EsheriaTransportError) as exc:
        report["checks"].append({"name": "ready", "status": "error", "detail": str(exc)})
        exit_code = _exit_for_error(exc)

    if args.pack:
        try:
            obligations = client.list_obligations(args.pack, {"limit": 1})
            total = (obligations.data.get("pagination") or {}).get("total", 0)
            report["checks"].append(
                {
                    "name": "obligations",
                    "status": "ok",
                    "pack_id": args.pack,
                    "total": total,
                    "trace_id": obligations.trace_id,
                }
            )
        except (EsheriaApiError, EsheriaTransportError) as exc:
            report["checks"].append(
                {"name": "obligations", "status": "error", "pack_id": args.pack, "detail": str(exc)}
            )
            exit_code = _exit_for_error(exc)
    report["status"] = "ok" if exit_code == 0 else "failed"
    emit(report, args)
    return exit_code


def cmd_packs_list(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_packs(
        _filters(args, ("jurisdiction", "legal_domain", "status", "readiness_label", "detail", "limit", "offset"))
    )
    emit(result, args, table=_packs_table(result))
    return 0


def cmd_packs_inspect(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.get_pack(args.pack_id)
    table = "\n".join(
        [
            f"PACK ID: {result.data.get('domain_pack_id')}",
            f"VERSION: {result.data.get('domain_pack_version')}",
            f"JURISDICTION: {result.data.get('jurisdiction')}",
            f"DOMAIN: {result.data.get('legal_domain')}",
            f"READINESS: {result.data.get('readiness_label')}",
            f"PUBLISHED LEGAL STATUS ROWS: {result.data.get('published_legal_status_count')}",
            f"LIMITATIONS: {'; '.join(result.data.get('limitations') or [])}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_packs_export(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.export_pack(
        args.pack_id,
        _filters(args, ("version", "include_all_forms")),
    )
    if args.out:
        Path(args.out).write_text(json.dumps(result.data, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
        emit({"status": "ok", "out": args.out, "trace_id": result.trace_id}, args)
    else:
        emit(result, args)
    return 0


def cmd_packs_versions(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_pack_versions(args.pack_id, _filters(args, ("limit", "offset")))
    rows = []
    for item in result.data.get("versions", []):
        fact_counts = item.get("fact_counts") or {}
        legal_status_counts = fact_counts.get("legal_status") if isinstance(fact_counts.get("legal_status"), dict) else {}
        rows.append(
            {
                "domain_pack_version": item.get("domain_pack_version"),
                "current": item.get("is_current"),
                "status": item.get("status"),
                "published": legal_status_counts.get("published", ""),
                "loaded_at": item.get("loaded_at"),
            }
        )
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("domain_pack_version", "VERSION"),
                ("current", "CURRENT"),
                ("status", "STATUS"),
                ("published", "PUBLISHED LEGAL STATUS"),
                ("loaded_at", "LOADED"),
            ],
            empty="No pack versions found.",
        ),
    )
    return 0


def cmd_packs_diff(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.diff_pack_versions(
        args.pack_id,
        _filters(args, ("from_version", "to_version", "publication_mode")),
    )
    summary = result.data.get("summary") or {}
    table = "\n".join(
        [
            f"PACK ID: {(result.data.get('domain_pack') or {}).get('domain_pack_id')}",
            f"FROM: {result.data.get('from_version')}",
            f"TO: {result.data.get('to_version')}",
            f"ADDED: {summary.get('added', 0)}",
            f"CHANGED: {summary.get('changed', 0)}",
            f"REMOVED: {summary.get('removed', 0)}",
            f"UNCHANGED: {summary.get('unchanged', 0)}",
            f"LIMITATIONS: {'; '.join(result.data.get('limitations') or [])}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_packs_change_events(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_change_events(
        args.pack_id,
        _filters(args, ("from_version", "to_version", "publication_mode", "limit", "offset")),
    )
    rows = [
        {
            "change_event_id": item.get("change_event_id"),
            "type": item.get("change_type"),
            "fact_type": item.get("fact_type"),
            "fact_id": item.get("fact_id"),
            "materiality": item.get("materiality"),
        }
        for item in result.data.get("change_events", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("change_event_id", "CHANGE EVENT ID"),
                ("type", "TYPE"),
                ("fact_type", "FACT TYPE"),
                ("fact_id", "FACT ID"),
                ("materiality", "MATERIALITY"),
            ],
            empty="No change events found.",
        ),
    )
    return 0


def cmd_obligations_list(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_obligations(
        args.pack_id,
        _filters(
            args,
            (
                "version",
                "query",
                "duty_holder",
                "workflow_target",
                "instrument_id",
                "evidence_type",
                "fact_class",
                "customer_actionability",
                "limit",
                "offset",
            ),
        ),
    )
    emit(result, args, table=_obligations_table(result))
    return 0


def cmd_applicability_check(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.check_applicability(args.pack_id, _profile(args))
    rows = [
        {
            "semantic_obligation_id": item.get("semantic_obligation_id"),
            "score": (item.get("applicability") or {}).get("score"),
            "reasons": (item.get("applicability") or {}).get("reasons", []),
            "duty_holders": item.get("duty_holders", []),
            "citation_count": len(item.get("citation_ids") or []),
        }
        for item in result.data.get("applicable_obligations", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("semantic_obligation_id", "SEMANTIC OBLIGATION ID"),
                ("score", "SCORE"),
                ("reasons", "REASONS"),
                ("duty_holders", "DUTY HOLDERS"),
                ("citation_count", "CITATIONS"),
            ],
            empty="No applicable obligations found.",
        ),
    )
    return 0


def cmd_claims_verify(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    jurisdiction = args.jurisdiction
    domain = args.domain
    if not jurisdiction or not domain:
        pack = client.get_pack(args.pack_id)
        jurisdiction = jurisdiction or pack.data.get("jurisdiction")
        domain = domain or pack.data.get("legal_domain")
    if not jurisdiction:
        raise ValueError(f"Pack `{args.pack_id}` does not declare a jurisdiction; pass --jurisdiction explicitly")
    if not domain:
        raise ValueError(f"Pack `{args.pack_id}` does not declare a legal domain; pass --domain explicitly")
    result = client.verify_claim(
        {
            "pack_id": args.pack_id,
            "claim": args.claim,
            "jurisdiction": jurisdiction,
            "domain": domain,
            "limit": args.limit,
        }
    )
    table = "\n".join(
        [
            f"STATUS: {result.data.get('status')}",
            f"ISSUES: {', '.join(result.data.get('issue_labels') or [])}",
            f"CITATIONS: {', '.join(result.data.get('citation_ids') or [])}",
            f"TRACE ID: {result.trace_id}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_workspace_show(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.get_workspace()
    workspace = result.data.get("workspace") or {}
    table = "\n".join(
        [
            f"WORKSPACE: {workspace.get('workspace_id')}",
            f"NAME: {workspace.get('display_name')}",
            f"STATUS: {workspace.get('status')}",
            f"BILLING CONTACT: {workspace.get('billing_contact_email') or ''}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_workspace_update(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    payload: dict[str, Any] = {"display_name": args.display_name}
    if args.billing_contact_email is not None:
        payload["billing_contact_email"] = args.billing_contact_email
    if args.metadata_json:
        payload["metadata"] = _json_object(args.metadata_json, label="Workspace metadata")
    result = client.update_workspace(payload)
    workspace = result.data.get("workspace") or {}
    emit(result, args, table=f"WORKSPACE: {workspace.get('workspace_id')}\nNAME: {workspace.get('display_name')}")
    return 0


def cmd_tokens_list(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_tokens(_filters(args, ("status", "token_type", "limit", "offset")))
    rows = [
        {
            "token_id": item.get("token_id"),
            "name": item.get("name"),
            "prefix": item.get("token_prefix"),
            "type": item.get("token_type"),
            "status": item.get("status"),
            "scopes": item.get("scopes", []),
            "packs": item.get("pack_entitlements", []),
            "last_used_at": item.get("last_used_at"),
        }
        for item in result.data.get("tokens", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("token_id", "TOKEN ID"),
                ("name", "NAME"),
                ("prefix", "PREFIX"),
                ("type", "TYPE"),
                ("status", "STATUS"),
                ("scopes", "SCOPES"),
                ("packs", "PACKS"),
                ("last_used_at", "LAST USED"),
            ],
            empty="No API tokens found.",
        ),
    )
    return 0


def cmd_tokens_create(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    metadata = _json_object(args.metadata_json, label="Token metadata") if args.metadata_json else {}
    payload = {
        "name": args.name,
        "metadata": metadata,
    }
    if args.scopes:
        payload["scopes"] = args.scopes
    if args.pack_entitlements:
        payload["pack_entitlements"] = args.pack_entitlements
    if args.expires_at:
        payload["expires_at"] = args.expires_at
    result = client.create_token(payload)
    table = "\n".join(
        [
            f"TOKEN ID: {result.data.get('token_id')}",
            f"PREFIX: {result.data.get('token_prefix')}",
            f"TYPE: {result.data.get('token_type')}",
            f"STATUS: {result.data.get('status')}",
            f"API TOKEN: {result.data.get('api_token')}",
            str(result.data.get("token_secret_note") or ""),
        ]
    ).strip()
    emit(result, args, table=table)
    return 0


def cmd_tokens_revoke(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.revoke_token(args.token_id)
    token = result.data.get("token") or {}
    emit(
        result,
        args,
        table=f"{token.get('status', 'revoked')} {token.get('token_id', args.token_id)}".strip(),
    )
    return 0


def cmd_billing_balance(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.billing_balance()
    table = "\n".join(
        [
            f"WORKSPACE: {result.data.get('workspace_id')}",
            f"AVAILABLE CREDITS: {result.data.get('available_credits')}",
            f"FREE CREDITS GRANTED: {result.data.get('free_credits_granted')}/{result.data.get('free_credit_cap')}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_billing_usage(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.billing_usage(
        _filters(args, ("token_id", "endpoint_family", "pack_id", "date_from", "date_to", "limit", "offset"))
    )
    rows = [
        {
            "created_at": item.get("created_at"),
            "endpoint_family": item.get("endpoint_family"),
            "pack_id": item.get("pack_id"),
            "status_code": item.get("status_code"),
            "credits": item.get("charged_credits"),
            "billing_status": item.get("billing_status"),
            "trace_id": item.get("trace_id"),
        }
        for item in result.data.get("usage", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("created_at", "CREATED"),
                ("endpoint_family", "ENDPOINT"),
                ("pack_id", "PACK"),
                ("status_code", "HTTP"),
                ("credits", "CREDITS"),
                ("billing_status", "BILLING"),
                ("trace_id", "TRACE ID"),
            ],
            empty="No usage events found.",
        ),
    )
    return 0


def cmd_billing_plans(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.billing_plans()
    rows = [
        {
            "sku_id": item.get("sku_id"),
            "name": item.get("name"),
            "credits": item.get("credits"),
            "price": item.get("price"),
            "checkout_type": item.get("checkout_type"),
            "billing_period": item.get("billing_period"),
        }
        for item in result.data.get("skus", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("sku_id", "SKU"),
                ("name", "NAME"),
                ("credits", "CREDITS"),
                ("price", "PRICE"),
                ("checkout_type", "TYPE"),
                ("billing_period", "PERIOD"),
            ],
            empty="No billing plans found.",
        ),
    )
    return 0


def cmd_billing_topup(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    sku_id = (args.sku_id or "").strip()
    if not sku_id and args.credits:
        catalog = client.billing_plans()
        matches = [
            item
            for item in catalog.data.get("skus", [])
            if int(item.get("credits") or 0) == int(args.credits)
            and str(item.get("checkout_type") or "") == ("subscription" if args.subscription else "topup")
            and (not args.plan_id or str(item.get("plan_id") or "") == args.plan_id)
        ]
        if len(matches) == 1:
            sku_id = str(matches[0].get("sku_id") or "")
        else:
            raise ValueError("Deprecated --credits selection did not resolve to one available SKU; use --sku-id from `esheria billing plans`.")
    if not sku_id:
        raise ValueError("billing checkout requires --sku-id from `esheria billing plans`.")
    result = client.create_billing_checkout_session(sku_id=sku_id)
    table = "\n".join(
        [
            f"CHECKOUT SESSION: {result.data.get('checkout_session_id')}",
            f"TYPE: {result.data.get('checkout_type')}",
            f"SKU: {((result.data.get('sku') or {}).get('sku_id') if isinstance(result.data.get('sku'), dict) else sku_id)}",
            f"URL: {result.data.get('url')}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_billing_subscription(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.billing_subscription()
    subscription = result.data.get("subscription") or {}
    table = "\n".join(
        [
            f"STATUS: {subscription.get('status') or 'none'}",
            f"PLAN: {subscription.get('plan_id') or ''}",
            f"CURRENT PERIOD END: {subscription.get('current_period_end') or ''}",
            f"CANCEL AT PERIOD END: {subscription.get('cancel_at_period_end') or False}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_billing_cancel_subscription(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    if not args.yes:
        raise ValueError("Subscription cancellation requires --yes")
    result = client.cancel_billing_subscription(cancel_at_period_end=args.at_period_end)
    subscription = result.data.get("subscription") or {}
    emit(
        result,
        args,
        table=f"STATUS: {subscription.get('status')}\nCANCEL AT PERIOD END: {subscription.get('cancel_at_period_end')}",
    )
    return 0


def cmd_calendar_list(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.get_filing_calendar(
        args.pack_id,
        _filters(args, ("version", "duty_holder", "workflow_target", "instrument_id", "limit")),
    )
    rows = [
        {
            "title": item.get("title"),
            "deadline": item.get("relative_deadline"),
            "duty_holders": (item.get("obligation") or {}).get("duty_holders", []),
            "forms": [form.get("form_id") for form in item.get("forms", [])],
            "citation_count": len(item.get("citations") or []),
        }
        for item in result.data.get("calendar_items", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("title", "TITLE"),
                ("deadline", "RELATIVE DEADLINE"),
                ("duty_holders", "DUTY HOLDERS"),
                ("forms", "FORMS"),
                ("citation_count", "CITATIONS"),
            ],
            empty="No calendar items found.",
        ),
    )
    return 0


def cmd_evidence_list(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.get_evidence_register(
        args.pack_id,
        _filters(args, ("version", "duty_holder", "workflow_target", "instrument_id")),
    )
    rows = [
        {
            "evidence_type": item.get("evidence_type"),
            "obligation_count": len(item.get("obligations") or []),
            "sample_obligation_ids": [ob.get("semantic_obligation_id") for ob in (item.get("obligations") or [])[:3]],
            "citation_count": len(item.get("citation_ids") or []),
        }
        for item in result.data.get("evidence_register", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("evidence_type", "EVIDENCE TYPE"),
                ("obligation_count", "OBLIGATIONS"),
                ("sample_obligation_ids", "SAMPLE OBLIGATIONS"),
                ("citation_count", "CITATIONS"),
            ],
            empty="No evidence requirements found.",
        ),
    )
    return 0


def cmd_penalties_list(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.get_penalty_facts(
        args.pack_id,
        _filters(
            args,
            (
                "version",
                "query",
                "regulator_or_enforcer",
                "consequence_type",
                "linked_obligation_id",
                "linked_provision_id",
                "limit",
                "offset",
            ),
        ),
    )
    rows = [
        {
            "penalty_fact_id": item.get("penalty_fact_id"),
            "consequence_type": item.get("consequence_type"),
            "regulator": item.get("regulator_or_enforcer"),
            "amount": item.get("amount_or_range", []),
            "citation_count": len(item.get("citation_ids") or []),
        }
        for item in result.data.get("penalty_facts", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("penalty_fact_id", "PENALTY FACT ID"),
                ("consequence_type", "CONSEQUENCE"),
                ("regulator", "REGULATOR"),
                ("amount", "AMOUNT/RANGE"),
                ("citation_count", "CITATIONS"),
            ],
            empty="No penalty facts found.",
        ),
    )
    return 0


def cmd_legal_review_audit(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.get_legal_review_audit(
        args.pack_id,
        _filters(
            args,
            (
                "version",
                "query",
                "review_decision",
                "promotion_state",
                "promotion_tier",
                "fact_class",
                "customer_actionability",
                "duty_holder_type",
                "audience_type",
                "operability_class",
                "qa_status",
                "limit",
                "offset",
            ),
        ),
    )
    rows = []
    for item in result.data.get("legal_review_items", []):
        review = item.get("review") or {}
        primitive = item.get("primitive") or {}
        rows.append(
            {
                "semantic_obligation_id": item.get("semantic_obligation_id"),
                "decision": review.get("review_decision"),
                "qa_status": item.get("qa_status"),
                "fact_class": item.get("fact_class"),
                "action": primitive.get("plain_language_action") or primitive.get("legal_action"),
            }
        )
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("semantic_obligation_id", "SEMANTIC OBLIGATION ID"),
                ("decision", "DECISION"),
                ("qa_status", "QA"),
                ("fact_class", "FACT CLASS"),
                ("action", "ACTION"),
            ],
            empty="No legal review audit rows found.",
        ),
    )
    return 0


def cmd_citations_get(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.get_citation_context(args.pack_id, args.citation_id)
    citation = result.data.get("citation") or {}
    table = "\n".join(
        [
            f"CITATION ID: {citation.get('citation_id')}",
            f"INSTRUMENT: {citation.get('instrument_id')}",
            f"PROVISION: {citation.get('provision_id')}",
            f"QUOTE: {citation.get('quote')}",
            f"SOURCE URL: {citation.get('source_url')}",
            f"LINES: {citation.get('line_start')}..{citation.get('line_end')}",
            f"CHARS: {citation.get('char_start')}..{citation.get('char_end')}",
            f"VERIFY: {citation.get('verification_status')}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_relationships_list(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_relationships(
        args.pack_id,
        _filters(
            args,
            ("version", "relationship_type", "source_pack_id", "target_pack_id", "evidence_basis", "query", "limit", "offset"),
        ),
    )
    emit(result, args, table=_relationships_table(result))
    return 0


def _relationships_table(result: EsheriaResult) -> str:
    rows = [
        {
            "relationship_id": item.get("relationship_id"),
            "type": item.get("relationship_type"),
            "source": item.get("source_pack_id"),
            "target": item.get("target_pack_id"),
            "evidence_basis": item.get("evidence_basis"),
            "citation_count": len(item.get("citation_ids") or []),
        }
        for item in result.data.get("relationships", [])
    ]
    return _table(
        rows,
        [
            ("relationship_id", "RELATIONSHIP ID"),
            ("type", "TYPE"),
            ("source", "SOURCE PACK"),
            ("target", "TARGET PACK"),
            ("evidence_basis", "EVIDENCE"),
            ("citation_count", "CITATIONS"),
        ],
        empty="No relationships found.",
    )


def _graph_request(args: argparse.Namespace) -> dict[str, Any]:
    payload = _filters(
        args,
        ("pack_ids", "relationship_types", "source_pack_id", "target_pack_id", "evidence_basis", "query", "limit", "offset"),
    )
    return payload


def cmd_graph_query(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.query_graph(_graph_request(args))
    emit(result, args, table=_relationships_table(result))
    return 0


def cmd_graph_applicability(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    payload = _profile(args)
    payload["pack_ids"] = args.pack_ids
    result = client.check_graph_applicability(payload)
    emit(result, args)
    return 0


def cmd_graph_entity_profile(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    payload = _profile(args)
    payload["pack_ids"] = args.pack_ids
    result = client.get_entity_profile(payload)
    emit(result, args)
    return 0


def cmd_graph_rebuild_projection(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    if not args.yes:
        raise ValueError("Graph projection rebuild requires --yes")
    metadata = _json_object(args.metadata_json, label="Projection metadata") if args.metadata_json else {}
    result = client.rebuild_graph_projection(
        {"reason": args.reason, "requested_by": args.requested_by, "metadata": metadata}
    )
    run = result.data.get("projection_run") or {}
    table = "\n".join(
        [
            f"PROJECTION RUN: {run.get('projection_run_id')}",
            f"STATUS: {run.get('status')}",
            f"NODES: {run.get('node_count')}",
            f"EDGES: {run.get('edge_count')}",
            f"EXCLUDED DRAFT/BLOCKED: {run.get('blocked_draft_excluded_count')}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_graph_coverage(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.get_graph_coverage(_filters(args, ("domain_pack_id", "limit", "offset")))
    rows = [
        {
            "pack": item.get("domain_pack_id"),
            "version": item.get("domain_pack_version"),
            "published": item.get("published_fact_count"),
            "nodes": item.get("graph_node_count"),
            "missing": item.get("missing_node_count"),
            "excluded": item.get("blocked_draft_excluded_count"),
            "status": item.get("status"),
        }
        for item in result.data.get("coverage_reports", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("pack", "PACK"),
                ("version", "VERSION"),
                ("published", "PUBLISHED"),
                ("nodes", "NODES"),
                ("missing", "MISSING"),
                ("excluded", "EXCLUDED"),
                ("status", "STATUS"),
            ],
            empty="No graph coverage reports found.",
        ),
    )
    return 0


def cmd_monitoring_watches(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_source_watches(
        _filters(args, ("domain_pack_id", "status", "source_kind", "authority_type", "limit", "offset"))
    )
    rows = [
        {
            "watch": item.get("source_watch_id"),
            "pack": item.get("domain_pack_id"),
            "source": item.get("source_asset_id") or item.get("source_uri"),
            "kind": item.get("source_kind"),
            "authority": item.get("authority_type"),
            "status": item.get("status"),
        }
        for item in result.data.get("source_watches", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("watch", "WATCH"),
                ("pack", "PACK"),
                ("source", "SOURCE"),
                ("kind", "KIND"),
                ("authority", "AUTHORITY"),
                ("status", "STATUS"),
            ],
            empty="No source watches found.",
        ),
    )
    return 0


def cmd_monitoring_create_watch(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    payload = _filters(
        args,
        (
            "domain_pack_id",
            "source_asset_id",
            "source_uri",
            "source_kind",
            "authority_type",
            "expected_hash_sha256",
            "expected_etag",
            "expected_last_modified",
            "check_interval_seconds",
            "status",
        ),
    )
    payload["metadata"] = _json_object(args.metadata_json, label="Source-watch metadata") if args.metadata_json else {}
    result = client.create_source_watch(payload)
    watch = result.data.get("source_watch") or {}
    emit(result, args, table=f"WATCH: {watch.get('source_watch_id')}\nSTATUS: {watch.get('status')}")
    return 0


def cmd_monitoring_currentness(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.get_source_currentness(_filters(args, ("domain_pack_id", "limit", "offset")))
    rows = [
        {
            "pack": item.get("domain_pack_id"),
            "source": item.get("source_asset_id") or item.get("source_uri"),
            "kind": item.get("source_kind"),
            "currentness": item.get("currentness_status"),
            "change": item.get("latest_change_type"),
            "candidate": item.get("recompile_candidate_id"),
        }
        for item in result.data.get("source_currentness", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("pack", "PACK"),
                ("source", "SOURCE"),
                ("kind", "KIND"),
                ("currentness", "CURRENTNESS"),
                ("change", "CHANGE"),
                ("candidate", "RECOMPILE"),
            ],
            empty="No source currentness rows found.",
        ),
    )
    return 0


def cmd_monitoring_check(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    if not args.yes:
        raise ValueError("Source-watch checks require --yes")
    result = client.check_source_watches(
        _filters(args, ("domain_pack_id", "status", "source_kind", "authority_type", "limit", "offset"))
    )
    summary = result.data.get("summary") or {}
    table = "\n".join(f"{key.upper()}: {value}" for key, value in summary.items())
    emit(result, args, table=table)
    return 0


def cmd_monitoring_changes(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_source_change_events(
        _filters(args, ("domain_pack_id", "source_kind", "authority_type", "change_type", "limit", "offset"))
    )
    rows = [
        {
            "event": item.get("source_change_event_id"),
            "pack": item.get("domain_pack_id"),
            "source": item.get("source_asset_id"),
            "type": item.get("change_type"),
            "binding": item.get("binding_authority"),
        }
        for item in result.data.get("source_change_events", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("event", "EVENT"),
                ("pack", "PACK"),
                ("source", "SOURCE"),
                ("type", "TYPE"),
                ("binding", "BINDING"),
            ],
            empty="No source-change events found.",
        ),
    )
    return 0


def cmd_monitoring_recompile_candidates(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_recompile_candidates(
        _filters(args, ("domain_pack_id", "status", "candidate_type", "priority", "limit", "offset"))
    )
    rows = [
        {
            "candidate": item.get("recompile_candidate_id"),
            "pack": item.get("domain_pack_id"),
            "source": item.get("source_asset_id"),
            "priority": item.get("priority"),
            "status": item.get("status"),
            "reason": item.get("reason"),
        }
        for item in result.data.get("recompile_candidates", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("candidate", "CANDIDATE"),
                ("pack", "PACK"),
                ("source", "SOURCE"),
                ("priority", "PRIORITY"),
                ("status", "STATUS"),
                ("reason", "REASON"),
            ],
            empty="No recompile candidates found.",
        ),
    )
    return 0


def cmd_customers_profiles(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_customer_profiles(_filters(args, ("status", "limit", "offset")))
    rows = [
        {
            "profile": item.get("customer_profile_id"),
            "name": item.get("profile_name"),
            "packs": item.get("default_pack_ids", []),
            "status": item.get("status"),
        }
        for item in result.data.get("customer_profiles", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [("profile", "PROFILE"), ("name", "NAME"), ("packs", "PACKS"), ("status", "STATUS")],
            empty="No customer profiles found.",
        ),
    )
    return 0


def cmd_customers_inspect_profile(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.get_customer_profile(args.customer_profile_id)
    profile = result.data.get("customer_profile") or {}
    table = "\n".join(
        [
            f"PROFILE: {profile.get('customer_profile_id')}",
            f"NAME: {profile.get('profile_name')}",
            f"STATUS: {profile.get('status')}",
            f"PACKS: {', '.join(profile.get('default_pack_ids') or [])}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_customers_preview(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    payload = _profile(args)
    payload["pack_ids"] = args.pack_ids
    payload["include_change_impacts"] = not args.no_change_impacts
    if args.from_version:
        payload["from_version"] = args.from_version
    if args.to_version:
        payload["to_version"] = args.to_version
    result = client.preview_customer_lifecycle(payload)
    table = "\n".join(
        [
            "MODE: stateless_preview",
            f"WRITES: {str((result.data.get('persistence') or {}).get('writes_performed')).lower()}",
            f"OBLIGATION PREVIEWS: {result.data.get('total_obligation_previews', 0)}",
            f"IMPACT PREVIEWS: {result.data.get('total_impact_previews', 0)}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_customers_create_profile(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    payload = _json_object_file(args.profile_file, label="Customer profile file") if args.profile_file else {}
    payload["profile_name"] = args.profile_name
    if args.default_pack_ids:
        payload["default_pack_ids"] = args.default_pack_ids
    result = client.create_customer_profile(payload)
    profile = result.data.get("customer_profile") or {}
    emit(result, args, table=f"PROFILE: {profile.get('customer_profile_id')}")
    return 0


def cmd_customers_run_applicability(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    payload = _json_object_file(args.profile_file, label="Customer applicability file") if args.profile_file else {}
    payload["pack_ids"] = args.pack_ids
    payload["limit"] = args.limit
    result = client.run_customer_applicability(args.customer_profile_id, payload)
    run = result.data.get("applicability_run") or {}
    table = "\n".join(
        [
            f"RUN: {run.get('applicability_run_id')}",
            f"PACKS: {', '.join(run.get('pack_ids') or [])}",
            f"INSTANCES: {len(result.data.get('customer_obligation_instances') or [])}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_customers_applicability_runs(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_customer_applicability_runs(
        args.customer_profile_id,
        _filters(args, ("limit", "offset")),
    )
    rows = [
        {
            "run": item.get("applicability_run_id"),
            "packs": item.get("pack_ids", []),
            "status": item.get("status"),
            "created_at": item.get("created_at"),
        }
        for item in result.data.get("applicability_runs", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [("run", "RUN"), ("packs", "PACKS"), ("status", "STATUS"), ("created_at", "CREATED")],
            empty="No applicability runs found.",
        ),
    )
    return 0


def cmd_customers_obligations(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_customer_obligation_instances(
        _filters(args, ("customer_profile_id", "domain_pack_id", "status", "applicability_status", "limit", "offset"))
    )
    rows = [
        {
            "instance": item.get("customer_obligation_instance_id"),
            "pack": item.get("domain_pack_id"),
            "version": item.get("domain_pack_version"),
            "fact": item.get("published_fact_id"),
            "status": item.get("status"),
            "applicability": item.get("applicability_status"),
        }
        for item in result.data.get("customer_obligation_instances", [])
    ]
    emit(
        result,
        args,
        table=_table(
            rows,
            [
                ("instance", "INSTANCE"),
                ("pack", "PACK"),
                ("version", "VERSION"),
                ("fact", "PUBLISHED FACT"),
                ("status", "STATUS"),
                ("applicability", "APPLICABILITY"),
            ],
            empty="No customer obligation instances found.",
        ),
    )
    return 0


def cmd_customers_update_obligation(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    payload = _filters(
        args,
        (
            "status",
            "owner_user_id",
            "owner_label",
            "due_date",
            "priority",
            "status_reason",
            "status_updated_by",
        ),
    )
    if args.metadata_json:
        payload["lifecycle_metadata"] = _json_object(args.metadata_json, label="Obligation lifecycle metadata")
    if not payload:
        raise ValueError("At least one obligation update field is required")
    result = client.update_customer_obligation_instance(args.customer_obligation_instance_id, payload)
    instance = result.data.get("customer_obligation_instance") or {}
    table = "\n".join(
        [
            f"INSTANCE: {instance.get('customer_obligation_instance_id')}",
            f"STATUS: {instance.get('status')}",
            f"OWNER: {instance.get('owner_label') or instance.get('owner_user_id')}",
            f"PRIORITY: {instance.get('priority')}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_customers_impacts(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.list_customer_change_impacts(
        _filters(args, ("customer_profile_id", "domain_pack_id", "status", "impact_type", "materiality", "limit", "offset"))
    )
    emit(result, args)
    return 0


def cmd_customers_recompute_impacts(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    result = client.recompute_customer_change_impacts(
        _filters(args, ("customer_profile_id", "domain_pack_id", "from_version", "to_version", "limit"))
    )
    emit(result, args, table=f"IMPACTS: {result.data.get('total', 0)}")
    return 0


def cmd_customers_update_impact(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    payload = _filters(args, ("status", "status_reason", "status_updated_by"))
    if args.resolution_json:
        payload["resolution_payload"] = _json_object(args.resolution_json, label="Impact resolution payload")
    result = client.update_customer_change_impact(args.customer_change_impact_id, payload)
    impact = result.data.get("customer_change_impact") or {}
    table = "\n".join(
        [
            f"IMPACT: {impact.get('customer_change_impact_id')}",
            f"STATUS: {impact.get('status')}",
            f"REASON: {impact.get('status_reason')}",
        ]
    )
    emit(result, args, table=table)
    return 0


def cmd_smoke(args: argparse.Namespace, client: EsheriaRegulatoryClient) -> int:
    checks: list[dict[str, Any]] = []
    exit_code = 0
    health = client.health()
    checks.append({"name": "health", "status": health.status, "trace_id": health.trace_id})
    ready = client.ready()
    checks.append({"name": "ready", "status": ready.status, "trace_id": ready.trace_id})
    if ready.status != "ready":
        exit_code = EXIT_NOT_READY
    pack = client.get_pack(args.pack)
    published = int(pack.data.get("published_legal_status_count") or 0)
    checks.append({"name": "pack", "status": "ok", "published_legal_status_count": published, "trace_id": pack.trace_id})
    if args.expected_published_rows is not None and published != args.expected_published_rows:
        checks[-1]["status"] = "failed"
        checks[-1]["expected_published_rows"] = args.expected_published_rows
        exit_code = EXIT_API_ERROR
    obligations = client.list_obligations(args.pack, {"limit": 1})
    checks.append({"name": "obligations", "status": "ok", "trace_id": obligations.trace_id})
    applicability = client.check_applicability(args.pack, {"limit": 1})
    checks.append({"name": "applicability", "status": "ok", "trace_id": applicability.trace_id})
    calendar = client.get_filing_calendar(args.pack, {"limit": 1})
    checks.append({"name": "calendar", "status": "ok", "trace_id": calendar.trace_id})
    evidence = client.get_evidence_register(args.pack)
    checks.append({"name": "evidence", "status": "ok", "trace_id": evidence.trace_id})
    versions = client.list_pack_versions(args.pack, {"limit": 2})
    checks.append({"name": "versions", "status": "ok", "trace_id": versions.trace_id})
    diff = client.diff_pack_versions(args.pack)
    checks.append({"name": "diff", "status": "ok", "trace_id": diff.trace_id})
    change_events = client.list_change_events(args.pack, {"limit": 1})
    checks.append({"name": "change_events", "status": "ok", "trace_id": change_events.trace_id})
    penalties = client.get_penalty_facts(args.pack, {"limit": 1})
    checks.append({"name": "penalty_facts", "status": "ok", "trace_id": penalties.trace_id})
    legal_review = client.get_legal_review_audit(args.pack, {"limit": 1})
    checks.append({"name": "legal_review_audit", "status": "ok", "trace_id": legal_review.trace_id})
    exported = client.export_pack(args.pack)
    checks.append({"name": "export", "status": "ok", "trace_id": exported.trace_id})
    try:
        client.list_obligations(args.pack, {"publication_mode": "draft", "limit": 1})
        checks.append({"name": "draft_block", "status": "not_blocked"})
        exit_code = EXIT_API_ERROR
    except EsheriaApiError as exc:
        checks.append({"name": "draft_block", "status": "ok", "error_code": exc.error_code, "trace_id": exc.trace_id})
    emit({"status": "ok" if exit_code == 0 else "failed", "pack_id": args.pack, "checks": checks}, args)
    return exit_code


def cmd_mcp_serve(args: argparse.Namespace, _client: EsheriaRegulatoryClient | None = None) -> int:
    from api.mcp.esheria_mcp.server import main as mcp_main

    forwarded = ["serve"]
    forwarded.append("--http" if args.http else "--stdio")
    for name in ("host", "port", "path", "base_url", "api_key", "timeout", "retry_count"):
        value = getattr(args, name, None)
        if value is None or value == "":
            continue
        forwarded.extend([f"--{name.replace('_', '-')}", str(value)])
    return int(mcp_main(forwarded))


def _exit_for_error(exc: Exception) -> int:
    if isinstance(exc, (EsheriaAuthenticationError, EsheriaAuthorizationError)):
        return EXIT_AUTH
    if isinstance(exc, (EsheriaTimeoutError, EsheriaTransportError)):
        return EXIT_NETWORK
    return EXIT_API_ERROR


def main(
    argv: list[str] | None = None,
    *,
    client_factory: Any = client_from_args,
    stdout: Any = None,
    stderr: Any = None,
) -> int:
    out_stream = stdout or sys.stdout
    err_stream = stderr or sys.stderr
    with contextlib.redirect_stdout(out_stream), contextlib.redirect_stderr(err_stream):
        parser = build_parser()
        args = parser.parse_args(argv)
        if getattr(args, "raw", False) and getattr(args, "envelope", False):
            parser.error("--raw and --envelope cannot be used together")
        try:
            if not getattr(args, "requires_client", True):
                return int(args.func(args, None))
            with client_factory(args) as client:
                return int(args.func(args, client))
        except EsheriaApiError as exc:
            print(str(exc), file=sys.stderr)
            return _exit_for_error(exc)
        except EsheriaTransportError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_NETWORK
        except BrokenPipeError:
            return 0
        except KeyboardInterrupt:
            print("Interrupted.", file=sys.stderr)
            return 130
        except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_USAGE
