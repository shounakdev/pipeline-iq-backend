import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.events.kafka_producer import publish_event_to_kafka
from app.models import OutboxEvent


OUTBOX_BATCH_SIZE = int(os.getenv("KAFKA_OUTBOX_BATCH_SIZE", "25"))
OUTBOX_MAX_RETRIES = int(os.getenv("KAFKA_OUTBOX_MAX_RETRIES", "5"))


def utc_now():
    return datetime.now(timezone.utc)


def build_envelope_from_outbox(event: OutboxEvent) -> dict:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "correlation_id": event.correlation_id,
        "service_id": event.service_id,
        "environment": event.environment,
        "timestamp": event.created_at.isoformat()
        if event.created_at
        else utc_now().isoformat(),
        "payload": event.payload or {},
    }


def publish_pending_outbox_events(db: Session) -> int:
    events = (
        db.query(OutboxEvent)
        .filter(OutboxEvent.status == "PENDING")
        .order_by(OutboxEvent.created_at.asc())
        .limit(OUTBOX_BATCH_SIZE)
        .all()
    )

    published_count = 0

    for event in events:
        event_db_id = event.id

        try:
            event.status = "PUBLISHING"
            event.updated_at = utc_now()
            db.commit()
            db.refresh(event)

            envelope = build_envelope_from_outbox(event)

            publish_event_to_kafka(
                topic=event.topic,
                envelope=envelope,
            )

            event.status = "PUBLISHED"
            event.published_at = utc_now()
            event.last_error = None
            event.updated_at = utc_now()

            published_count += 1

        except Exception as exc:
            db.rollback()

            failed_event = (
                db.query(OutboxEvent)
                .filter(OutboxEvent.id == event_db_id)
                .first()
            )

            if failed_event:
                failed_event.retry_count = (failed_event.retry_count or 0) + 1
                failed_event.last_error = str(exc)[:2000]
                failed_event.updated_at = utc_now()

                if failed_event.retry_count >= OUTBOX_MAX_RETRIES:
                    failed_event.status = "FAILED"
                else:
                    failed_event.status = "PENDING"

        finally:
            db.commit()

    return published_count


def run_outbox_publisher_once() -> int:
    db = SessionLocal()

    try:
        return publish_pending_outbox_events(db)
    finally:
        db.close()
