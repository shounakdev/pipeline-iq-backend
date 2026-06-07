from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit.service import create_audit_event
from app.database import get_db
from app.models import (
    AuditEvent,
    Environment,
    Pipeline,
    Project,
    Repository,
    Service,
)
from app.schemas import (
    AuditEventResponse,
    EnvironmentCreate,
    EnvironmentResponse,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectResponse,
    RepositoryCreate,
    RepositoryResponse,
    ServiceCreate,
    ServiceDetailResponse,
    ServicePipelineTriggerRequest,
    ServicePipelineTriggerResponse,
    ServiceResponse,
)
from app.tasks import execute_pipeline_task


router = APIRouter(tags=["PlatformIQ Control Plane"])


@router.post("/projects", response_model=ProjectResponse)
def create_project(request: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(
        id=str(uuid4()),
        name=request.name,
        description=request.description,
        created_by=request.created_by,
        created_at=datetime.utcnow(),
    )

    db.add(project)

    create_audit_event(
        db=db,
        action="PROJECT_CREATED",
        entity_type="Project",
        entity_id=project.id,
        actor_id=request.created_by,
        details={
            "name": project.name,
            "description": project.description,
        },
    )

    db.commit()
    db.refresh(project)

    return project


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return project


@router.post(
    "/projects/{project_id}/services",
    response_model=ServiceResponse,
)
def create_service(
    project_id: str,
    request: ServiceCreate,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    service = Service(
        id=str(uuid4()),
        project_id=project_id,
        name=request.name,
        description=request.description,
        service_type=request.service_type,
        owner=request.owner,
        created_at=datetime.utcnow(),
    )

    db.add(service)

    create_audit_event(
        db=db,
        action="SERVICE_CREATED",
        entity_type="Service",
        entity_id=service.id,
        actor_id=None,
        details={
            "project_id": project_id,
            "name": service.name,
            "service_type": service.service_type,
        },
    )

    db.commit()
    db.refresh(service)

    return service


@router.get(
    "/projects/{project_id}/services",
    response_model=list[ServiceResponse],
)
def list_project_services(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return (
        db.query(Service)
        .filter(Service.project_id == project_id)
        .order_by(Service.created_at.desc())
        .all()
    )


@router.get(
    "/projects/{project_id}/services/{service_id}",
    response_model=ServiceDetailResponse,
)
def get_service(
    project_id: str,
    service_id: str,
    db: Session = Depends(get_db),
):
    service = (
        db.query(Service)
        .filter(
            Service.id == service_id,
            Service.project_id == project_id,
        )
        .first()
    )

    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    return service


@router.post(
    "/projects/{project_id}/services/{service_id}/repositories",
    response_model=RepositoryResponse,
)
def create_repository(
    project_id: str,
    service_id: str,
    request: RepositoryCreate,
    db: Session = Depends(get_db),
):
    service = (
        db.query(Service)
        .filter(
            Service.id == service_id,
            Service.project_id == project_id,
        )
        .first()
    )

    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    repository = Repository(
        id=str(uuid4()),
        service_id=service_id,
        provider=request.provider,
        repo_url=str(request.repo_url),
        default_branch=request.default_branch,
        created_at=datetime.utcnow(),
    )

    db.add(repository)

    create_audit_event(
        db=db,
        action="REPOSITORY_CONNECTED",
        entity_type="Repository",
        entity_id=repository.id,
        actor_id=service.owner,
        details={
            "project_id": project_id,
            "service_id": service_id,
            "provider": repository.provider,
            "repo_url": repository.repo_url,
            "default_branch": repository.default_branch,
        },
    )

    db.commit()
    db.refresh(repository)

    return repository


@router.post(
    "/projects/{project_id}/services/{service_id}/environments",
    response_model=EnvironmentResponse,
)
def create_environment(
    project_id: str,
    service_id: str,
    request: EnvironmentCreate,
    db: Session = Depends(get_db),
):
    service = (
        db.query(Service)
        .filter(
            Service.id == service_id,
            Service.project_id == project_id,
        )
        .first()
    )

    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    environment = Environment(
        id=str(uuid4()),
        service_id=service_id,
        name=request.name,
        is_active=request.is_active,
        created_at=datetime.utcnow(),
    )

    db.add(environment)

    create_audit_event(
        db=db,
        action="ENVIRONMENT_CREATED",
        entity_type="Environment",
        entity_id=environment.id,
        actor_id=service.owner,
        details={
            "project_id": project_id,
            "service_id": service_id,
            "name": environment.name,
            "is_active": environment.is_active,
        },
    )

    db.commit()
    db.refresh(environment)

    return environment


@router.post(
    "/projects/{project_id}/services/{service_id}/trigger-pipeline",
    response_model=ServicePipelineTriggerResponse,
)
def trigger_service_pipeline(
    project_id: str,
    service_id: str,
    request: ServicePipelineTriggerRequest,
    db: Session = Depends(get_db),
):
    service = (
        db.query(Service)
        .filter(
            Service.id == service_id,
            Service.project_id == project_id,
        )
        .first()
    )

    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    repository = (
        db.query(Repository)
        .filter(Repository.service_id == service_id)
        .order_by(Repository.created_at.desc())
        .first()
    )

    if not repository:
        raise HTTPException(
            status_code=400,
            detail="No repository connected to this service",
        )

    branch = request.branch or repository.default_branch or "main"
    pipeline_id = str(uuid4())

    pipeline = Pipeline(
        id=pipeline_id,
        repo_url=repository.repo_url,
        branch=branch,
        status="PENDING",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    db.add(pipeline)

    create_audit_event(
        db=db,
        action="SERVICE_PIPELINE_TRIGGERED",
        entity_type="Pipeline",
        entity_id=pipeline_id,
        actor_id=service.owner,
        details={
            "project_id": project_id,
            "service_id": service_id,
            "repository_id": repository.id,
            "repo_url": repository.repo_url,
            "branch": branch,
        },
    )

    db.commit()
    db.refresh(pipeline)

    execute_pipeline_task.apply_async(
        args=[pipeline_id],
        queue="pipeline_queue",
        ignore_result=True,
    )

    return ServicePipelineTriggerResponse(
        pipeline_id=pipeline_id,
        service_id=service_id,
        repository_id=repository.id,
        repo_url=repository.repo_url,
        branch=branch,
        status="PENDING",
        message="Service pipeline triggered successfully",
    )


@router.get("/audit-events", response_model=list[AuditEventResponse])
def list_audit_events(db: Session = Depends(get_db)):
    return (
        db.query(AuditEvent)
        .order_by(AuditEvent.created_at.desc())
        .limit(100)
        .all()
    )