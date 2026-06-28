from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.events.constants import EVENT_TOPIC_MAP
from app.models import EventRecord


SUPPORTED_EVENT_TYPES = set(EVENT_TOPIC_MAP.keys())


def handle_event(db: Session, record: EventRecord) -> None:
    """
    Handles side effects after an event has been consumed.

    Sprint 4 version:
    - Validate supported event types.
    - Keep side effects simple.
    - Add stronger domain updates in later sprints.
    """

    if record.event_type not in SUPPORTED_EVENT_TYPES:
        raise ValueError(f"Unsupported event_type={record.event_type}")

    if record.topic == "deployment.events":
        handle_deployment_event(db, record)

    elif record.topic == "kubernetes.events":
        handle_kubernetes_event(db, record)

    elif record.topic == "audit.events":
        handle_audit_event(db, record)

    record.processing_status = "PROCESSED"
    record.processing_error = None
    record.processed_at = datetime.now(timezone.utc)


def handle_deployment_event(db: Session, record: EventRecord) -> None:
    """
    Optional side effect:
    Update deployment status if your DeploymentRun model exists.
    """

    payload = record.payload or {}
    deployment_id = payload.get("deployment_id")

    if not deployment_id:
        return

    try:
        import app.models as models

        DeploymentRun = getattr(models, "DeploymentRun", None)

        if DeploymentRun is None:
            return

        deployment = db.query(DeploymentRun).filter(DeploymentRun.id == deployment_id).first()

        if deployment is None:
            raise ValueError(f"DeploymentRun not found for deployment_id={deployment_id}")

        if record.event_type.endswith("_STARTED"):
            deployment.status = "RUNNING"
        elif record.event_type.endswith("_COMPLETED"):
            deployment.status = "SUCCESS"
        elif record.event_type.endswith("_FAILED"):
            deployment.status = "FAILED"

    except ValueError:
        raise
    except Exception:
        return


def handle_kubernetes_event(db: Session, record: EventRecord) -> None:
    """
    Sprint 4 version can be no-op.

    Later you can update a kubernetes_workloads table here.
    """
    return


def handle_audit_event(db: Session, record: EventRecord) -> None:
    """
    Sprint 4 version can be no-op because audit may already be written elsewhere.
    """
    return