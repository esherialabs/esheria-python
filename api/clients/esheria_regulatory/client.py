from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import httpx

from api.clients.esheria_regulatory.config import EsheriaClientConfig
from api.clients.esheria_regulatory.errors import (
    EsheriaApiError,
    EsheriaAuthenticationError,
    EsheriaAuthorizationError,
    EsheriaNotFoundError,
    EsheriaPaymentRequiredError,
    EsheriaRateLimitError,
    EsheriaServerError,
    EsheriaTimeoutError,
    EsheriaTransportError,
    EsheriaValidationError,
)
from api.clients.esheria_regulatory.models import (
    ApiEnvelope,
    ApplicabilityResult,
    CitationContextResult,
    EntityProfileResult,
    EsheriaResult,
    EvidenceRegisterResult,
    FilingCalendarResult,
    ChangeEventListResult,
    CustomerApplicabilityRunResult,
    CustomerChangeImpactResult,
    CustomerLifecyclePreviewResult,
    CustomerObligationInstanceResult,
    CustomerProfileResult,
    GraphApplicabilityResult,
    GraphCoverageResult,
    GraphQueryResult,
    HealthResult,
    LegalReviewAuditResult,
    ObligationListResult,
    PackExportResult,
    PackDiffResult,
    PackListResult,
    PackSummaryResult,
    PackVersionListResult,
    PenaltyFactListResult,
    ReadinessResult,
    RelationshipListResult,
    SourceCurrentnessResult,
    SourceWatchResult,
    VerifyClaimRequest,
    VerifyClaimResult,
)
from api.clients.esheria_regulatory.retries import RETRYABLE_STATUS_CODES, sleep_before_retry


ResultT = TypeVar("ResultT", bound=EsheriaResult)


def _path_segment(value: str, *, field_name: str) -> str:
    """Validate and encode one caller-controlled API path segment.

    Identifiers are deliberately stricter than arbitrary URL text. Rejecting
    slash-like and dot-segment values before quoting prevents an MCP/CLI caller
    from retargeting a request to a different API route.
    """

    segment = str(value or "").strip()
    if not segment:
        raise ValueError(f"{field_name} must not be empty")
    if len(segment) > 512:
        raise ValueError(f"{field_name} must not exceed 512 characters")
    if segment in {".", ".."}:
        raise ValueError(f"{field_name} must not be a URL dot segment")
    if any(character in segment for character in ("/", "\\", "\x00", "\r", "\n")):
        raise ValueError(f"{field_name} contains an invalid path character")
    return quote(segment, safe="-._~:@+")


class EsheriaRegulatoryClient:
    def __init__(
        self,
        config: EsheriaClientConfig | None = None,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config or EsheriaClientConfig.from_env()
        self._owned_client = http_client is None
        self._client = http_client or httpx.Client(
            base_url=self.config.normalized_base_url,
            timeout=self.config.timeout_seconds,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=8,
                max_keepalive_connections=4,
                keepalive_expiry=30,
            ),
        )

    @classmethod
    def from_env(cls) -> "EsheriaRegulatoryClient":
        return cls(EsheriaClientConfig.from_env())

    def close(self) -> None:
        if self._owned_client:
            self._client.close()

    def __enter__(self) -> "EsheriaRegulatoryClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def health(self) -> HealthResult:
        return self._request("GET", "/healthz", result_model=HealthResult)

    def ready(self) -> ReadinessResult:
        return self._request("GET", "/readyz", result_model=ReadinessResult, allowed_statuses={503})

    def list_packs(self, filters: Mapping[str, Any] | None = None) -> PackListResult:
        return self._request("GET", "/api/v1/domain-packs", params=filters, result_model=PackListResult)

    def get_pack(self, pack_id: str) -> PackSummaryResult:
        segment = _path_segment(pack_id, field_name="pack_id")
        return self._request("GET", f"/api/v1/domain-packs/{segment}", result_model=PackSummaryResult)

    def list_pack_versions(self, pack_id: str, filters: Mapping[str, Any] | None = None) -> PackVersionListResult:
        segment = _path_segment(pack_id, field_name="pack_id")
        return self._request(
            "GET",
            f"/api/v1/domain-packs/{segment}/versions",
            params=self._query_params(filters),
            result_model=PackVersionListResult,
        )

    def diff_pack_versions(self, pack_id: str, filters: Mapping[str, Any] | None = None) -> PackDiffResult:
        segment = _path_segment(pack_id, field_name="pack_id")
        return self._request(
            "GET",
            f"/api/v1/domain-packs/{segment}/diff",
            params=self._query_params(filters),
            result_model=PackDiffResult,
        )

    def list_change_events(self, pack_id: str, filters: Mapping[str, Any] | None = None) -> ChangeEventListResult:
        segment = _path_segment(pack_id, field_name="pack_id")
        return self._request(
            "GET",
            f"/api/v1/domain-packs/{segment}/change-events",
            params=self._query_params(filters),
            result_model=ChangeEventListResult,
        )

    def verify_claim(self, request: VerifyClaimRequest | Mapping[str, Any]) -> VerifyClaimResult:
        validated = request if isinstance(request, VerifyClaimRequest) else VerifyClaimRequest.model_validate(dict(request))
        payload = validated.model_dump(exclude_none=True)
        return self._request("POST", "/api/v1/legal-status/verify-claim", json_body=payload, result_model=VerifyClaimResult)

    def list_obligations(self, pack_id: str, filters: Mapping[str, Any] | None = None) -> ObligationListResult:
        segment = _path_segment(pack_id, field_name="pack_id")
        return self._request(
            "GET",
            f"/api/v1/domain-packs/{segment}/obligations",
            params=self._query_params(filters),
            result_model=ObligationListResult,
        )

    def check_applicability(self, pack_id: str, profile: Mapping[str, Any]) -> ApplicabilityResult:
        segment = _path_segment(pack_id, field_name="pack_id")
        return self._request(
            "POST",
            f"/api/v1/domain-packs/{segment}/applicability-check",
            json_body=dict(profile),
            result_model=ApplicabilityResult,
        )

    def get_filing_calendar(self, pack_id: str, filters: Mapping[str, Any] | None = None) -> FilingCalendarResult:
        segment = _path_segment(pack_id, field_name="pack_id")
        return self._request(
            "GET",
            f"/api/v1/domain-packs/{segment}/filing-calendar",
            params=self._query_params(filters),
            result_model=FilingCalendarResult,
        )

    def get_evidence_register(self, pack_id: str, filters: Mapping[str, Any] | None = None) -> EvidenceRegisterResult:
        segment = _path_segment(pack_id, field_name="pack_id")
        return self._request(
            "GET",
            f"/api/v1/domain-packs/{segment}/evidence-register",
            params=self._query_params(filters),
            result_model=EvidenceRegisterResult,
        )

    def get_penalty_facts(self, pack_id: str, filters: Mapping[str, Any] | None = None) -> PenaltyFactListResult:
        segment = _path_segment(pack_id, field_name="pack_id")
        return self._request(
            "GET",
            f"/api/v1/domain-packs/{segment}/penalty-facts",
            params=self._query_params(filters),
            result_model=PenaltyFactListResult,
        )

    def get_legal_review_audit(self, pack_id: str, filters: Mapping[str, Any] | None = None) -> LegalReviewAuditResult:
        segment = _path_segment(pack_id, field_name="pack_id")
        return self._request(
            "GET",
            f"/api/v1/domain-packs/{segment}/legal-review-audit",
            params=self._query_params(filters),
            result_model=LegalReviewAuditResult,
        )

    def list_relationships(self, pack_id: str, filters: Mapping[str, Any] | None = None) -> RelationshipListResult:
        segment = _path_segment(pack_id, field_name="pack_id")
        params = dict(filters or {})
        if params.get("relationship_types") and not params.get("relationship_type"):
            values = params.pop("relationship_types")
            if isinstance(values, list):
                if len(values) > 1:
                    raise ValueError("The pack relationships endpoint accepts only one relationship type")
                params["relationship_type"] = values[0] if values else None
            else:
                params["relationship_type"] = values
        return self._request(
            "GET",
            f"/api/v1/domain-packs/{segment}/relationships",
            params=self._query_params(params),
            result_model=RelationshipListResult,
        )

    def export_pack(self, pack_id: str, options: Mapping[str, Any] | None = None) -> PackExportResult:
        segment = _path_segment(pack_id, field_name="pack_id")
        return self._request(
            "GET",
            f"/api/v1/domain-packs/{segment}/export",
            params=self._query_params(options),
            result_model=PackExportResult,
        )

    def query_graph(self, request: Mapping[str, Any]) -> GraphQueryResult:
        return self._request(
            "POST",
            "/api/v1/regulatory-graph/query",
            json_body=dict(request),
            result_model=GraphQueryResult,
        )

    def check_graph_applicability(self, request: Mapping[str, Any]) -> GraphApplicabilityResult:
        return self._request(
            "POST",
            "/api/v1/regulatory-graph/applicability-check",
            json_body=dict(request),
            result_model=GraphApplicabilityResult,
        )

    def get_entity_profile(self, request: Mapping[str, Any]) -> EntityProfileResult:
        return self._request(
            "GET",
            "/api/v1/regulatory-graph/entity-profile",
            params=self._query_params(request),
            result_model=EntityProfileResult,
        )

    def create_source_watch(self, request: Mapping[str, Any]) -> SourceWatchResult:
        return self._request(
            "POST",
            "/api/v1/regulatory-monitoring/source-watches",
            json_body=dict(request),
            result_model=SourceWatchResult,
        )

    def list_source_watches(self, filters: Mapping[str, Any] | None = None) -> SourceWatchResult:
        return self._request(
            "GET",
            "/api/v1/regulatory-monitoring/source-watches",
            params=self._query_params(filters),
            result_model=SourceWatchResult,
        )

    def get_source_currentness(self, filters: Mapping[str, Any] | None = None) -> SourceCurrentnessResult:
        return self._request(
            "GET",
            "/api/v1/regulatory-monitoring/source-currentness",
            params=self._query_params(filters),
            result_model=SourceCurrentnessResult,
        )

    def check_source_watches(self, request: Mapping[str, Any] | None = None) -> SourceWatchResult:
        return self._request(
            "POST",
            "/api/v1/regulatory-monitoring/source-watches/check",
            json_body=dict(request or {}),
            result_model=SourceWatchResult,
        )

    def list_source_change_events(self, filters: Mapping[str, Any] | None = None) -> SourceWatchResult:
        return self._request(
            "GET",
            "/api/v1/regulatory-monitoring/source-change-events",
            params=self._query_params(filters),
            result_model=SourceWatchResult,
        )

    def list_recompile_candidates(self, filters: Mapping[str, Any] | None = None) -> SourceWatchResult:
        return self._request(
            "GET",
            "/api/v1/regulatory-monitoring/recompile-candidates",
            params=self._query_params(filters),
            result_model=SourceWatchResult,
        )

    def rebuild_graph_projection(self, request: Mapping[str, Any] | None = None) -> GraphCoverageResult:
        return self._request(
            "POST",
            "/api/v1/regulatory-graph/projections/rebuild",
            json_body=dict(request or {}),
            result_model=GraphCoverageResult,
        )

    def get_graph_coverage(self, filters: Mapping[str, Any] | None = None) -> GraphCoverageResult:
        return self._request(
            "GET",
            "/api/v1/regulatory-graph/coverage",
            params=self._query_params(filters),
            result_model=GraphCoverageResult,
        )

    def create_customer_profile(self, request: Mapping[str, Any]) -> CustomerProfileResult:
        return self._request(
            "POST",
            "/api/v1/customer-profiles",
            json_body=dict(request),
            result_model=CustomerProfileResult,
        )

    def preview_customer_lifecycle(self, request: Mapping[str, Any]) -> CustomerLifecyclePreviewResult:
        return self._request(
            "POST",
            "/api/v1/customer-lifecycle/preview",
            json_body=dict(request),
            result_model=CustomerLifecyclePreviewResult,
        )

    def list_customer_profiles(self, filters: Mapping[str, Any] | None = None) -> CustomerProfileResult:
        return self._request(
            "GET",
            "/api/v1/customer-profiles",
            params=self._query_params(filters),
            result_model=CustomerProfileResult,
        )

    def get_customer_profile(self, customer_profile_id: str) -> CustomerProfileResult:
        segment = _path_segment(customer_profile_id, field_name="customer_profile_id")
        return self._request(
            "GET",
            f"/api/v1/customer-profiles/{segment}",
            result_model=CustomerProfileResult,
        )

    def run_customer_applicability(
        self,
        customer_profile_id: str,
        request: Mapping[str, Any] | None = None,
    ) -> CustomerApplicabilityRunResult:
        segment = _path_segment(customer_profile_id, field_name="customer_profile_id")
        return self._request(
            "POST",
            f"/api/v1/customer-profiles/{segment}/applicability-runs",
            json_body=dict(request or {}),
            result_model=CustomerApplicabilityRunResult,
        )

    def list_customer_applicability_runs(
        self,
        customer_profile_id: str,
        filters: Mapping[str, Any] | None = None,
    ) -> CustomerApplicabilityRunResult:
        segment = _path_segment(customer_profile_id, field_name="customer_profile_id")
        return self._request(
            "GET",
            f"/api/v1/customer-profiles/{segment}/applicability-runs",
            params=self._query_params(filters),
            result_model=CustomerApplicabilityRunResult,
        )

    def list_customer_obligation_instances(
        self,
        filters: Mapping[str, Any] | None = None,
    ) -> CustomerObligationInstanceResult:
        return self._request(
            "GET",
            "/api/v1/customer-obligation-instances",
            params=self._query_params(filters),
            result_model=CustomerObligationInstanceResult,
        )

    def update_customer_obligation_instance(
        self,
        customer_obligation_instance_id: str,
        request: Mapping[str, Any],
    ) -> CustomerObligationInstanceResult:
        segment = _path_segment(
            customer_obligation_instance_id,
            field_name="customer_obligation_instance_id",
        )
        return self._request(
            "PATCH",
            f"/api/v1/customer-obligation-instances/{segment}",
            json_body=dict(request),
            result_model=CustomerObligationInstanceResult,
        )

    def recompute_customer_change_impacts(
        self,
        request: Mapping[str, Any] | None = None,
    ) -> CustomerChangeImpactResult:
        return self._request(
            "POST",
            "/api/v1/customer-change-impacts/recompute",
            json_body=dict(request or {}),
            result_model=CustomerChangeImpactResult,
        )

    def list_customer_change_impacts(
        self,
        filters: Mapping[str, Any] | None = None,
    ) -> CustomerChangeImpactResult:
        return self._request(
            "GET",
            "/api/v1/customer-change-impacts",
            params=self._query_params(filters),
            result_model=CustomerChangeImpactResult,
        )

    def update_customer_change_impact(
        self,
        customer_change_impact_id: str,
        request: Mapping[str, Any],
    ) -> CustomerChangeImpactResult:
        segment = _path_segment(customer_change_impact_id, field_name="customer_change_impact_id")
        return self._request(
            "PATCH",
            f"/api/v1/customer-change-impacts/{segment}",
            json_body=dict(request),
            result_model=CustomerChangeImpactResult,
        )

    def create_token(self, request: Mapping[str, Any]) -> EsheriaResult:
        return self._request(
            "POST",
            "/api/v1/tokens",
            json_body=dict(request),
            result_model=EsheriaResult,
        )

    def list_tokens(self, filters: Mapping[str, Any] | None = None) -> EsheriaResult:
        return self._request(
            "GET",
            "/api/v1/tokens",
            params=self._query_params(filters),
            result_model=EsheriaResult,
        )

    def revoke_token(self, token_id: str) -> EsheriaResult:
        segment = _path_segment(token_id, field_name="token_id")
        return self._request(
            "POST",
            f"/api/v1/tokens/{segment}/revoke",
            result_model=EsheriaResult,
        )

    def billing_balance(self) -> EsheriaResult:
        return self._request("GET", "/api/v1/billing/balance", result_model=EsheriaResult)

    def billing_usage(self, filters: Mapping[str, Any] | None = None) -> EsheriaResult:
        return self._request(
            "GET",
            "/api/v1/billing/usage",
            params=self._query_params(filters),
            result_model=EsheriaResult,
        )

    def billing_plans(self) -> EsheriaResult:
        return self._request("GET", "/api/v1/billing/plans", result_model=EsheriaResult)

    def create_billing_checkout_session(self, *, sku_id: str) -> EsheriaResult:
        return self._request(
            "POST",
            "/api/v1/billing/topups/checkout-session",
            json_body={"sku_id": sku_id},
            result_model=EsheriaResult,
        )

    def get_workspace(self) -> EsheriaResult:
        return self._request("GET", "/api/v1/workspace", result_model=EsheriaResult)

    def update_workspace(self, request: Mapping[str, Any]) -> EsheriaResult:
        return self._request(
            "PATCH",
            "/api/v1/workspace",
            json_body=dict(request),
            result_model=EsheriaResult,
        )

    def billing_subscription(self) -> EsheriaResult:
        return self._request("GET", "/api/v1/billing/subscription", result_model=EsheriaResult)

    def cancel_billing_subscription(self, *, cancel_at_period_end: bool = False) -> EsheriaResult:
        return self._request(
            "POST",
            "/api/v1/billing/subscription/cancel",
            json_body={"cancel_at_period_end": cancel_at_period_end},
            result_model=EsheriaResult,
        )

    def get_citation_context(self, pack_id: str, citation_id: str) -> CitationContextResult:
        exported = self.export_pack(pack_id)
        citations = exported.data.get("citations") or []
        for citation in citations:
            if str(citation.get("citation_id") or "") == citation_id:
                return CitationContextResult.from_data(
                    {
                        "domain_pack": exported.data.get("domain_pack") or {},
                        "citation_id": citation_id,
                        "citation": citation,
                        "limitations": ["Citation context was resolved client-side from the published pack export."],
                    },
                    trace_id=exported.trace_id,
                    endpoint_path=exported.endpoint_path,
                    http_status=exported.http_status,
                )
        raise EsheriaNotFoundError(
            f"Citation `{citation_id}` was not found in pack `{pack_id}` export.",
            status_code=404,
            trace_id=exported.trace_id,
            error_code="citation_not_found",
            endpoint_path=exported.endpoint_path,
            request_metadata={"pack_id": pack_id, "citation_id": citation_id},
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        allowed_statuses: set[int] | None = None,
    ) -> EsheriaResult:
        return self._request(
            method,
            path,
            params=params,
            json_body=json_body,
            allowed_statuses=allowed_statuses,
            result_model=EsheriaResult,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        allowed_statuses: set[int] | None = None,
        result_model: type[ResultT],
    ) -> ResultT:
        method = method.upper()
        clean_path = path if path.startswith("/") else f"/{path}"
        attempts = max(0, int(self.config.retry_count)) + 1
        allowed = allowed_statuses or set()
        headers = self._headers(method)
        last_transport_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = self._client.request(
                    method,
                    clean_path,
                    params=self._query_params(params),
                    json=dict(json_body) if json_body is not None else None,
                    headers=headers,
                    follow_redirects=False,
                )
            except httpx.TimeoutException as exc:
                last_transport_error = exc
                if attempt < attempts - 1:
                    sleep_before_retry(attempt)
                    continue
                raise EsheriaTimeoutError(str(exc)) from exc
            except httpx.TransportError as exc:
                last_transport_error = exc
                if attempt < attempts - 1:
                    sleep_before_retry(attempt)
                    continue
                raise EsheriaTransportError(str(exc)) from exc

            if response.is_redirect:
                target = self._safe_redirect_target(response.headers.get("location", ""))
                suffix = f" to {target}" if target else ""
                raise EsheriaTransportError(
                    f"Refusing HTTP redirect from {clean_path}{suffix}; configure the canonical Esheria API base URL"
                )
            if response.status_code in RETRYABLE_STATUS_CODES and response.status_code not in allowed and attempt < attempts - 1:
                sleep_before_retry(attempt)
                continue
            envelope = self._parse_envelope(response, clean_path)
            if (response.status_code < 200 or response.status_code >= 300) and response.status_code not in allowed:
                raise self._api_error(envelope, response.status_code, clean_path)
            if envelope.status == "error":
                raise self._api_error(envelope, response.status_code, clean_path)
            return result_model.from_envelope(envelope, endpoint_path=clean_path, http_status=response.status_code)
        if last_transport_error:
            raise EsheriaTransportError(str(last_transport_error)) from last_transport_error
        raise EsheriaTransportError(f"Request to {clean_path} failed without a response")

    def _headers(self, method: str) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "accept-encoding": "gzip",
            "user-agent": self.config.user_agent,
        }
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers["idempotency-key"] = str(uuid4())
        return headers

    @staticmethod
    def _query_params(values: Mapping[str, Any] | None) -> dict[str, Any]:
        if not values:
            return {}
        params: dict[str, Any] = {}
        for key, value in values.items():
            if value is None or value == "" or value == []:
                continue
            params["q" if key == "query" else key] = value
        return params

    @staticmethod
    def _parse_envelope(response: httpx.Response, path: str) -> ApiEnvelope:
        try:
            payload = response.json()
        except ValueError as exc:
            raise EsheriaTransportError(f"Non-JSON response from {path}: HTTP {response.status_code}") from exc
        try:
            return ApiEnvelope.model_validate(payload)
        except Exception as exc:
            raise EsheriaTransportError(f"Malformed API envelope from {path}: HTTP {response.status_code}") from exc

    @staticmethod
    def _safe_redirect_target(location: str) -> str:
        if not location:
            return ""
        parsed = urlsplit(location)
        if not parsed.scheme and not parsed.netloc:
            return urlunsplit(("", "", parsed.path, "", ""))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    def _api_error(self, envelope: ApiEnvelope, status_code: int, path: str) -> EsheriaApiError:
        first = envelope.errors[0] if envelope.errors else None
        code = first.code if first else "api_error"
        message = first.message if first and first.message else "API request failed"
        if self.config.api_key:
            message = message.replace(self.config.api_key, "***")
        kwargs = {
            "status_code": status_code,
            "trace_id": envelope.trace_id,
            "error_code": code,
            "endpoint_path": path,
            "request_metadata": {"endpoint_path": path},
        }
        if status_code == 401:
            return EsheriaAuthenticationError(message, **kwargs)
        if status_code == 403:
            return EsheriaAuthorizationError(message, **kwargs)
        if status_code == 402:
            return EsheriaPaymentRequiredError(message, **kwargs)
        if status_code == 404:
            return EsheriaNotFoundError(message, **kwargs)
        if status_code == 429:
            return EsheriaRateLimitError(message, **kwargs)
        if status_code in {400, 409, 422}:
            return EsheriaValidationError(message, **kwargs)
        if status_code >= 500:
            return EsheriaServerError(message, **kwargs)
        return EsheriaApiError(message, **kwargs)
