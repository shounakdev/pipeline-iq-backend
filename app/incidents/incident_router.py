import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db


router = APIRouter(
    prefix="/api/incidents",
    tags=["incidents"],
)

service_runtime_router = APIRouter(
    prefix="/api/services",
    tags=["runtime-timeline"],
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def row_to_dict(row) -> dict[str, Any]:
    return dict(row._mapping)


def add_incident_event(
    db: Session,
    incident_id: str,
    event_type: str,
    message: str,
    metadata: dict[str, Any] | None = None,
):
    db.execute(
        text(
            """
            insert into incident_events (
                id,
                incident_id,
                event_type,
                message,
                metadata,
                created_at
            )
            values (
                :id,
                :incident_id,
                :event_type,
                :message,
                cast(:metadata as jsonb),
                :created_at
            )
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "incident_id": incident_id,
            "event_type": event_type,
            "message": message,
            "metadata": "{}" if metadata is None else json.dumps(metadata),
            "created_at": utc_now(),
        },
    )


@router.get("")
def list_incidents(db: Session = Depends(get_db)):
    result = db.execute(
        text(
            """
            select
                id,
                title,
                description,
                severity,
                status,
                service_id,
                environment,
                correlation_id,
                triggered_by_event_id,
                started_at,
                resolved_at,
                created_at,
                updated_at
            from incidents
            order by created_at desc
            """
        )
    ).fetchall()

    return [row_to_dict(row) for row in result]


@router.get("/{incident_id}")
def get_incident(incident_id: str, db: Session = Depends(get_db)):
    result = db.execute(
        text(
            """
            select
                id,
                title,
                description,
                severity,
                status,
                service_id,
                environment,
                correlation_id,
                triggered_by_event_id,
                started_at,
                resolved_at,
                created_at,
                updated_at
            from incidents
            where id = :incident_id
            """
        ),
        {"incident_id": incident_id},
    ).fetchone()

    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    return row_to_dict(result)


@router.get("/{incident_id}/timeline")
def get_incident_timeline(incident_id: str, db: Session = Depends(get_db)):
    incident = db.execute(
        text(
            """
            select id, service_id, environment, correlation_id, created_at
            from incidents
            where id = :incident_id
            """
        ),
        {"incident_id": incident_id},
    ).fetchone()

    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident_data = row_to_dict(incident)

    events = db.execute(
        text(
            """
            select
                id,
                incident_id,
                event_type,
                message,
                metadata,
                created_at
            from incident_events
            where incident_id = :incident_id
            order by created_at desc
            """
        ),
        {"incident_id": incident_id},
    ).fetchall()

    timeline = []

    for event in events:
        item = row_to_dict(event)
        timeline.append(
            {
                "source": "incident_events",
                "type": item["event_type"],
                "message": item["message"],
                "metadata": item.get("metadata"),
                "timestamp": item["created_at"],
            }
        )

    snapshots = db.execute(
        text(
            """
            select
                id,
                service_id,
                service_name,
                environment,
                status,
                latency_ms,
                error_rate,
                pod_restart_count,
                replica_count,
                available_replicas,
                created_at
            from service_health_snapshots
            where service_id = :service_id
              and environment = :environment
            order by created_at desc
            limit 20
            """
        ),
        {
            "service_id": incident_data["service_id"],
            "environment": incident_data["environment"],
        },
    ).fetchall()

    for snapshot in snapshots:
        item = row_to_dict(snapshot)
        timeline.append(
            {
                "source": "service_health_snapshots",
                "type": "HEALTH_SNAPSHOT",
                "message": f"Service health snapshot recorded with status {item['status']}",
                "metadata": item,
                "timestamp": item["created_at"],
            }
        )

    timeline.sort(
        key=lambda x: str(x.get("timestamp") or ""),
        reverse=True,
    )

    return {
        "incident_id": incident_id,
        "timeline": timeline,
    }


@router.post("/{incident_id}/acknowledge")
def acknowledge_incident(incident_id: str, db: Session = Depends(get_db)):
    incident = db.execute(
        text(
            """
            select id, status
            from incidents
            where id = :incident_id
            """
        ),
        {"incident_id": incident_id},
    ).fetchone()

    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident_data = row_to_dict(incident)

    if incident_data["status"] == "RESOLVED":
        raise HTTPException(
            status_code=400,
            detail="Cannot acknowledge a resolved incident",
        )

    now = utc_now()

    db.execute(
        text(
            """
            update incidents
            set status = 'ACKNOWLEDGED',
                updated_at = :updated_at
            where id = :incident_id
            """
        ),
        {
            "incident_id": incident_id,
            "updated_at": now,
        },
    )

    add_incident_event(
        db=db,
        incident_id=incident_id,
        event_type="INCIDENT_ACKNOWLEDGED",
        message="Incident acknowledged",
        metadata={},
    )

    db.commit()

    return {
        "incident_id": incident_id,
        "status": "ACKNOWLEDGED",
        "message": "Incident acknowledged",
    }


@router.post("/{incident_id}/resolve")
def resolve_incident(incident_id: str, db: Session = Depends(get_db)):
    incident = db.execute(
        text(
            """
            select id, status
            from incidents
            where id = :incident_id
            """
        ),
        {"incident_id": incident_id},
    ).fetchone()

    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    now = utc_now()

    db.execute(
        text(
            """
            update incidents
            set status = 'RESOLVED',
                resolved_at = :resolved_at,
                updated_at = :updated_at
            where id = :incident_id
            """
        ),
        {
            "incident_id": incident_id,
            "resolved_at": now,
            "updated_at": now,
        },
    )

    add_incident_event(
        db=db,
        incident_id=incident_id,
        event_type="INCIDENT_RESOLVED",
        message="Incident resolved",
        metadata={},
    )

    db.commit()

    return {
        "incident_id": incident_id,
        "status": "RESOLVED",
        "message": "Incident resolved",
    }


@service_runtime_router.get("/{service_id}/incidents")
def get_service_incidents(service_id: str, db: Session = Depends(get_db)):
    result = db.execute(
        text(
            """
            select
                id,
                title,
                description,
                severity,
                status,
                service_id,
                environment,
                correlation_id,
                triggered_by_event_id,
                started_at,
                resolved_at,
                created_at,
                updated_at
            from incidents
            where service_id = :service_id
            order by created_at desc
            """
        ),
        {"service_id": service_id},
    ).fetchall()

    return [row_to_dict(row) for row in result]


@service_runtime_router.get("/{service_id}/runtime-timeline")
def get_service_runtime_timeline(service_id: str, db: Session = Depends(get_db)):
    timeline = []

    incident_events = db.execute(
        text(
            """
            select
                ie.id,
                ie.incident_id,
                ie.event_type,
                ie.message,
                ie.metadata,
                ie.created_at
            from incident_events ie
            join incidents i on i.id = ie.incident_id
            where i.service_id = :service_id
            order by ie.created_at desc
            limit 50
            """
        ),
        {"service_id": service_id},
    ).fetchall()

    for event in incident_events:
        item = row_to_dict(event)
        timeline.append(
            {
                "source": "incident_events",
                "type": item["event_type"],
                "message": item["message"],
                "metadata": item.get("metadata"),
                "timestamp": item["created_at"],
            }
        )

    health_snapshots = db.execute(
        text(
            """
            select
                id,
                service_id,
                service_name,
                environment,
                status,
                latency_ms,
                error_rate,
                pod_restart_count,
                replica_count,
                available_replicas,
                created_at
            from service_health_snapshots
            where service_id = :service_id
            order by created_at desc
            limit 50
            """
        ),
        {"service_id": service_id},
    ).fetchall()

    for snapshot in health_snapshots:
        item = row_to_dict(snapshot)
        timeline.append(
            {
                "source": "service_health_snapshots",
                "type": "HEALTH_SNAPSHOT",
                "message": f"Service health snapshot recorded with status {item['status']}",
                "metadata": item,
                "timestamp": item["created_at"],
            }
        )

    timeline.sort(
        key=lambda x: str(x.get("timestamp") or ""),
        reverse=True,
    )

    return {
        "service_id": service_id,
        "timeline": timeline,
    }