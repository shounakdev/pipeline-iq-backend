import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.events.consumer import validate_envelope
from app.events.handlers import handle_event
from app.events.idempotency import create_event_record_if_new
from app.events.outbox import create_outbox_event
from app.models import DeadLetterEvent, EventRecord


def record_platform_event(
    db: Session,
    *,
    event_type: str,
    correlation_id: str,
    service_id: Optional[str] = None,
    environment: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
):
    """
    High-level event service used by routers/tasks.

    This keeps event creation consistent across:
    - PipelineIQ
    - deployments
    - Kubernetes runtime checks
    - audit
    - remediation
    """
    return create_outbox_event(
        db,
        event_type=event_type,
        correlation_id=correlation_id,
        service_id=service_id,
        environment=environment,
        payload=payload or {},
    )


def serialize_event_record(event: EventRecord) -> dict:
    return {
        "id": event.id,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "topic": event.topic,
        "correlation_id": event.correlation_id,
        "service_id": event.service_id,
        "environment": event.environment,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "payload": event.payload,
        "raw_event": event.raw_event,
        "processing_status": event.processing_status,
        "processing_error": event.processing_error,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "processed_at": event.processed_at.isoformat() if event.processed_at else None,
    }


def serialize_dead_letter_event(event: DeadLetterEvent) -> dict:
    return {
        "id": event.id,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "topic": event.topic,
        "correlation_id": event.correlation_id,
        "service_id": event.service_id,
        "environment": event.environment,
        "raw_event": event.raw_event,
        "payload": event.payload,
        "error_reason": event.error_reason,
        "status": event.status,
        "retry_count": event.retry_count,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
        "last_retry_at": event.last_retry_at.isoformat() if event.last_retry_at else None,
    }


def list_event_records(
    db: Session,
    *,
    event_type: Optional[str] = None,
    service_id: Optional[str] = None,
    environment: Optional[str] = None,
    correlation_id: Optional[str] = None,
    status: Optional[str] = None,
    topic: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
):
    query = db.query(EventRecord)

    if event_type:
        query = query.filter(EventRecord.event_type == event_type)

    if service_id:
        query = query.filter(EventRecord.service_id == service_id)

    if environment:
        query = query.filter(EventRecord.environment == environment)

    if correlation_id:
        query = query.filter(EventRecord.correlation_id == correlation_id)

    if status:
        query = query.filter(EventRecord.processing_status == status)

    if topic:
        query = query.filter(EventRecord.topic == topic)

    if from_date:
        query = query.filter(EventRecord.timestamp >= from_date)

    if to_date:
        query = query.filter(EventRecord.timestamp <= to_date)

    events = (
        query.order_by(
            EventRecord.timestamp.desc().nullslast(),
            EventRecord.created_at.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [serialize_event_record(event) for event in events]


def get_event_record(db: Session, event_id: str):
    event = db.query(EventRecord).filter(EventRecord.event_id == event_id).first()

    if not event:
        return None

    return serialize_event_record(event)


def get_release_timeline(db: Session, correlation_id: str):
    events = (
        db.query(EventRecord)
        .filter(EventRecord.correlation_id == correlation_id)
        .order_by(
            EventRecord.timestamp.asc().nullslast(),
            EventRecord.created_at.asc(),
        )
        .all()
    )

    return [serialize_event_record(event) for event in events]


def list_dead_letter_records(
    db: Session,
    *,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    query = db.query(DeadLetterEvent)

    if status:
        query = query.filter(DeadLetterEvent.status == status)

    events = (
        query.order_by(DeadLetterEvent.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [serialize_dead_letter_event(event) for event in events]


def retry_dead_letter_record(db: Session, event_id: str):
    dead = db.query(DeadLetterEvent).filter(DeadLetterEvent.event_id == event_id).first()

    if not dead:
        return None

    try:
        envelope = dead.raw_event or {}

        if isinstance(envelope, str):
            envelope = json.loads(envelope)

        validate_envelope(envelope)

        record, is_new = create_event_record_if_new(
            db,
            envelope=envelope,
            topic=dead.topic or "dead-letter.events",
        )

        if is_new:
            handle_event(db, record)

        dead.status = "RESOLVED"
        dead.retry_count = (dead.retry_count or 0) + 1
        dead.last_retry_at = datetime.now(timezone.utc)
        dead.updated_at = datetime.now(timezone.utc)

        db.commit()

        return serialize_dead_letter_event(dead)

    except Exception as exc:
        db.rollback()

        dead = db.query(DeadLetterEvent).filter(DeadLetterEvent.event_id == event_id).first()

        if not dead:
            return None

        dead.status = "FAILED"
        dead.retry_count = (dead.retry_count or 0) + 1
        dead.error_reason = str(exc)
        dead.last_retry_at = datetime.now(timezone.utc)
        dead.updated_at = datetime.now(timezone.utc)

        db.commit()

        return serialize_dead_letter_event(dead)