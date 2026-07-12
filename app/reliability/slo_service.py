from sqlalchemy.orm import Session

from app.models import Service, SLODefinition
from app.reliability.schemas import SLOCreate


def get_service(
    db: Session,
    service_id: str,
) -> Service | None:
    return (
        db.query(Service)
        .filter(Service.id == service_id)
        .first()
    )


def create_slo(
    db: Session,
    service_id: str,
    payload: SLOCreate,
) -> SLODefinition:
    slo_definition = SLODefinition(
        service_id=service_id,
        metric_type=payload.metric_type,
        target_value=payload.target_value,
        window_minutes=payload.window_minutes,
        severity_on_breach=payload.severity_on_breach,
        enabled=payload.enabled,
    )

    try:
        db.add(slo_definition)
        db.commit()
        db.refresh(slo_definition)
    except Exception:
        db.rollback()
        raise

    return slo_definition


def list_slos(
    db: Session,
    service_id: str,
) -> list[SLODefinition]:
    return (
        db.query(SLODefinition)
        .filter(SLODefinition.service_id == service_id)
        .order_by(SLODefinition.created_at.desc())
        .all()
    )


def list_enabled_slos(
    db: Session,
    service_id: str,
) -> list[SLODefinition]:
    return (
        db.query(SLODefinition)
        .filter(
            SLODefinition.service_id == service_id,
            SLODefinition.enabled.is_(True),
        )
        .order_by(SLODefinition.created_at.asc())
        .all()
    )


def get_slo_definition(
    db: Session,
    slo_definition_id: str,
) -> SLODefinition | None:
    return (
        db.query(SLODefinition)
        .filter(SLODefinition.id == slo_definition_id)
        .first()
    )