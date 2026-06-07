import json
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import AuditEvent


def create_audit_event(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> AuditEvent:
    audit_event = AuditEvent(
    id=str(uuid4()),
    actor_id=actor_id,
    action=action,
    entity_type=entity_type,
    entity_id=entity_id,
    details=json.dumps(details),
)

    db.add(audit_event)
    return audit_event