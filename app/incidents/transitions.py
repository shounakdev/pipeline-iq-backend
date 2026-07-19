"""Canonical incident lifecycle transition rules.

This module contains pure incident status-transition validation. It must not
perform database queries, commits, timeline creation, audit logging, or HTTP
error handling.
"""

from __future__ import annotations

from typing import Any

from app.incidents.enums import IncidentStatus


ALLOWED_INCIDENT_TRANSITIONS: dict[
    IncidentStatus,
    set[IncidentStatus],
] = {
    IncidentStatus.DETECTED: {
        IncidentStatus.ACKNOWLEDGED,
    },
    IncidentStatus.ACKNOWLEDGED: {
        IncidentStatus.INVESTIGATING,
    },
    IncidentStatus.INVESTIGATING: {
        IncidentStatus.ACTION_RECOMMENDED,
        IncidentStatus.REMEDIATING,
    },
    IncidentStatus.ACTION_RECOMMENDED: {
        IncidentStatus.REMEDIATING,
    },
    IncidentStatus.REMEDIATING: {
        IncidentStatus.RESOLVED,
        IncidentStatus.FAILED_RECOVERY,
    },
    IncidentStatus.FAILED_RECOVERY: {
        IncidentStatus.INVESTIGATING,
        IncidentStatus.REMEDIATING,
    },
    IncidentStatus.RESOLVED: set(),
}


# Backward-compatible alias retained for older tests and integrations.
#
# This references the canonical dictionary rather than creating a second
# transition map.
ALLOWED_TRANSITIONS = ALLOWED_INCIDENT_TRANSITIONS


def _normalise_status(
    value: IncidentStatus | str | Any,
) -> IncidentStatus:
    """Normalise strings or compatible enum values into IncidentStatus."""

    if isinstance(value, IncidentStatus):
        return value

    return IncidentStatus(
        getattr(value, "value", value)
    )


class InvalidIncidentTransitionError(ValueError):
    """Raised when an incident status transition is not permitted."""

    def __init__(
        self,
        current_status: IncidentStatus | str,
        requested_status: IncidentStatus | str,
        message: str | None = None,
    ) -> None:
        current = _normalise_status(current_status)
        requested = _normalise_status(requested_status)

        self.current_status = current
        self.requested_status = requested

        # Compatibility attributes for older callers.
        self.from_status = current
        self.to_status = requested

        detail = message or (
            "Invalid incident status transition: "
            f"{current.value} -> {requested.value}"
        )

        super().__init__(detail)


def validate_incident_transition(
    *,
    current_status: IncidentStatus | str,
    requested_status: IncidentStatus | str,
) -> None:
    """Validate that an incident can move to the requested status.

    Raises:
        ValueError: If either supplied status cannot be converted into an
            IncidentStatus.
        InvalidIncidentTransitionError: If the incident is already in the
            requested status or the transition is not permitted.
    """

    current = _normalise_status(current_status)
    requested = _normalise_status(requested_status)

    if current == requested:
        raise InvalidIncidentTransitionError(
            current_status=current,
            requested_status=requested,
            message=(
                "Incident is already in status "
                f"{requested.value}"
            ),
        )

    allowed_statuses = ALLOWED_INCIDENT_TRANSITIONS.get(
        current,
        set(),
    )

    if requested not in allowed_statuses:
        raise InvalidIncidentTransitionError(
            current_status=current,
            requested_status=requested,
        )


def validate_status_transition(
    current_status: IncidentStatus | str,
    requested_status: IncidentStatus | str,
) -> None:
    """Backward-compatible wrapper around the canonical validator."""

    validate_incident_transition(
        current_status=current_status,
        requested_status=requested_status,
    )