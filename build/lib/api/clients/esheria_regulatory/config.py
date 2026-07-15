from __future__ import annotations

import os
import math
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

from api.clients.esheria_regulatory.version import PYTHON_USER_AGENT


DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_USER_AGENT = PYTHON_USER_AGENT


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _float_env(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    return float(raw)


def _int_env(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    return int(raw)


@dataclass(frozen=True)
class EsheriaClientConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    default_pack_id: str = ""
    timeout_seconds: float = 30.0
    retry_count: int = 2
    user_agent: str = DEFAULT_USER_AGENT

    def __post_init__(self) -> None:
        parsed = urlsplit(self.normalized_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Esheria API base URL must be an absolute http:// or https:// URL")
        if parsed.username or parsed.password:
            raise ValueError("Esheria API base URL must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("Esheria API base URL must not contain a query string or fragment")
        if parsed.path not in {"", "/"}:
            raise ValueError("Esheria API base URL must not contain a path prefix")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Esheria timeout must be greater than zero seconds")
        if self.retry_count < 0:
            raise ValueError("Esheria retry count must be zero or greater")
        if not self.user_agent.strip():
            raise ValueError("Esheria user agent must not be empty")
        if "\r" in self.user_agent or "\n" in self.user_agent:
            raise ValueError("Esheria user agent must not contain line breaks")
        if "\r" in self.api_key or "\n" in self.api_key:
            raise ValueError("Esheria API key must not contain line breaks")

    @classmethod
    def from_env(cls) -> "EsheriaClientConfig":
        return cls(
            base_url=_env("ESHERIA_API_BASE_URL", DEFAULT_BASE_URL),
            api_key=_env("ESHERIA_API_KEY") or _env("ESHERIA_API_TOKEN"),
            default_pack_id=_env("ESHERIA_DEFAULT_PACK_ID"),
            timeout_seconds=_float_env("ESHERIA_TIMEOUT_SECONDS", 30.0),
            retry_count=_int_env("ESHERIA_RETRY_COUNT", 2),
            user_agent=_env("ESHERIA_USER_AGENT", DEFAULT_USER_AGENT),
        )

    def with_overrides(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        retry_count: int | None = None,
        user_agent: str | None = None,
    ) -> "EsheriaClientConfig":
        return replace(
            self,
            base_url=(base_url or self.base_url).strip(),
            api_key=self.api_key if api_key is None else api_key.strip(),
            timeout_seconds=self.timeout_seconds if timeout_seconds is None else timeout_seconds,
            retry_count=self.retry_count if retry_count is None else retry_count,
            user_agent=(user_agent or self.user_agent).strip(),
        )

    @property
    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")

    def redacted(self) -> dict[str, object]:
        return {
            "base_url": self.normalized_base_url,
            "api_key": "set" if self.api_key else "missing",  # pragma: allowlist secret
            "default_pack_id": self.default_pack_id,
            "timeout_seconds": self.timeout_seconds,
            "retry_count": self.retry_count,
            "user_agent": self.user_agent,
        }
