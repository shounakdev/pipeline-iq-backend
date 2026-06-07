import os
import re
from typing import Iterable


SECRET_PATTERNS = [
    re.compile(r"(SONARQUBE_TOKEN\s*=\s*)([^\s]+)", re.IGNORECASE),
    re.compile(r"(SONAR_TOKEN\s*=\s*)([^\s]+)", re.IGNORECASE),
    re.compile(r"(sonar\.login\s*=\s*)([^\s]+)", re.IGNORECASE),
    re.compile(r"(sonar\.token\s*=\s*)([^\s]+)", re.IGNORECASE),
    re.compile(r"(Authorization:\s*Bearer\s+)([^\s]+)", re.IGNORECASE),
    re.compile(r"(-Dsonar\.login=)([^\s]+)", re.IGNORECASE),
    re.compile(r"(-Dsonar\.token=)([^\s]+)", re.IGNORECASE),
]


def mask_known_secret_values(text: str, secrets: Iterable[str | None]) -> str:
    if not text:
        return text

    sanitized = text

    for secret in secrets:
        if secret and len(secret) >= 6:
            sanitized = sanitized.replace(secret, "****MASKED_SECRET****")

    return sanitized


def sanitize_log_text(text: str) -> str:
    if not text:
        return text

    sanitized = text

    env_secrets = [
        os.getenv("SONARQUBE_TOKEN"),
        os.getenv("SONAR_TOKEN"),
    ]

    sanitized = mask_known_secret_values(sanitized, env_secrets)

    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub(r"\1****MASKED_SECRET****", sanitized)

    return sanitized


def sanitize_log_lines(lines: list[str]) -> list[str]:
    return [sanitize_log_text(line) for line in lines]