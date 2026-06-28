from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.events.service import (
    get_event_record,
    get_release_timeline,
    list_dead_letter_records,
    list_event_records,
    retry_dead_letter_record,
)


router = APIRouter(prefix="/api", tags=["Events"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def parse_datetime(value: Optional[str]):
    if not value:
        return None

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@router.get("/events")
def api_list_events(
    event_type: Optional[str] = None,
    service_id: Optional[str] = None,
    environment: Optional[str] = None,
    correlation_id: Optional[str] = None,
    status: Optional[str] = None,
    topic: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    events = list_event_records(
        db,
        event_type=event_type,
        service_id=service_id,
        environment=environment,
        correlation_id=correlation_id,
        status=status,
        topic=topic,
        from_date=parse_datetime(from_date),
        to_date=parse_datetime(to_date),
        limit=limit,
        offset=offset,
    )

    return {
        "events": events,
        "count": len(events),
    }


@router.get("/events/{event_id}")
def api_get_event(event_id: str, db: Session = Depends(get_db)):
    event = get_event_record(db, event_id)

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return event


@router.get("/releases/{correlation_id}/timeline")
def api_release_timeline(correlation_id: str, db: Session = Depends(get_db)):
    events = get_release_timeline(db, correlation_id)

    return {
        "correlation_id": correlation_id,
        "events": events,
        "count": len(events),
    }


@router.get("/dead-letter-events")
def api_list_dead_letter_events(
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    events = list_dead_letter_records(
        db,
        status=status,
        limit=limit,
        offset=offset,
    )

    return {
        "dead_letter_events": events,
        "count": len(events),
    }


@router.post("/dead-letter-events/{event_id}/retry")
def api_retry_dead_letter_event(event_id: str, db: Session = Depends(get_db)):
    event = retry_dead_letter_record(db, event_id)

    if not event:
        raise HTTPException(status_code=404, detail="Dead-letter event not found")

    return event