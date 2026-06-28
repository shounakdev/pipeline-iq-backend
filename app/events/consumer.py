import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from confluent_kafka import Consumer

from app.database import SessionLocal
from app.events.handlers import handle_event
from app.events.idempotency import create_event_record_if_new
from app.models import DeadLetterEvent


KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "platformiq-kafka:9092")
KAFKA_CONSUMER_GROUP_ID = os.getenv("KAFKA_CONSUMER_GROUP_ID", "platformiq-event-consumers")
KAFKA_CONSUMER_BATCH_SIZE = int(os.getenv("KAFKA_CONSUMER_BATCH_SIZE", "25"))

KAFKA_CONSUMER_TOPICS = os.getenv(
    "KAFKA_CONSUMER_TOPICS",
    "pipeline.events,deployment.events,kubernetes.events,audit.events",
).split(",")


REQUIRED_ENVELOPE_FIELDS = [
    "event_id",
    "event_type",
    "schema_version",
    "correlation_id",
    "timestamp",
    "payload",
]


def validate_envelope(envelope: Dict[str, Any]) -> None:
    if not isinstance(envelope, dict):
        raise ValueError("Event envelope must be a JSON object")

    missing = [field for field in REQUIRED_ENVELOPE_FIELDS if field not in envelope]

    if missing:
        raise ValueError(f"Invalid event envelope. Missing fields: {missing}")

    if not envelope.get("event_id"):
        raise ValueError("Missing event_id")

    if not envelope.get("event_type"):
        raise ValueError("Missing event_type")

    if not isinstance(envelope.get("payload"), dict):
        raise ValueError("payload must be a JSON object")


def save_dead_letter_event(
    *,
    topic: str | None,
    raw_event: Any,
    error_reason: str,
) -> None:
    db = SessionLocal()

    try:
        envelope = raw_event if isinstance(raw_event, dict) else {}

        event_id = envelope.get("event_id") or f"dlq_{uuid.uuid4()}"

        existing = db.query(DeadLetterEvent).filter(
            DeadLetterEvent.event_id == event_id
        ).first()

        if existing:
            existing.retry_count = (existing.retry_count or 0) + 1
            existing.error_reason = error_reason
            existing.status = "OPEN"
            existing.updated_at = datetime.now(timezone.utc)
        else:
            dead = DeadLetterEvent(
                event_id=event_id,
                event_type=envelope.get("event_type"),
                topic=topic,
                correlation_id=envelope.get("correlation_id"),
                service_id=envelope.get("service_id"),
                environment=envelope.get("environment"),
                raw_event=raw_event if isinstance(raw_event, dict) else {"raw": str(raw_event)},
                payload=envelope.get("payload") if isinstance(envelope.get("payload"), dict) else None,
                error_reason=error_reason,
                status="OPEN",
                retry_count=0,
            )
            db.add(dead)

        db.commit()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def process_event_message(*, topic: str, raw_value: str) -> str:
    db = SessionLocal()

    try:
        try:
            envelope = json.loads(raw_value)
        except Exception as exc:
            save_dead_letter_event(
                topic=topic,
                raw_event={"raw": raw_value},
                error_reason=f"Invalid JSON: {exc}",
            )
            return "DEAD_LETTER"

        try:
            validate_envelope(envelope)

            record, is_new = create_event_record_if_new(
                db,
                envelope=envelope,
                topic=topic,
            )

            if not is_new:
                db.commit()
                return "DUPLICATE_IGNORED"

            handle_event(db, record)
            db.commit()

            return "PROCESSED"

        except Exception as exc:
            db.rollback()

            save_dead_letter_event(
                topic=topic,
                raw_event=envelope,
                error_reason=str(exc),
            )

            return "DEAD_LETTER"

    finally:
        db.close()


def get_kafka_consumer() -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
            "group.id": KAFKA_CONSUMER_GROUP_ID,
            "client.id": "platformiq-event-consumer",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )


def run_event_consumer_once(batch_size: int | None = None) -> int:
    consumer = get_kafka_consumer()
    processed_count = 0

    try:
        consumer.subscribe([topic.strip() for topic in KAFKA_CONSUMER_TOPICS if topic.strip()])

        messages = consumer.consume(
            num_messages=batch_size or KAFKA_CONSUMER_BATCH_SIZE,
            timeout=5.0,
        )

        for message in messages:
            if message is None:
                continue

            if message.error():
                continue

            topic = message.topic()
            raw_value = message.value().decode("utf-8")

            process_event_message(topic=topic, raw_value=raw_value)

            consumer.commit(message=message, asynchronous=False)
            processed_count += 1

        return processed_count

    finally:
        consumer.close()