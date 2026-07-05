import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import relationship

from app.database import Base


class Pipeline(Base):
    __tablename__ = "pipelines"

    id = Column(String, primary_key=True, index=True)

    repo_url = Column(Text, nullable=False)
    branch = Column(String, nullable=False, default="main")
    status = Column(String, nullable=False, default="PENDING")

    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    stage = Column(String, default="QUEUED")
    failure_reason = Column(Text, nullable=True)

    commit_sha = Column(String, nullable=True)
    commit_message = Column(Text, nullable=True)

    build_status = Column(String, default="NOT_STARTED")
    test_status = Column(String, default="NOT_STARTED")
    sonar_status = Column(String, default="NOT_STARTED")
    trivy_status = Column(String, default="NOT_STARTED")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    quality_score = Column(Float, nullable=True)
    coverage = Column(Float, nullable=True)

    bugs = Column(Integer, default=0)
    vulnerabilities = Column(Integer, default=0)
    code_smells = Column(Integer, default=0)
    duplicated_lines_density = Column(Float, nullable=True)
    quality_gate = Column(String, nullable=True)
    sonar_report_url = Column(Text, nullable=True)
    sonar_issues = Column(JSON, nullable=True)

    trivy_critical = Column(Integer, default=0)
    trivy_high = Column(Integer, default=0)
    trivy_medium = Column(Integer, default=0)
    trivy_low = Column(Integer, default=0)
    trivy_unknown = Column(Integer, default=0)
    trivy_total = Column(Integer, default=0)
    trivy_report = Column(JSON, nullable=True)

    risk_score = Column(Float, nullable=True)
    risk_level = Column(String, nullable=True)
    risk_summary = Column(Text, nullable=True)

    ai_summary = Column(Text, nullable=True)
    recommendations = Column(JSON, nullable=True)

    logs = relationship(
        "PipelineLog",
        back_populates="pipeline",
        cascade="all, delete-orphan",
    )

    analysis = relationship(
        "Analysis",
        back_populates="pipeline",
        uselist=False,
        cascade="all, delete-orphan",
    )


class PipelineLog(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, index=True)
    pipeline_id = Column(String, ForeignKey("pipelines.id"))
    log_text = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    pipeline = relationship("Pipeline", back_populates="logs")


class Analysis(Base):
    __tablename__ = "analysis"

    id = Column(Integer, primary_key=True, index=True)
    pipeline_id = Column(String, ForeignKey("pipelines.id"))

    failure_reason = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    suggestion = Column(Text, nullable=True)

    final_status = Column(String, nullable=True)
    report_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    pipeline = relationship("Pipeline", back_populates="analysis")


def generate_uuid():
    return str(uuid.uuid4())


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", String, ForeignKey("users.id"), primary_key=True),
    Column("role_id", String, ForeignKey("roles.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    roles = relationship("Role", secondary=user_roles, back_populates="users")
    projects = relationship("Project", back_populates="creator")


class Role(Base):
    __tablename__ = "roles"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", secondary=user_roles, back_populates="roles")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User", back_populates="projects")
    services = relationship("Service", back_populates="project")


class Service(Base):
    __tablename__ = "services"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    service_type = Column(String, nullable=True)
    owner = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="services")
    environments = relationship("Environment", back_populates="service")
    repositories = relationship("Repository", back_populates="service")
    pipeline_runs = relationship("PipelineRun", back_populates="service")
    health_snapshots = relationship(
        "ServiceHealthSnapshot",
        back_populates="service",
        cascade="all, delete-orphan",
    )


class ServiceHealthStatus(str, enum.Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class ServiceHealthSnapshot(Base):
    __tablename__ = "service_health_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    service_id = Column(
        String,
        ForeignKey("services.id"),
        nullable=False,
        index=True,
    )
    service_name = Column(String, nullable=False, index=True)

    environment = Column(String, nullable=False, default="staging")
    status = Column(
        Enum(ServiceHealthStatus),
        nullable=False,
        default=ServiceHealthStatus.UNKNOWN,
    )

    latency_ms = Column(Float, nullable=True)
    error_rate = Column(Float, nullable=True)
    cpu_usage = Column(Float, nullable=True)
    memory_usage = Column(Float, nullable=True)

    pod_restart_count = Column(Integer, nullable=True)
    replica_count = Column(Integer, nullable=True)
    available_replicas = Column(Integer, nullable=True)

    source = Column(String, nullable=False, default="prometheus")

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    service = relationship("Service", back_populates="health_snapshots")


class Environment(Base):
    __tablename__ = "environments"

    id = Column(String, primary_key=True, default=generate_uuid)
    service_id = Column(String, ForeignKey("services.id"), nullable=False)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    service = relationship("Service", back_populates="environments")


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(String, primary_key=True, default=generate_uuid)
    service_id = Column(String, ForeignKey("services.id"), nullable=False)
    provider = Column(String, nullable=True)
    repo_url = Column(Text, nullable=False)
    default_branch = Column(String, default="main")
    created_at = Column(DateTime, default=datetime.utcnow)

    service = relationship("Service", back_populates="repositories")
    pipeline_runs = relationship("PipelineRun", back_populates="repository")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(String, primary_key=True, index=True)

    service_id = Column(String, ForeignKey("services.id"), nullable=True)
    repo_id = Column(String, ForeignKey("repositories.id"), nullable=True)

    repo_url = Column(String, nullable=False)
    branch = Column(String, default="main")

    status = Column(String, default="PENDING")
    stage = Column(String, default="QUEUED")
    failure_reason = Column(Text, nullable=True)

    commit_sha = Column(String, nullable=True)
    commit_message = Column(Text, nullable=True)

    build_status = Column(String, default="NOT_STARTED")
    test_status = Column(String, default="NOT_STARTED")
    sonar_status = Column(String, default="NOT_STARTED")
    trivy_status = Column(String, default="NOT_STARTED")

    coverage = Column(Float, nullable=True)
    bugs = Column(Integer, default=0)
    vulnerabilities = Column(Integer, default=0)
    code_smells = Column(Integer, default=0)
    duplicated_lines_density = Column(Float, nullable=True)

    quality_gate = Column(String, nullable=True)
    sonar_report_url = Column(String, nullable=True)
    sonar_issues = Column(MutableList.as_mutable(JSON), default=list, nullable=False)

    trivy_critical = Column(Integer, default=0)
    trivy_high = Column(Integer, default=0)
    trivy_medium = Column(Integer, default=0)
    trivy_low = Column(Integer, default=0)
    trivy_unknown = Column(Integer, default=0)
    trivy_total = Column(Integer, default=0)
    trivy_report = Column(MutableDict.as_mutable(JSON), nullable=True)

    risk_score = Column(Float, nullable=True)
    risk_level = Column(String, nullable=True)
    risk_summary = Column(Text, nullable=True)

    ai_summary = Column(Text, nullable=True)
    recommendations = Column(MutableList.as_mutable(JSON), default=list, nullable=False)

    logs = Column(MutableList.as_mutable(JSON), default=list, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)

    service = relationship("Service", back_populates="pipeline_runs")
    repository = relationship("Repository", back_populates="pipeline_runs")


class Deployment(Base):
    __tablename__ = "deployments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    service_id = Column(String(36), ForeignKey("services.id"), nullable=False)
    pipeline_run_id = Column(String(36), ForeignKey("pipeline_runs.id"), nullable=True)
    environment_id = Column(String(36), ForeignKey("environments.id"), nullable=True)

    commit_sha = Column(String(100), nullable=True)
    image_tag = Column(String(255), nullable=False)
    deployment_version = Column(String(50), nullable=True)

    argo_sync_status = Column(String(50), nullable=True, default="UNKNOWN")
    kubernetes_rollout_status = Column(String(50), nullable=True, default="UNKNOWN")

    previous_revision = Column(String(100), nullable=True)

    namespace = Column(String(100), nullable=True)
    cluster_name = Column(String(100), nullable=True, default="kind-platformiq")
    service_name = Column(String(150), nullable=True)
    argo_application_name = Column(String(150), nullable=True)

    pod_count = Column(Integer, nullable=True, default=0)
    restart_count = Column(Integer, nullable=True, default=0)
    failure_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deployed_at = Column(DateTime(timezone=True), nullable=True)

    workloads = relationship(
        "KubernetesWorkload",
        back_populates="deployment",
        cascade="all, delete-orphan",
    )

    revisions = relationship(
        "DeploymentRevision",
        back_populates="deployment",
        cascade="all, delete-orphan",
    )


class KubernetesWorkload(Base):
    __tablename__ = "kubernetes_workloads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    deployment_id = Column(UUID(as_uuid=True), ForeignKey("deployments.id"), nullable=False)

    workload_name = Column(String(150), nullable=False)
    namespace = Column(String(100), nullable=False)
    kind = Column(String(50), nullable=False)

    desired_replicas = Column(Integer, nullable=True, default=0)
    available_replicas = Column(Integer, nullable=True, default=0)
    pod_count = Column(Integer, nullable=True, default=0)
    restart_count = Column(Integer, nullable=True, default=0)

    status = Column(String(50), nullable=True, default="UNKNOWN")
    failure_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    deployment = relationship("Deployment", back_populates="workloads")


class DeploymentRevision(Base):
    __tablename__ = "deployment_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    deployment_id = Column(UUID(as_uuid=True), ForeignKey("deployments.id"), nullable=False)

    revision = Column(String(100), nullable=True)
    image_tag = Column(String(255), nullable=True)
    commit_sha = Column(String(100), nullable=True)
    status = Column(String(50), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deployed_at = Column(DateTime(timezone=True), nullable=True)

    deployment = relationship("Deployment", back_populates="revisions")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    actor_id = Column(String, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class EventRecord(Base):
    __tablename__ = "event_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    event_id = Column(String, nullable=False, unique=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    schema_version = Column(String, nullable=True)

    topic = Column(String, nullable=False, index=True)
    correlation_id = Column(String, nullable=True, index=True)
    service_id = Column(String, nullable=True, index=True)
    environment = Column(String, nullable=True, index=True)

    timestamp = Column(DateTime(timezone=True), nullable=True, index=True)

    payload = Column(JSON, nullable=False, default=dict)
    raw_event = Column(JSON, nullable=False, default=dict)

    processing_status = Column(
        String,
        nullable=False,
        default="PROCESSED",
        index=True,
    )
    processing_error = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    processed_at = Column(DateTime(timezone=True), nullable=True)


Index(
    "ix_event_records_release_timeline",
    EventRecord.correlation_id,
    EventRecord.timestamp,
)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    event_id = Column(String, unique=True, index=True, nullable=False)
    topic = Column(String, index=True, nullable=False)
    event_type = Column(String, index=True, nullable=False)
    schema_version = Column(String, nullable=False, default="1.0")

    correlation_id = Column(String, index=True, nullable=True)
    service_id = Column(String, index=True, nullable=True)
    environment = Column(String, index=True, nullable=True)

    payload = Column(JSONB, nullable=False, default=dict)

    status = Column(String, index=True, nullable=False, default="PENDING")
    retry_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)

    published_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ConsumerCheckpoint(Base):
    __tablename__ = "consumer_checkpoints"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    consumer_name = Column(String, nullable=False)
    topic = Column(String, nullable=False)
    partition = Column(Integer, nullable=False)
    offset = Column(Integer, nullable=False)

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "consumer_name",
            "topic",
            "partition",
            name="uq_consumer_topic_partition",
        ),
    )


class DeadLetterEvent(Base):
    __tablename__ = "dead_letter_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    event_id = Column(String, nullable=False, unique=True, index=True)
    event_type = Column(String, nullable=True, index=True)
    topic = Column(String, nullable=True, index=True)

    correlation_id = Column(String, nullable=True, index=True)
    service_id = Column(String, nullable=True, index=True)
    environment = Column(String, nullable=True, index=True)

    raw_event = Column(JSON, nullable=True)
    payload = Column(JSON, nullable=True)

    error_reason = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="OPEN", index=True)

    retry_count = Column(Integer, nullable=False, default=0)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    last_retry_at = Column(DateTime(timezone=True), nullable=True)


class IncidentSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, enum.Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    severity = Column(
        Enum(IncidentSeverity, name="incidentseverity"),
        nullable=False,
        index=True,
    )

    status = Column(
        Enum(IncidentStatus, name="incidentstatus"),
        nullable=False,
        default=IncidentStatus.OPEN,
        index=True,
    )

    service_id = Column(String, nullable=False, index=True)
    environment = Column(String, nullable=False, index=True)

    correlation_id = Column(String, nullable=False, index=True)
    triggered_by_event_id = Column(String, nullable=True, index=True)

    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    events = relationship(
        "IncidentEvent",
        back_populates="incident",
        cascade="all, delete-orphan",
    )


class IncidentEvent(Base):
    __tablename__ = "incident_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    incident_id = Column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    event_type = Column(String, nullable=False, index=True)
    message = Column(Text, nullable=True)

    # Important: SQLAlchemy reserves the name "metadata".
    # The Python attribute is event_metadata, but the DB column is metadata.
    event_metadata = Column("metadata", JSON, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="events")