from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from app.events.constants import SCHEMA_VERSION


class EventEnvelope(BaseModel):
    event_id: str
    event_type: str
    schema_version: str = SCHEMA_VERSION
    correlation_id: str
    service_id: Optional[str] = None
    environment: Optional[str] = None
    timestamp: datetime
    payload: Dict[str, Any] = Field(default_factory=dict)
