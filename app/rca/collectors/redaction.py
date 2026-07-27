from __future__ import annotations

import re
from typing import Any


SENSITIVE_KEY_PATTERNS = [
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "private_key",
    "database_url",
    "db_url",
]

LARGE_BODY_KEYS = {
    "body",
    "request_body",
    "response_body",
    "payload",
    "raw_payload",
    "raw_request",
    "raw_response",
}

SECRET_VALUE_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"postgres(?:ql)?://[^\s]+", re.IGNORECASE),
    re.compile(r"mysql://[^\s]+", re.IGNORECASE),
    re.compile(r"mongodb(?:\+srv)?://[^\s]+", re.IGNORECASE),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
]

REDACTED = "[REDACTED]"
REDACTED_LARGE_BODY = "[REDACTED_LARGE_BODY]"


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(pattern in normalized for pattern in SENSITIVE_KEY_PATTERNS)


def redact_string(value: str) -> str:
    redacted = value

    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)

    return redacted


def redact_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}

        for key, item in value.items():
            normalized_key = str(key).lower()

            if is_sensitive_key(str(key)):
                redacted[key] = REDACTED
            elif normalized_key in LARGE_BODY_KEYS:
                redacted[key] = REDACTED_LARGE_BODY
            else:
                redacted[key] = redact_evidence(item)

        return redacted

    if isinstance(value, list):
        return [redact_evidence(item) for item in value]

    if isinstance(value, str):
        return redact_string(value)

    return value