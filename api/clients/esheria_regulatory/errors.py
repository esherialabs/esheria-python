from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class EsheriaError(Exception):
    """Base class for client-side Esheria errors."""


class EsheriaTransportError(EsheriaError):
    pass


class EsheriaTimeoutError(EsheriaTransportError):
    pass


@dataclass
class EsheriaApiError(EsheriaError):
    message: str
    status_code: int | None = None
    trace_id: str | None = None
    error_code: str | None = None
    endpoint_path: str | None = None
    request_metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        pieces = [self.message]
        if self.error_code:
            pieces.append(f"code={self.error_code}")
        if self.status_code is not None:
            pieces.append(f"http_status={self.status_code}")
        if self.trace_id:
            pieces.append(f"trace_id={self.trace_id}")
        if self.endpoint_path:
            pieces.append(f"endpoint={self.endpoint_path}")
        return " | ".join(pieces)


class EsheriaAuthenticationError(EsheriaApiError):
    pass


class EsheriaAuthorizationError(EsheriaApiError):
    pass


class EsheriaPaymentRequiredError(EsheriaApiError):
    pass


class EsheriaNotFoundError(EsheriaApiError):
    pass


class EsheriaRateLimitError(EsheriaApiError):
    pass


class EsheriaValidationError(EsheriaApiError):
    pass


class EsheriaServerError(EsheriaApiError):
    pass
