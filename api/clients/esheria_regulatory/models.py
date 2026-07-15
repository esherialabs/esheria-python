from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ALLOW_EXTRA = ConfigDict(extra="allow")


class ApiErrorItem(BaseModel):
    model_config = ALLOW_EXTRA

    code: str = ""
    message: str = ""
    field: str | None = None
    details: dict[str, Any] | None = None


class ApiEnvelope(BaseModel):
    model_config = ALLOW_EXTRA

    status: Literal["ok", "error"]
    data: Any | None = None
    errors: list[ApiErrorItem] = Field(default_factory=list)
    trace_id: str = ""


class EsheriaResult(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    trace_id: str
    data: dict[str, Any]
    envelope: ApiEnvelope
    endpoint_path: str
    http_status: int

    @classmethod
    def from_envelope(
        cls,
        envelope: ApiEnvelope,
        *,
        endpoint_path: str,
        http_status: int,
    ) -> "EsheriaResult":
        data = envelope.data if isinstance(envelope.data, dict) else {"value": envelope.data}
        payload = dict(data)
        payload.update(
            {
            "trace_id": envelope.trace_id,
            "data": data,
            "envelope": envelope,
            "endpoint_path": endpoint_path,
            "http_status": http_status,
            }
        )
        return cls.model_validate(payload)

    @classmethod
    def from_data(
        cls,
        data: dict[str, Any],
        *,
        trace_id: str,
        endpoint_path: str,
        http_status: int,
    ) -> "EsheriaResult":
        envelope = ApiEnvelope(status="ok", data=data, errors=[], trace_id=trace_id)
        return cls.from_envelope(envelope, endpoint_path=endpoint_path, http_status=http_status)


class HealthResult(EsheriaResult):
    status: str = ""
    version: str = ""
    environment: str = ""


class ReadinessDependency(BaseModel):
    model_config = ALLOW_EXTRA

    name: str = ""
    status: str = ""
    detail: str = ""


class ReadinessResult(EsheriaResult):
    status: str = ""
    dependencies: list[ReadinessDependency] = Field(default_factory=list)


class PackSummary(BaseModel):
    model_config = ALLOW_EXTRA

    domain_pack_id: str = ""
    domain_pack_version: str | None = None
    jurisdiction: str | None = None
    legal_domain: str | None = None
    status: str | None = None
    is_current: bool = True
    publication_mode: str = "published"
    published_legal_status_count: int = 0
    readiness_label: str | None = None
    limitations: list[str] = Field(default_factory=list)
    current_s3_prefix: str = ""


class PackListResult(EsheriaResult):
    packs: list[PackSummary] = Field(default_factory=list)
    total: int = 0
    limit: int = 100
    offset: int = 0


class PackSummaryResult(PackSummary, EsheriaResult):
    fact_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    published_row_counts_by_fact_type: dict[str, int] = Field(default_factory=dict)
    blocked_backlog_legal_status_count: int = 0
    family_coverage_summary: dict[str, Any] = Field(default_factory=dict)
    coverage_summary: dict[str, Any] = Field(default_factory=dict)
    manifest_summary: dict[str, Any] = Field(default_factory=dict)
    load_run_metadata: dict[str, Any] = Field(default_factory=dict)


class VerifyClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    pack_id: str
    jurisdiction: str | None = None
    domain: str | None = None
    publication_mode: str | None = None
    claimed_instrument_version: str | None = None
    limit: int = 3


class EnvelopeWorkflowResult(EsheriaResult):
    pass


ObligationListResult = EnvelopeWorkflowResult
ApplicabilityResult = EnvelopeWorkflowResult
FilingCalendarResult = EnvelopeWorkflowResult
EvidenceRegisterResult = EnvelopeWorkflowResult
PackVersionListResult = EnvelopeWorkflowResult
PackDiffResult = EnvelopeWorkflowResult
ChangeEventListResult = EnvelopeWorkflowResult
PenaltyFactListResult = EnvelopeWorkflowResult
LegalReviewAuditResult = EnvelopeWorkflowResult
RelationshipListResult = EnvelopeWorkflowResult
PackExportResult = EnvelopeWorkflowResult
GraphQueryResult = EnvelopeWorkflowResult
GraphApplicabilityResult = EnvelopeWorkflowResult
EntityProfileResult = EnvelopeWorkflowResult
VerifyClaimResult = EnvelopeWorkflowResult
CitationContextResult = EnvelopeWorkflowResult
SourceWatchResult = EnvelopeWorkflowResult
SourceCurrentnessResult = EnvelopeWorkflowResult
GraphCoverageResult = EnvelopeWorkflowResult
CustomerProfileResult = EnvelopeWorkflowResult
CustomerLifecyclePreviewResult = EnvelopeWorkflowResult
CustomerApplicabilityRunResult = EnvelopeWorkflowResult
CustomerObligationInstanceResult = EnvelopeWorkflowResult
CustomerChangeImpactResult = EnvelopeWorkflowResult
