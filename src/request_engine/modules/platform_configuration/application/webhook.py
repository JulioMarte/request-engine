from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_ALLOWED_KEYS = frozenset({"base_url", "auth_header_name", "timeout_seconds"})
_RESERVED_HEADERS = frozenset({"content-length", "content-type", "host"})


@dataclass(frozen=True, slots=True)
class WebhookConfiguration:
    base_url: str
    auth_header_name: str | None
    timeout_seconds: float


def parse_webhook_configuration(configuration: dict[str, object]) -> WebhookConfiguration:
    unknown = set(configuration) - _ALLOWED_KEYS
    if unknown:
        raise ValueError("webhook configuration contains unsupported fields")

    base_url_raw = configuration.get("base_url")
    if not isinstance(base_url_raw, str) or not base_url_raw.strip():
        raise ValueError("webhook base_url is required")
    base_url = base_url_raw.strip().rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("webhook base_url must be a credential-free https URL")

    header_raw = configuration.get("auth_header_name")
    auth_header_name: str | None
    if header_raw is None:
        auth_header_name = None
    elif isinstance(header_raw, str) and _HEADER_NAME.fullmatch(header_raw.strip()):
        auth_header_name = header_raw.strip()
        if auth_header_name.lower() in _RESERVED_HEADERS:
            raise ValueError("webhook auth header name is reserved")
    else:
        raise ValueError("webhook auth_header_name is invalid")

    timeout_raw = configuration.get("timeout_seconds", 10.0)
    if isinstance(timeout_raw, bool) or not isinstance(timeout_raw, (int, float)):
        raise ValueError("webhook timeout_seconds must be numeric")
    timeout_seconds = float(timeout_raw)
    if timeout_seconds <= 0 or timeout_seconds > 30:
        raise ValueError("webhook timeout_seconds must be > 0 and <= 30")

    return WebhookConfiguration(
        base_url=base_url,
        auth_header_name=auth_header_name,
        timeout_seconds=timeout_seconds,
    )
