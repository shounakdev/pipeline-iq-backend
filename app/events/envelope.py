import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from app.events.constants import SCHEMA_VERSION
from app.events.schemas import EventEnvelope


def create_event_envelope(
    *,
    event_type: str,
    correlation_id: str,
    service_id: Optional[str] = None,
    environment: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    event_id: Optional[str] = None,
) -> dict:
    """
    Creates the standard PlatformIQ event envelope.

    Important:
    - All producers must use this helper.
    - Do not manually shape event JSON in routers/tasks.
    """
    envelope = EventEnvelope(
        event_id=event_id or f"evt_{uuid4()}",
        event_type=event_type,
        schema_version=SCHEMA_VERSION,
        correlation_id=correlation_id,
        service_id=service_id,
        environment=environment,
        timestamp=datetime.now(timezone.utc),
        payload=payload or {},
    )

    if hasattr(envelope, "model_dump"):
        return envelope.model_dump(mode="json")

    return json.loads(envelope.json())
