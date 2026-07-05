from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Incident, IncidentStatus, IncidentSeverity
from app.incidents.schemas import IncidentOut, IncidentDetailOut, TimelineItemOut
from app.incidents.incident_service import (
    acknowledge_incident,
    resolve_incident,
    incident_to_out,
    incident_detail_to_out,
    build_incident_timeline,
)

router = APIRouter(prefix="/api/incidents", tags=["incidents"])
service_router = APIRouter(prefix="/api/services", tags=["service-incidents"])


@router.get("", response_model=list[IncidentOut])
def list_incidents(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    service_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(Incident)

    if status:
        query = query.filter(Incident.status == IncidentStatus(status))

    if severity:
        query = query.filter(Incident.severity == IncidentSeverity(severity))

    if service_id:
        query = query.filter(Incident.service_id == service_id)

    if environment:
        query = query.filter(Incident.environment == environment)

    incidents = query.order_by(Incident.created_at.desc()).all()

    return [incident_to_out(incident) for incident in incidents]


@router.get("/{incident_id}", response_model=IncidentDetailOut)
def get_incident(
    incident_id: UUID,
    db: Session = Depends(get_db),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    return incident_detail_to_out(incident)


@router.post("/{incident_id}/acknowledge", response_model=IncidentOut)
def acknowledge(
    incident_id: UUID,
    db: Session = Depends(get_db),
):
    try:
        incident = acknowledge_incident(db, incident_id)
        return incident_to_out(incident)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{incident_id}/resolve", response_model=IncidentOut)
def resolve(
    incident_id: UUID,
    db: Session = Depends(get_db),
):
    try:
        incident = resolve_incident(db, incident_id)
        return incident_to_out(incident)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{incident_id}/timeline", response_model=list[TimelineItemOut])
def get_incident_timeline(
    incident_id: UUID,
    db: Session = Depends(get_db),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    return build_incident_timeline(db, incident)


@service_router.get("/{service_id}/incidents", response_model=list[IncidentOut])
def get_service_incidents(
    service_id: str,
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(Incident).filter(Incident.service_id == service_id)

    if status:
        query = query.filter(Incident.status == IncidentStatus(status))

    incidents = query.order_by(Incident.created_at.desc()).all()

    return [incident_to_out(incident) for incident in incidents]


@service_router.get("/{service_id}/runtime-timeline", response_model=list[TimelineItemOut])
def get_service_runtime_timeline(
    service_id: str,
    environment: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(Incident).filter(Incident.service_id == service_id)

    if environment:
        query = query.filter(Incident.environment == environment)

    incidents = query.order_by(Incident.created_at.desc()).limit(10).all()

    timeline = []

    for incident in incidents:
        timeline.extend(build_incident_timeline(db, incident))

    timeline.sort(key=lambda item: item["timestamp"])

    return timeline