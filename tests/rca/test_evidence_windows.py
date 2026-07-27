from datetime import datetime, timezone

from app.rca.collectors.orchestrator import calculate_evidence_window


def test_evidence_window_uses_failure_started_at_as_anchor():
    failure_started_at = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    detected_at = datetime(2026, 7, 25, 10, 5, tzinfo=timezone.utc)
    current_time = datetime(2026, 7, 25, 10, 30, tzinfo=timezone.utc)

    window = calculate_evidence_window(
        failure_started_at=failure_started_at,
        detected_at=detected_at,
        current_time=current_time,
    )

    assert window["before_window_start"].minute == 45
    assert window["before_window_end"].minute == 59
    assert window["after_window_start"].minute == 0
    assert window["after_window_end"].minute == 15


def test_evidence_window_falls_back_to_detected_at():
    detected_at = datetime(2026, 7, 25, 10, 5, tzinfo=timezone.utc)
    current_time = datetime(2026, 7, 25, 10, 10, tzinfo=timezone.utc)

    window = calculate_evidence_window(
        failure_started_at=None,
        detected_at=detected_at,
        current_time=current_time,
    )

    assert window["after_window_start"] == detected_at
    assert window["after_window_end"] == current_time