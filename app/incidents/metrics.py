"""Pure incident response-time metric calculations."""

from datetime import datetime, timezone
from typing import TypedDict


class IncidentMetricsValues(TypedDict):
    """Calculated incident response metrics and display values."""

    mttd_seconds: int | None
    mtta_seconds: int | None
    mttr_seconds: int | None
    mttd_display: str | None
    mtta_display: str | None
    mttr_display: str | None


def calculate_duration_seconds(
    *,
    start: datetime | None,
    end: datetime | None,
) -> int | None:
    """
    Return the whole-number duration between two timestamps in seconds.

    Missing timestamps return None.

    Both timestamps must be timezone-aware. Invalid timestamp ordering
    returns None rather than zero because zero would incorrectly represent
    an instantaneous response.
    """

    if start is None or end is None:
        return None

    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError(
            "Incident metric timestamps must be timezone-aware"
        )

    normalized_start = start.astimezone(timezone.utc)
    normalized_end = end.astimezone(timezone.utc)

    duration_seconds = int(
        (
            normalized_end - normalized_start
        ).total_seconds()
    )

    if duration_seconds < 0:
        return None

    return duration_seconds


def format_duration(
    seconds: int | float | None,
) -> str | None:
    """
    Convert seconds into a compact operational duration.

    Examples:
        45   -> "45s"
        60   -> "1m"
        120  -> "2m"
        1920 -> "32m"
        3660 -> "1h 1m"
    """

    if seconds is None:
        return None

    if seconds < 0:
        raise ValueError("Duration cannot be negative")

    remaining_seconds = int(round(seconds))

    days, remaining_seconds = divmod(
        remaining_seconds,
        86_400,
    )
    hours, remaining_seconds = divmod(
        remaining_seconds,
        3_600,
    )
    minutes, remaining_seconds = divmod(
        remaining_seconds,
        60,
    )

    parts: list[str] = []

    if days:
        parts.append(f"{days}d")

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    if remaining_seconds or not parts:
        parts.append(f"{remaining_seconds}s")

    return " ".join(parts)


def calculate_mttd(
    *,
    failure_started_at: datetime | None,
    detected_at: datetime | None,
) -> int | None:
    """
    Calculate Mean Time to Detect in seconds.

    MTTD = detected_at - failure_started_at
    """

    return calculate_duration_seconds(
        start=failure_started_at,
        end=detected_at,
    )


def calculate_mtta(
    *,
    detected_at: datetime | None,
    acknowledged_at: datetime | None,
) -> int | None:
    """
    Calculate Mean Time to Acknowledge in seconds.

    MTTA = acknowledged_at - detected_at
    """

    return calculate_duration_seconds(
        start=detected_at,
        end=acknowledged_at,
    )


def calculate_mttr(
    *,
    detected_at: datetime | None,
    resolved_at: datetime | None,
) -> int | None:
    """
    Calculate Mean Time to Resolve in seconds.

    MTTR = resolved_at - detected_at
    """

    return calculate_duration_seconds(
        start=detected_at,
        end=resolved_at,
    )


def calculate_incident_metrics(
    *,
    failure_started_at: datetime | None,
    detected_at: datetime | None,
    acknowledged_at: datetime | None,
    resolved_at: datetime | None,
) -> IncidentMetricsValues:
    """
    Calculate the response-time metrics for one incident.

    MTTD is unavailable until failure_started_at is known.
    MTTA is unavailable until the incident is acknowledged.
    MTTR is unavailable until the incident is resolved.
    """

    mttd_seconds = calculate_mttd(
        failure_started_at=failure_started_at,
        detected_at=detected_at,
    )

    mtta_seconds = calculate_mtta(
        detected_at=detected_at,
        acknowledged_at=acknowledged_at,
    )

    mttr_seconds = calculate_mttr(
        detected_at=detected_at,
        resolved_at=resolved_at,
    )

    return {
        "mttd_seconds": mttd_seconds,
        "mtta_seconds": mtta_seconds,
        "mttr_seconds": mttr_seconds,
        "mttd_display": format_duration(mttd_seconds),
        "mtta_display": format_duration(mtta_seconds),
        "mttr_display": format_duration(mttr_seconds),
    }