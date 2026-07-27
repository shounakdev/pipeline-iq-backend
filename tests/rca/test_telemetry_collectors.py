from datetime import datetime, timezone

from app.rca.collectors.telemetry.utils import (
    safe_subtract,
    safe_multiplier,
    redact_log_line,
    normalize_error_signature,
    build_incident_window,
)
from app.rca.collectors.telemetry.loki_collector import classify_error


def test_safe_subtract_calculates_after_minus_before():
    assert safe_subtract(12, 5) == 7


def test_safe_subtract_handles_missing_values():
    assert safe_subtract(None, 5) is None
    assert safe_subtract(5, None) is None


def test_safe_multiplier_handles_zero_baseline():
    assert safe_multiplier(10, 0) is None


def test_safe_multiplier_calculates_ratio():
    assert safe_multiplier(200, 100) == 2


def test_build_incident_window_uses_failure_started_at():
    anchor = datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc)

    window = build_incident_window({
        "failure_started_at": anchor,
        "detected_at": None,
    })

    assert window["status"] == "COLLECTED"
    assert window["anchor"] == anchor
    assert window["before_end"] == anchor
    assert window["after_start"] == anchor


def test_build_incident_window_returns_no_data_without_anchor():
    window = build_incident_window({
        "failure_started_at": None,
        "detected_at": None,
    })

    assert window["status"] == "NO_DATA"


def test_redact_log_line_removes_ids_timestamps_and_numbers():
    line = "2026-07-26T10:00:00Z request_id=abc-123 user 991 failed trace_id=xyz-999"

    redacted = redact_log_line(line)

    assert "<timestamp>" in redacted
    assert "request_id=<id>" in redacted
    assert "trace_id=<id>" in redacted
    assert "<num>" in redacted


def test_normalize_error_signature_groups_changing_values():
    first = "2026-07-26T10:00:00Z request_id=req-123 database timeout for user 101"
    second = "2026-07-26T10:01:00Z request_id=req-999 database timeout for user 202"

    assert normalize_error_signature(first) == normalize_error_signature(second)


def test_classify_database_timeout_error():
    assert classify_error("database timeout while querying payments") == "database_timeout_errors"


def test_classify_connection_refused_error():
    assert classify_error("connection refused by inventory-service") == "connection_refused_errors"


def test_classify_out_of_memory_error():
    assert classify_error("pod killed due to out of memory") == "out_of_memory_errors"


def test_classify_uncaught_exception_error():
    assert classify_error("uncaught exception in payment handler") == "uncaught_exception_errors"