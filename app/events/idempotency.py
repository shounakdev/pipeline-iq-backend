from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import EventRecord


def parse_event_timestamp(value: str | None):
    if not value:
        return None

    if isinstance(value, datetime):
        return value

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def create_event_record_if_new(
    db: Session,
    *,
    envelope: Dict[str, Any],
    topic: str,
) -> Tuple[EventRecord | None, bool]:
    event_id = envelope.get("event_id")

    if not event_id:
        raise ValueError("Missing event_id")

    existing = db.query(EventRecord).filter(EventRecord.event_id == event_id).first()

    if existing:
        return existing, False

    record = EventRecord(
        event_id=event_id,
        event_type=envelope.get("event_type"),
        schema_version=envelope.get("schema_version"),
        topic=topic,
        correlation_id=envelope.get("correlation_id"),
        service_id=envelope.get("service_id"),
        environment=envelope.get("environment"),
        timestamp=parse_event_timestamp(envelope.get("timestamp")),
        payload=envelope.get("payload") or {},
        raw_event=envelope,
        processing_status="RECEIVED",
    )

    db.add(record)

    try:
        db.flush()
        return record, True

    except IntegrityError:
        db.rollback()

        existing_after_error = (
            db.query(EventRecord)
            .filter(EventRecord.event_id == event_id)
            .first()
        )

        if existing_after_error:
            return existing_after_error, False

        # Important:
        # If no existing record is found, this was not a real duplicate.
        # Re-raise so the consumer can dead-letter it instead of pretending
        # it was safely ignored.
        raise