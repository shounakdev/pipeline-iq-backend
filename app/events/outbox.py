from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.events.constants import EVENT_TOPIC_MAP
from app.events.envelope import create_event_envelope
from app.models import OutboxEvent


def create_outbox_event(
    db: Session,
    *,
    event_type: str,
    correlation_id: str,
    service_id: Optional[str] = None,
    environment: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    topic: Optional[str] = None,
) -> OutboxEvent:
    """
    Creates an outbox event inside the current DB transaction.

    Important:
    - This function does NOT commit.
    - Caller must commit after saving both business data and outbox event.
    """
    resolved_topic = topic or EVENT_TOPIC_MAP.get(event_type)

    if not resolved_topic:
        raise ValueError(f"No Kafka topic mapped for event_type={event_type}")

    envelope = create_event_envelope(
        event_type=event_type,
        correlation_id=correlation_id,
        service_id=service_id,
        environment=environment,
        payload=payload or {},
    )

    outbox_event = OutboxEvent(
        event_id=envelope["event_id"],
        topic=resolved_topic,
        event_type=envelope["event_type"],
        schema_version=envelope["schema_version"],
        correlation_id=envelope["correlation_id"],
        service_id=envelope.get("service_id"),
        environment=envelope.get("environment"),
        payload=envelope["payload"],
        status="PENDING",
        retry_count=0,
    )

    db.add(outbox_event)
    return outbox_event
