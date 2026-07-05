from sqlalchemy.orm import Session

from app.models import ServiceHealthSnapshot


def get_latest_service_health(db: Session, service_id: str):
    return (
        db.query(ServiceHealthSnapshot)
        .filter(ServiceHealthSnapshot.service_id == service_id)
        .order_by(ServiceHealthSnapshot.created_at.desc())
        .first()
    )


def get_service_health_history(db: Session, service_id: str, limit: int = 50):
    return (
        db.query(ServiceHealthSnapshot)
        .filter(ServiceHealthSnapshot.service_id == service_id)
        .order_by(ServiceHealthSnapshot.created_at.desc())
        .limit(limit)
        .all()
    )


def get_health_summary(db: Session):
    latest_rows = (
        db.query(ServiceHealthSnapshot)
        .order_by(ServiceHealthSnapshot.created_at.desc())
        .all()
    )

    seen = set()
    summary = []

    for row in latest_rows:
        key = (row.service_id, row.environment)

        if key in seen:
            continue

        seen.add(key)
        summary.append(row)

    return summary