# Esheria Regulatory Pack API

Production FastAPI service for serving citation-backed regulatory packs from the Esheria regulatory corpus.

## Production Surface

The API exposes the refined regulatory pack workflows:

- verify a legal claim against published regulatory facts
- list published obligations
- check applicability for an entity profile
- produce filing-calendar items
- produce an evidence register
- expose source-backed penalty/consequence facts
- expose legal review and publication audit metadata
- inspect pack version history, deterministic diffs, and change events
- monitor regulatory source currentness and source-change events
- rebuild and inspect cross-pack regulatory graph projection coverage
- persist workspace-scoped customer profiles, applicability runs, obligation
  instances, and customer change impacts
- export the published regulatory pack

The sanitized discovery release generated on July 15, 2026 contains 69 current pack records across 27 jurisdiction labels: 60 `verified_published` packs and 9 metadata-only `not_ready` records. Catalog version: `2026-07-15-v1+sha256:c5732893a6156d077166b60ea5016166ac5b178bb024162320d3a54e0ce745eb`. Query `GET /api/v1/domain-packs` for live discovery and treat the authenticated response as authoritative.

The route surface is pack-oriented. In DB mode, `{pack_id}` is resolved against
`regulatory_serving.domain_packs` and `regulatory_serving.facts`, so the same
obligation, applicability, filing-calendar, evidence-register, penalty-fact,
legal-review-audit, relationship, and export workflows serve any published pack
loaded into the serving schema.

Claim verification is intentionally evaluator-gated. Evaluators are supplied by
an enabled pack `claim_evaluation_profile`; Kenya data protection and BRS
corporate registry both use the generic profile-backed evaluator. Packs without
a registered evaluator return
`unsupported_capability` for `verify-claim` while the other pack workflows
remain available.

## Serving Architecture

```text
canonical regulatory documents on Seaweed S3
-> deterministic extraction and normalization
-> citation verification and publication gates
-> PostgreSQL regulatory_serving.domain_packs + regulatory_serving.facts
-> FastAPI Regulatory Pack API
```

Request handlers serve from Postgres. Seaweed S3 remains the canonical artifact store and publication target.

Production mode serves only the `published` tier.

Default data and OAuth connector tokens are read-only (`regulatory:read`).
Hosted source-monitoring changes require `monitoring:write`, graph projection
rebuilds require `graph:write`, and persisted customer lifecycle changes
require `customer:write`. Management-token holders can mint scoped operator
data tokens; `regulatory:read` alone cannot authorize those mutations.

Controlled legal QA is documented in `api/docs/AUTONOMOUS_LEGAL_QA_REVIEW.md`.
The current local stage is a deterministic review harness, not live LLM legal
review. New local decisions must disclose `reviewer_type=deterministic_harness`,
`llm_inference_enabled=false`, `not_human_counsel=true`, and
`not_legal_advice=true`. Opt-in live Hermes legal review is available only when
a remote Hermes endpoint is configured; live rows disclose
`reviewer_type=ai_agent`, `llm_inference_enabled=true`, and reviewer/verifier
pass flags, then still pass through deterministic hard gates.

The reusable pack factory is documented in
`api/docs/GENERIC_REGULATORY_PACK_PIPELINE.md`. For a senior-engineer
end-to-end explanation of source intake, canonicalization, Kanon/ILGS
enrichment, ontology normalization, legal QA, publication, Postgres serving
load, and API exposure, read
`api/docs/REGULATORY_INTELLIGENCE_PIPELINE_DEEP_DIVE.md`. New regulatory packs
should add config and artifacts under
`regulatory_data_model/domain_packs/<PACK_ID>/`; they should not add
pack-specific builders, publishers, loaders, routes, or claim-evaluator code
paths.

## Runtime Design

- App entrypoint: `api/app.py`
- Public route surface: `api/routes.py`
- Regulatory pack service: `api/services/domain_pack.py`
- Regulatory intelligence service: `api/services/regulatory_intelligence.py`
- Regulatory serving repository: `api/repositories.py`
- Billing, credit-ledger, Checkout, and Stripe repository: `api/billing_repository.py`
- Serving schema migration: `api/migrations/003_regulatory_serving.sql`
- Regulatory intelligence migration:
  `api/migrations/008_regulatory_intelligence_capabilities.sql`
- Runtime middleware: auth, idempotency, rate limit, payload limits, correlation ID, logs, metrics

## Public Endpoints

```text
GET  /healthz
GET  /readyz
GET  /metrics
POST /api/v1/legal-status/verify-claim
GET  /api/v1/domain-packs
GET  /api/v1/domain-packs/{pack_id}
GET  /api/v1/domain-packs/{pack_id}/versions
GET  /api/v1/domain-packs/{pack_id}/diff
GET  /api/v1/domain-packs/{pack_id}/change-events
GET  /api/v1/domain-packs/{pack_id}/obligations
POST /api/v1/domain-packs/{pack_id}/applicability-check
GET  /api/v1/domain-packs/{pack_id}/filing-calendar
GET  /api/v1/domain-packs/{pack_id}/evidence-register
GET  /api/v1/domain-packs/{pack_id}/penalty-facts
GET  /api/v1/domain-packs/{pack_id}/legal-review-audit
GET  /api/v1/domain-packs/{pack_id}/relationships
GET  /api/v1/domain-packs/{pack_id}/export
POST /api/v1/regulatory-graph/query
POST /api/v1/regulatory-graph/applicability-check
GET  /api/v1/regulatory-graph/entity-profile
POST /api/v1/regulatory-graph/projections/rebuild
GET  /api/v1/regulatory-graph/coverage
POST /api/v1/regulatory-monitoring/source-watches
GET  /api/v1/regulatory-monitoring/source-watches
GET  /api/v1/regulatory-monitoring/source-currentness
POST /api/v1/regulatory-monitoring/source-watches/check
GET  /api/v1/regulatory-monitoring/source-change-events
GET  /api/v1/regulatory-monitoring/recompile-candidates
POST /api/v1/customer-lifecycle/preview
POST /api/v1/customer-profiles
GET  /api/v1/customer-profiles
GET  /api/v1/customer-profiles/{customer_profile_id}
POST /api/v1/customer-profiles/{customer_profile_id}/applicability-runs
GET  /api/v1/customer-profiles/{customer_profile_id}/applicability-runs
GET  /api/v1/customer-obligation-instances
POST /api/v1/customer-change-impacts/recompute
GET  /api/v1/customer-change-impacts
GET  /api/v1/workspace
PATCH /api/v1/workspace
POST /api/v1/tokens
GET  /api/v1/tokens
POST /api/v1/tokens/{token_id}/revoke
GET  /api/v1/billing/balance
GET  /api/v1/billing/usage
GET  /api/v1/billing/plans
POST /api/v1/billing/topups/checkout-session
GET  /api/v1/billing/subscription
POST /api/v1/billing/subscription/cancel
GET  /openapi.json
GET  /docs
```

Billing Checkout accepts only a server catalog `sku_id`. Retrieve exact plan,
SKU, pack, feature, rate-limit, and pricing-rule data from
`GET /api/v1/billing/plans`; clients cannot submit a credit amount, quantity,
price, or entitlement.

Hosted MCP OAuth endpoints are served on the MCP issuer host, not the main API
hostname in production. They support Claude Directory callbacks and strict
Codex loopback callbacks:

```text
GET  https://mcp.esheria.ai/.well-known/oauth-protected-resource
GET  https://mcp.esheria.ai/.well-known/oauth-authorization-server
POST https://mcp.esheria.ai/register
GET  https://mcp.esheria.ai/authorize
POST https://mcp.esheria.ai/token
POST https://mcp.esheria.ai/revoke
GET  https://mcp.esheria.ai/api/v1/oauth/introspect
```

`/api/v1/oauth/introspect` is an internal non-billable validation endpoint for
the hosted MCP worker. It requires API auth and returns safe principal metadata
only, not token secrets.

Canonical pack rows may include `fact_class`, `duty_holder_type`,
`audience_type`, `operability_class`, `customer_actionability`,
`legal_effect`, and `recommended_use`. Filing rules, evidence requirements,
penalty/consequence facts, legal review audit metadata, and change events are
served as first-class source-traced facts when present; legacy filing calendar
and evidence register behavior remains available as a fallback for older packs.
Most pack fact endpoints accept `version=<domain_pack_version>` for historical
reads when the requested version is loaded in the serving database.

## API Envelope

Every JSON response uses a deterministic envelope:

```json
{
  "status": "ok|error",
  "data": {},
  "errors": [],
  "trace_id": "..."
}
```

## Quick Start

```bash
python3 -m venv .venv-api
source .venv-api/bin/activate
pip install -r api/requirements-dev.txt

export APP_ENV=production
export API_AUTH_MODE=api_key
export API_AUTH_KEYS=dev-api-key
export REGULATORY_DB_HOST=/tmp
export REGULATORY_DB_PORT=5432
export REGULATORY_DB_NAME=postgres
export REGULATORY_DB_USER=postgres
export REGULATORY_DB_PASSWORD=
export REGULATORY_DB_SSLMODE=prefer
export API_DOMAIN_PACK_SOURCE=db
export API_DOMAIN_PACK_PUBLICATION_MODE=published
export API_INTERNAL_NON_REGULATORY_ROUTES_ENABLED=false

python3 api/scripts/harness_runtime_manager.py \
  --mode reload \
  --host 0.0.0.0 \
  --port 8080 \
  --startup-timeout-seconds 45
```

Production DB mode has no implicit jurisdiction or pack. Pack-specific requests
must provide `pack_id` or `pack_ids`. `API_DOMAIN_PACK_ID` is retained only for
explicit single-pack file-mode development compatibility.

## Validation

```bash
python3 -m py_compile api/app.py api/routes.py api/oauth.py api/oauth_routes.py api/services/domain_pack.py api/services/oauth.py api/services/regulatory_intelligence.py api/repositories.py api/billing_repository.py api/security.py api/mcp/esheria_mcp/server.py api/mcp/esheria_mcp/tools.py
python3 -m pytest tests/test_regulatory_intelligence_capabilities.py tests/test_esheria_regulatory_client_cli_mcp.py tests/test_regulatory_pack_multi_pack_api.py tests/test_kenya_data_protection_api_surface.py tests/test_kenya_data_protection_serving_db.py tests/test_kenya_data_protection_claim_evaluation.py tests/test_legal_status_publication_gate.py -q
python3 api/scripts/ke_data_protection_api_smoke.py --base-url http://127.0.0.1:8080 --api-key dev-api-key --json
```

## OpenAPI

- Interactive docs: `/docs`
- Spec endpoint: `/openapi.json`
- Committed snapshot: `api/openapi.v1.json`
- Regeneration script: `api/scripts/export_openapi.py`

The production OpenAPI schema is intentionally limited to the Regulatory Pack API surface.

## Core Docs

- Current endpoint catalog: `api/docs/API_ENDPOINT_CATALOG.md`
- Versioned sanitized public discovery catalog:
  `api/docs/PUBLIC_DISCOVERY_CATALOG.md`
- Acquisition, activation, retention, and client-surface measurement:
  `api/docs/ACQUISITION_ACTIVATION_MEASUREMENT.md`
- Token billing and credits: `api/docs/API_TOKEN_BILLING_CREDITS.md`
- Client integration guide: `api/docs/CLIENT_API_GUIDE.md`
- Regulatory intelligence pipeline deep dive:
  `api/docs/REGULATORY_INTELLIGENCE_PIPELINE_DEEP_DIVE.md`
- CLI and MCP product PRD: `api/docs/REGULATORY_API_CLI_MCP_PRODUCT_PRD.md`
- CLI and MCP implementation guide: `api/docs/REGULATORY_API_CLI_MCP_GUIDE.md`
- Public CLI license and hosted-service terms boundary:
  `api/docs/PUBLIC_CLI_LICENSE_AND_TERMS.md`
- Installable CLI/MCP commands: root `pyproject.toml` exposes `esheria` and `esheria-mcp` console scripts while `bin/esheria` and `bin/esheria-mcp` remain repo-local wrappers.
- Hosted MCP: `esheria-mcp serve --http --host 127.0.0.1 --port 8081 --path /mcp` runs the official SDK Streamable HTTP transport for `https://mcp.esheria.ai/mcp`; local stdio remains a token-validated fallback for hosts without remote MCP URL support.
- Hosted MCP OAuth: `https://mcp.esheria.ai/mcp` is a protected MCP resource.
  Claude.ai and Claude Desktop use click-to-connect OAuth discovery. Codex may
  use `codex mcp login esheria` or a dashboard data token sent as
  `Authorization: Bearer <token>` / `X-API-Key: <token>`. OAuth sees 20
  read-only tools, normal data tokens see
  29 safe tools, and operator tokens add only scope-authorized mutations up to
  the complete 37-tool catalog. Hosted callbacks remain constrained by
  `OAUTH_ALLOWED_REDIRECT_URI_PREFIXES`; Codex loopback callbacks are separately
  validated as exact local HTTP hosts with an explicit port and
  `/callback/<id>` path.
- Regulatory source monitor config example:
  `regulatory_data_model/source_watch_config.example.json`
- Regulatory intelligence operators:
  `pipeline/monitor_regulatory_sources.py`,
  `pipeline/build_regulatory_graph_projection.py`, and
  `dags/regulatory_intelligence_monitoring.py`
- Working copy-paste API examples: `api/docs/WORKING_API_EXAMPLES.md`
- Business-question API examples: `api/docs/BUSINESS_QUESTION_API_EXAMPLES.md`
- RL team integration guide: `api/docs/RL_TEAM_INTEGRATION_GUIDE.md`
- External deployment guide: `api/docs/EXTERNAL_API_DEPLOYMENT.md`
- Public DNS/TLS runbook: `api/docs/PUBLIC_API_DNS_TLS.md`
- Environment matrix: `api/docs/ENVIRONMENT_MATRIX.md`
- Runbook: `api/docs/RUNBOOK.md`
- Claude Directory submission checklist:
  `api/docs/CLAUDE_DIRECTORY_SUBMISSION_CHECKLIST.md`
- Generic regulatory pack pipeline: `api/docs/GENERIC_REGULATORY_PACK_PIPELINE.md`
- Request examples: `api/docs/OPENAPI_AND_EXAMPLES.md`
- Regulatory corpus ETL runbook: `api/docs/REGULATORY_CORPUS_ETL_RUNBOOK.md`
