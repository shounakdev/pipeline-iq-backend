"""Configuration for remediation safety guardrails."""

from __future__ import annotations

import os


def _positive_int_from_env(
    name: str,
    default: int,
) -> int:
    raw_value = os.getenv(
        name,
        str(default),
    )

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a valid integer, "
            f"received {raw_value!r}"
        ) from exc

    if value <= 0:
        raise ValueError(
            f"{name} must be greater than zero"
        )

    return value


MAX_ROLLBACKS_PER_SERVICE_WINDOW = (
    _positive_int_from_env(
        "MAX_ROLLBACKS_PER_SERVICE_WINDOW",
        2,
    )
)

ROLLBACK_WINDOW_MINUTES = (
    _positive_int_from_env(
        "ROLLBACK_WINDOW_MINUTES",
        60,
    )
)

ROLLBACK_LOOP_PREVENTION_MINUTES = (
    _positive_int_from_env(
        "ROLLBACK_LOOP_PREVENTION_MINUTES",
        120,
    )
)
