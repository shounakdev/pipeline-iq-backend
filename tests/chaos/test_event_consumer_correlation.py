import json
from datetime import datetime, timezone

from app.events import consumer
from app.events.handlers import handle_telemetry_alert_event
from app.models import EventRecord, IncidentStatus


class FakeQuery:
    def filter(self, *args):
        return self

    def first(self):
        return None


class FakeSession:
    def __init__(self):
        self.committed = False
        self.closed = False
        self.added = []

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        self.closed = True

    def query(self, model):
        return FakeQuery()

    def add(self, value):
        self.added.append(value)

    def flush(self):
        pass


def test_consumed_event_is_correlated_before_commit(monkeypatch):
    db = FakeSession()
    record = object()
    calls = []

    monkeypatch.setattr(consumer, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        consumer,
        "create_event_record_if_new",
        lambda session, *, envelope, topic: (record, True),
    )
    monkeypatch.setattr(
        consumer,
        "handle_event",
        lambda session, value: calls.append(
            ("handled", session, value)
        ),
    )
    monkeypatch.setattr(
        consumer,
        "correlate_event",
        lambda session, value: calls.append(
            ("correlated", session, value)
        ),
    )

    result = consumer.process_event_message(
        topic="telemetry.alerts",
        raw_value=json.dumps(
            {
                "event_id": "event-1",
                "event_type": "SERVICE_DOWN",
                "schema_version": "1.0",
                "correlation_id": "correlation-1",
                "timestamp": "2026-08-09T11:04:45Z",
                "payload": {"snapshot_id": "snapshot-1"},
            }
        ),
    )

    assert result == "PROCESSED"
    assert [item[0] for item in calls] == [
        "handled",
        "correlated",
    ]
    assert db.committed is True
    assert db.closed is True


def test_legacy_alert_handler_uses_current_incident_fields():
    db = FakeSession()
    occurred_at = datetime(
        2026,
        8,
        9,
        11,
        45,
        43,
        tzinfo=timezone.utc,
    )
    record = EventRecord(
        event_id="event-live-alert",
        event_type="SERVICE_DOWN",
        topic="telemetry.alerts",
        correlation_id="snapshot-live",
        service_id="service-payment",
        environment="staging",
        timestamp=occurred_at,
        payload={
            "snapshot_id": "snapshot-live",
            "severity": "CRITICAL",
        },
        raw_event={
            "service_name": "payment-service",
            "environment": "staging",
        },
    )

    handle_telemetry_alert_event(db, record)

    assert len(db.added) == 1
    incident = db.added[0]
    assert incident.primary_service_id == "service-payment"
    assert incident.environment == "staging"
    assert incident.status == IncidentStatus.DETECTED
    assert incident.triggered_by_event_id == "event-live-alert"
    assert incident.detected_at == occurred_at