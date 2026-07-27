import pytest

from app.incidents.transitions import (
    ALLOWED_TRANSITIONS,
    InvalidIncidentTransitionError,
    validate_status_transition,
)
from app.models import IncidentStatus


@pytest.mark.parametrize(
    ("current_status", "requested_status"),
    [
        (
            IncidentStatus.DETECTED,
            IncidentStatus.ACKNOWLEDGED,
        ),
        (
            IncidentStatus.ACKNOWLEDGED,
            IncidentStatus.INVESTIGATING,
        ),
        (
            IncidentStatus.INVESTIGATING,
            IncidentStatus.ACTION_RECOMMENDED,
        ),
        (
            IncidentStatus.INVESTIGATING,
            IncidentStatus.REMEDIATING,
        ),
        (
            IncidentStatus.ACTION_RECOMMENDED,
            IncidentStatus.REMEDIATING,
        ),
        (
            IncidentStatus.REMEDIATING,
            IncidentStatus.RESOLVED,
        ),
        (
            IncidentStatus.REMEDIATING,
            IncidentStatus.FAILED_RECOVERY,
        ),
        (
            IncidentStatus.FAILED_RECOVERY,
            IncidentStatus.INVESTIGATING,
        ),
        (
            IncidentStatus.FAILED_RECOVERY,
            IncidentStatus.REMEDIATING,
        ),
    ],
)
def test_allows_valid_incident_transition(
    current_status: IncidentStatus,
    requested_status: IncidentStatus,
) -> None:
    validate_status_transition(
        current_status=current_status,
        requested_status=requested_status,
    )


@pytest.mark.parametrize(
    ("current_status", "requested_status"),
    [
        (
            IncidentStatus.DETECTED,
            IncidentStatus.RESOLVED,
        ),
        (
            IncidentStatus.DETECTED,
            IncidentStatus.REMEDIATING,
        ),
        (
            IncidentStatus.ACKNOWLEDGED,
            IncidentStatus.ACTION_RECOMMENDED,
        ),
        (
            IncidentStatus.ACKNOWLEDGED,
            IncidentStatus.RESOLVED,
        ),
        (
            IncidentStatus.INVESTIGATING,
            IncidentStatus.RESOLVED,
        ),
        (
            IncidentStatus.ACTION_RECOMMENDED,
            IncidentStatus.INVESTIGATING,
        ),
        (
            IncidentStatus.ACTION_RECOMMENDED,
            IncidentStatus.RESOLVED,
        ),
        (
            IncidentStatus.FAILED_RECOVERY,
            IncidentStatus.ACTION_RECOMMENDED,
        ),
        (
            IncidentStatus.RESOLVED,
            IncidentStatus.INVESTIGATING,
        ),
    ],
)
def test_rejects_invalid_incident_transition(
    current_status: IncidentStatus,
    requested_status: IncidentStatus,
) -> None:
    with pytest.raises(
        InvalidIncidentTransitionError,
        match=(
            f"{current_status.value} -> "
            f"{requested_status.value}"
        ),
    ):
        validate_status_transition(
            current_status=current_status,
            requested_status=requested_status,
        )


def test_resolved_incident_has_no_allowed_transitions() -> None:
    assert (
        ALLOWED_TRANSITIONS[IncidentStatus.RESOLVED]
        == set()
    )


def test_repeating_same_status_is_not_a_valid_transition() -> None:
    with pytest.raises(
        InvalidIncidentTransitionError,
        match="already in status ACKNOWLEDGED",
    ):
        validate_status_transition(
            current_status=IncidentStatus.ACKNOWLEDGED,
            requested_status=IncidentStatus.ACKNOWLEDGED,
        )