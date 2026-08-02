import enum
import uuid
from datetime import datetime, timezone
from app.incidents.enums import IncidentSeverity, IncidentStatus

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SQLEnum,
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import relationship, validates

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
    remediation_recommendations = relationship(
        "RemediationRecommendation",
        back_populates="service",
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
        SQLEnum(ServiceHealthStatus),
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


# ============================================================
# Sprint 7 — Incident Response and Timeline Engine
# ============================================================


def enum_values(enum_class):
    """
    Persist enum values rather than Python member names.

    Example:
        IncidentSeverity.SEV_1 -> "SEV-1"
    """
    return [member.value for member in enum_class]






incident_severity_enum = SQLEnum(
    IncidentSeverity,
    name="incidentseverity",
    values_callable=enum_values,
    validate_strings=True,
)


incident_status_enum = SQLEnum(
    IncidentStatus,
    name="incidentstatus",
    values_callable=enum_values,
    validate_strings=True,
)


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    incident_number = Column(
        String(32),
        nullable=False,
        unique=True,
        server_default=text("next_incident_number()"),
    )

    title = Column(
        String(255),
        nullable=False,
    )

    description = Column(
        Text,
        nullable=True,
    )
    
    evidence_records = relationship(
        "IncidentEvidence",
        back_populates="incident",
        cascade="all, delete-orphan",
    )

    rca_reports = relationship(
        "RCAReport",
        back_populates="incident",
        cascade="all, delete-orphan",
    )

    rca_feedback = relationship(
        "RCAFeedback",
        back_populates="incident",
        cascade="all, delete-orphan",
    )

    remediation_recommendations = relationship(
        "RemediationRecommendation",
        back_populates="incident",
        cascade="all, delete-orphan",
    )

    severity = Column(
        incident_severity_enum,
        nullable=False,
        default=IncidentSeverity.SEV_3,
        server_default=IncidentSeverity.SEV_3.value,
    )

    status = Column(
        incident_status_enum,
        nullable=False,
        default=IncidentStatus.DETECTED,
        server_default=IncidentStatus.DETECTED.value,
    )

    primary_service_id = Column(
        String(36),
        ForeignKey("services.id", ondelete="SET NULL"),
        nullable=True,
    )

    environment = Column(
        String(100),
        nullable=False,
    )

    triggering_alert_id = Column(
        String(36),
        ForeignKey(
            "reliability_alerts.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    suspected_deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "deployments.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    deduplication_key = Column(
        String(500),
        nullable=True,
    )

    failure_started_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    detected_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    acknowledged_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    investigation_started_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    remediation_started_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    resolved_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    current_assignee_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    resolution_summary = Column(
        Text,
        nullable=True,
    )

    rca_summary = Column(
        Text,
        nullable=True,
    )

    remediation_summary = Column(
        Text,
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    created_by = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --------------------------------------------------------
    # Temporary Sprint 5 compatibility columns.
    #
    # Keep these during Sprint 7B because the active router and
    # old incident service still use these names.
    # --------------------------------------------------------

    # Legacy Sprint 5 compatibility fields.
    # New Sprint 7 code must use primary_service_id, deduplication_key,
    # detected_at, and the incident-alert relationship instead.
    service_id = Column(
        String,
        nullable=True,

    )

    correlation_id = Column(
        String,
        nullable=True,

    )

    triggered_by_event_id = Column(
        String,
        nullable=True,

    )

    started_at = Column(
        DateTime,
        nullable=True,
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

    primary_service = relationship(
        "Service",
        foreign_keys=[primary_service_id],
    )

    triggering_alert = relationship(
        "ReliabilityAlert",
        foreign_keys=[triggering_alert_id],
    )

    suspected_deployment = relationship(
        "Deployment",
        foreign_keys=[suspected_deployment_id],
    )

    current_assignee = relationship(
        "User",
        foreign_keys=[current_assignee_id],
    )

    creator = relationship(
        "User",
        foreign_keys=[created_by],
    )

    events = relationship(
        "IncidentTimelineEvent",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by=(
            "IncidentTimelineEvent.occurred_at, "
            "IncidentTimelineEvent.id"
        ),
    )

    assignments = relationship(
        "IncidentAssignment",
        back_populates="incident",
        cascade="all, delete-orphan",
    )

    comments = relationship(
        "IncidentComment",
        back_populates="incident",
        cascade="all, delete-orphan",
    )

    metrics = relationship(
        "IncidentMetric",
        back_populates="incident",
        cascade="all, delete-orphan",
    )

    alert_links = relationship(
        "IncidentAlertLink",
        back_populates="incident",
        cascade="all, delete-orphan",
    )

    # Keep old ORM creation working until incident_service.py
    # is replaced during the next Sprint 7 step.

    @validates("service_id")
    def sync_legacy_service_id(self, key, value):
        if value:
            self.primary_service_id = value

        return value

    @validates("correlation_id")
    def sync_legacy_correlation_id(self, key, value):
        if value:
            self.deduplication_key = value

        return value

    @validates("started_at")
    def sync_legacy_started_at(self, key, value):
        if value:
            self.failure_started_at = value

        return value

    __table_args__ = (
        Index(
            "ix_incidents_status",
            "status",
        ),
        Index(
            "ix_incidents_severity",
            "severity",
        ),
        Index(
            "ix_incidents_primary_service_id",
            "primary_service_id",
        ),
        Index(
            "ix_incidents_environment",
            "environment",
        ),
        Index(
            "ix_incidents_detected_at",
            "detected_at",
        ),
        Index(
            "ix_incidents_current_assignee_id",
            "current_assignee_id",
        ),
        Index(
            "ix_incidents_deduplication_key",
            "deduplication_key",
        ),
    )


class IncidentTimelineEvent(Base):
    __tablename__ = "incident_timeline_events"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    incident_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "incidents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    event_type = Column(
        String(100),
        nullable=False,
    )

    source = Column(
        String(100),
        nullable=False,
        default="SYSTEM",
        server_default="SYSTEM",
    )

    message = Column(
        Text,
        nullable=True,
    )

    from_status = Column(
        incident_status_enum,
        nullable=True,
    )

    to_status = Column(
        incident_status_enum,
        nullable=True,
    )

    actor_user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    alert_id = Column(
        String(36),
        ForeignKey(
            "reliability_alerts.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "deployments.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    metadata_json = Column(
        JSONB,
        nullable=True,
    )

    occurred_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    incident = relationship(
        "Incident",
        back_populates="events",
    )

    actor_user = relationship(
        "User",
        foreign_keys=[actor_user_id],
    )

    alert = relationship(
        "ReliabilityAlert",
        foreign_keys=[alert_id],
    )

    deployment = relationship(
        "Deployment",
        foreign_keys=[deployment_id],
    )

    # Compatibility with old IncidentEvent(event_metadata=...).
    @property
    def event_metadata(self):
        return self.metadata_json

    @event_metadata.setter
    def event_metadata(self, value):
        self.metadata_json = value

    __table_args__ = (
        Index(
            "ix_incident_timeline_incident_occurred_id",
            "incident_id",
            "occurred_at",
            "id",
        ),
        Index(
            "ix_incident_timeline_event_type",
            "event_type",
        ),
    )


# Temporary import compatibility:
#
# from app.models import IncidentEvent
#
# will continue to work, but the real table is now
# incident_timeline_events.
IncidentEvent = IncidentTimelineEvent


class IncidentAssignment(Base):
    __tablename__ = "incident_assignments"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    incident_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "incidents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    assigned_to_user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    assigned_by_user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    assignment_note = Column(
        Text,
        nullable=True,
    )

    assigned_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    unassigned_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    incident = relationship(
        "Incident",
        back_populates="assignments",
    )

    assigned_to_user = relationship(
        "User",
        foreign_keys=[assigned_to_user_id],
    )

    assigned_by_user = relationship(
        "User",
        foreign_keys=[assigned_by_user_id],
    )


class IncidentComment(Base):
    __tablename__ = "incident_comments"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    incident_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "incidents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    author_user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    comment = Column(
        Text,
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    incident = relationship(
        "Incident",
        back_populates="comments",
    )

    author = relationship(
        "User",
        foreign_keys=[author_user_id],
    )


class IncidentMetric(Base):
    __tablename__ = "incident_metrics"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    incident_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "incidents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    metric_type = Column(
        String(100),
        nullable=False,
    )

    metric_name = Column(
        String(255),
        nullable=False,
    )

    value = Column(
        Float,
        nullable=False,
    )

    unit = Column(
        String(50),
        nullable=True,
    )

    source = Column(
        String(100),
        nullable=False,
        default="UNKNOWN",
        server_default="UNKNOWN",
    )

    captured_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    metadata_json = Column(
        JSONB,
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    incident = relationship(
        "Incident",
        back_populates="metrics",
    )


class IncidentAlertLink(Base):
    __tablename__ = "incident_alert_links"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    incident_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "incidents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    reliability_alert_id = Column(
        String(36),
        ForeignKey(
            "reliability_alerts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    linked_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    is_triggering_alert = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    incident = relationship(
        "Incident",
        back_populates="alert_links",
    )

    reliability_alert = relationship(
        "ReliabilityAlert",
    )

    __table_args__ = (
        UniqueConstraint(
            "incident_id",
            "reliability_alert_id",
            name="uq_incident_alert_link",
        ),
        UniqueConstraint(
            "reliability_alert_id",
            name="uq_incident_alert_links_reliability_alert_id",
        ),
    )

# ============================================================
# Sprint 6 — Reliability Models
# ============================================================

class EvidenceCollectionStatus(str, enum.Enum):
    PENDING = "PENDING"
    COLLECTING = "COLLECTING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class RCAReportStatus(str, enum.Enum):
    PENDING = "PENDING"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RCAConfidence(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RCAFeedbackRating(str, enum.Enum):
    CORRECT = "CORRECT"
    PARTIALLY_CORRECT = "PARTIALLY_CORRECT"
    INCORRECT = "INCORRECT"


class IncidentEvidence(Base):
    __tablename__ = "incident_evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    incident_id = Column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version = Column(Integer, nullable=False, default=1)

    status = Column(
        SQLEnum(EvidenceCollectionStatus, name="evidence_collection_status"),
        nullable=False,
        default=EvidenceCollectionStatus.PENDING,
        server_default=EvidenceCollectionStatus.PENDING.value,
    )

    schema_version = Column(
        String(20),
        nullable=False,
        default="1.0",
        server_default="1.0",
    )

    window_start = Column(DateTime(timezone=True), nullable=True)
    window_end = Column(DateTime(timezone=True), nullable=True)
    anchor_time = Column(DateTime(timezone=True), nullable=True)

    evidence_payload = Column(JSONB, nullable=False, default=dict)
    source_statuses = Column(JSONB, nullable=False, default=dict)
    collection_errors = Column(JSONB, nullable=False, default=list)

    created_by = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    incident = relationship("Incident", back_populates="evidence_records")

    reports = relationship(
        "RCAReport",
        back_populates="evidence",
        cascade="all, delete-orphan",
    )

    creator = relationship("User")

    __table_args__ = (
        UniqueConstraint(
            "incident_id",
            "version",
            name="uq_incident_evidence_incident_version",
        ),
        Index(
            "ix_incident_evidence_incident_created",
            "incident_id",
            "created_at",
        ),
    )


class RCAReport(Base):
    __tablename__ = "rca_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    incident_id = Column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    evidence_id = Column(
        UUID(as_uuid=True),
        ForeignKey("incident_evidence.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    version = Column(Integer, nullable=False, default=1)

    status = Column(
        SQLEnum(RCAReportStatus, name="rca_report_status"),
        nullable=False,
        default=RCAReportStatus.PENDING,
        server_default=RCAReportStatus.PENDING.value,
    )

    schema_version = Column(
        String(20),
        nullable=False,
        default="1.0",
        server_default="1.0",
    )

    confidence = Column(
        SQLEnum(RCAConfidence, name="rca_confidence"),
        nullable=True,
    )

    summary = Column(Text, nullable=True)
    probable_root_cause = Column(Text, nullable=True)

    supporting_evidence = Column(JSONB, nullable=False, default=list)
    contradictory_evidence = Column(JSONB, nullable=False, default=list)
    alternative_hypotheses = Column(JSONB, nullable=False, default=list)
    missing_evidence = Column(JSONB, nullable=False, default=list)
    report_json = Column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    model_provider = Column(String(100), nullable=True)
    model_name = Column(String(100), nullable=True)
    prompt_version = Column(String(50), nullable=True)

    generated_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    incident = relationship("Incident", back_populates="rca_reports")
    evidence = relationship("IncidentEvidence", back_populates="reports")

    feedback_items = relationship(
        "RCAFeedback",
        back_populates="report",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "incident_id",
            "version",
            name="uq_rca_reports_incident_version",
        ),
        Index(
            "ix_rca_reports_incident_created",
            "incident_id",
            "created_at",
        ),
    )


class RCAFeedback(Base):
    __tablename__ = "rca_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    incident_id = Column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    report_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rca_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    rating = Column(
        SQLEnum(RCAFeedbackRating, name="rca_feedback_rating"),
        nullable=False,
    )

    comment = Column(Text, nullable=True)
    correct_root_cause = Column(Text, nullable=True)

    reviewer_id = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    incident = relationship("Incident", back_populates="rca_feedback")
    report = relationship("RCAReport", back_populates="feedback_items")
    reviewer = relationship("User")

    __table_args__ = (
        Index(
            "ix_rca_feedback_report_created",
            "report_id",
            "created_at",
        ),
    )


# ============================================================
# Sprint 9A — Remediation Data Model Foundation
# ============================================================


class RecommendationStatus(str, enum.Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RECOVERY_VERIFIED = "RECOVERY_VERIFIED"
    RECOVERY_FAILED = "RECOVERY_FAILED"


class ActionType(str, enum.Enum):
    ROLLBACK_DEPLOYMENT = "ROLLBACK_DEPLOYMENT"
    RESTART_POD = "RESTART_POD"
    SCALE_REPLICAS = "SCALE_REPLICAS"
    REDEPLOY_REVISION = "REDEPLOY_REVISION"


class ApprovalDecision(str, enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RemediationExecutionStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class RecoveryVerificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


recommendation_status_enum = SQLEnum(
    RecommendationStatus,
    name="recommendation_status",
    values_callable=enum_values,
    validate_strings=True,
)


remediation_action_type_enum = SQLEnum(
    ActionType,
    name="remediation_action_type",
    values_callable=enum_values,
    validate_strings=True,
)


approval_decision_enum = SQLEnum(
    ApprovalDecision,
    name="remediation_approval_decision",
    values_callable=enum_values,
    validate_strings=True,
)


remediation_execution_status_enum = SQLEnum(
    RemediationExecutionStatus,
    name="remediation_execution_status",
    values_callable=enum_values,
    validate_strings=True,
)


recovery_verification_status_enum = SQLEnum(
    RecoveryVerificationStatus,
    name="recovery_verification_status",
    values_callable=enum_values,
    validate_strings=True,
)


class RemediationRecommendation(Base):
    __tablename__ = "remediation_recommendations"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    incident_id = Column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )

    service_id = Column(
        String(36),
        ForeignKey("services.id", ondelete="RESTRICT"),
        nullable=False,
    )

    environment = Column(
        String(100),
        nullable=False,
    )

    action_type = Column(
        remediation_action_type_enum,
        nullable=False,
    )

    reason = Column(
        Text,
        nullable=False,
    )

    evidence_summary = Column(
        JSONB,
        nullable=False,
        default=dict,
    )

    confidence = Column(
        SQLEnum(
            RCAConfidence,
            name="rca_confidence",
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )

    status = Column(
        recommendation_status_enum,
        nullable=False,
        default=RecommendationStatus.PENDING_APPROVAL,
        server_default=RecommendationStatus.PENDING_APPROVAL.value,
    )

    created_by = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    incident = relationship(
        "Incident",
        back_populates="remediation_recommendations",
    )

    service = relationship(
        "Service",
        back_populates="remediation_recommendations",
    )

    creator = relationship(
        "User",
        foreign_keys=[created_by],
    )

    approval = relationship(
        "RemediationApproval",
        back_populates="remediation",
        uselist=False,
        cascade="all, delete-orphan",
    )

    executions = relationship(
        "RemediationExecution",
        back_populates="remediation",
        cascade="all, delete-orphan",
        order_by="RemediationExecution.created_at",
    )

    recovery_verifications = relationship(
        "RecoveryVerification",
        back_populates="remediation",
        cascade="all, delete-orphan",
        order_by="RecoveryVerification.created_at",
    )

    __table_args__ = (
        Index(
            "ix_remediation_recommendations_incident_created",
            "incident_id",
            "created_at",
        ),
        Index(
            "ix_remediation_recommendations_service_environment",
            "service_id",
            "environment",
        ),
        Index(
            "ix_remediation_recommendations_status",
            "status",
        ),
    )


class RemediationApproval(Base):
    __tablename__ = "remediation_approvals"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    remediation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "remediation_recommendations.id",
            ondelete="CASCADE",
        ),
        nullable=False
    )

    approved_by = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    decision = Column(
        approval_decision_enum,
        nullable=False,
    )

    rejection_reason = Column(
        Text,
        nullable=True,
    )

    approved_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    remediation = relationship(
        "RemediationRecommendation",
        back_populates="approval",
    )

    approver = relationship(
        "User",
        foreign_keys=[approved_by],
    )

    __table_args__ = (
        CheckConstraint(
            "decision != 'REJECTED' OR "
            "(rejection_reason IS NOT NULL "
            "AND length(trim(rejection_reason)) > 0)",
            name=(
                "ck_remediation_approval_"
                "rejection_reason"
            ),
        ),
        UniqueConstraint(
            "remediation_id",
            name=(
                "uq_remediation_approvals_"
                "remediation_id"
            ),
        ),
        Index(
            "ix_remediation_approvals_remediation_id",
            "remediation_id",
        ),
    )


class RemediationExecution(Base):
    __tablename__ = "remediation_executions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    remediation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "remediation_recommendations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    command_type = Column(
        remediation_action_type_enum,
        nullable=False,
    )

    command_payload = Column(
        JSONB,
        nullable=False,
        default=dict,
    )

    execution_status = Column(
        remediation_execution_status_enum,
        nullable=False,
        default=RemediationExecutionStatus.PENDING,
        server_default=RemediationExecutionStatus.PENDING.value,
    )

    started_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    result_summary = Column(
        JSONB,
        nullable=False,
        default=dict,
    )

    error_message = Column(
        Text,
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    remediation = relationship(
        "RemediationRecommendation",
        back_populates="executions",
    )

    recovery_verification = relationship(
        "RecoveryVerification",
        back_populates="execution",
        uselist=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "remediation_id",
            name=(
                "uq_remediation_executions_"
                "remediation_id"
            ),
        ),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL "
            "OR completed_at >= started_at",
            name="ck_remediation_execution_timestamp_order",
        ),
        Index(
            "ix_remediation_executions_remediation_status",
            "remediation_id",
            "execution_status",
        ),
        Index(
            "ix_remediation_executions_started_at",
            "started_at",
        ),
    )


class RecoveryVerification(Base):
    __tablename__ = "recovery_verifications"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    remediation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "remediation_recommendations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    remediation_execution_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "remediation_executions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        unique=True,
    )

    verification_status = Column(
        recovery_verification_status_enum,
        nullable=False,
        default=RecoveryVerificationStatus.PENDING,
        server_default=RecoveryVerificationStatus.PENDING.value,
    )

    error_rate_recovered = Column(
        Boolean,
        nullable=True,
    )

    latency_recovered = Column(
        Boolean,
        nullable=True,
    )

    pods_healthy = Column(
        Boolean,
        nullable=True,
    )

    restart_loop_absent = Column(
        Boolean,
        nullable=True,
    )

    availability_restored = Column(
        Boolean,
        nullable=True,
    )

    metrics_snapshot = Column(
        JSONB,
        nullable=False,
        default=dict,
    )

    verified_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    remediation = relationship(
        "RemediationRecommendation",
        back_populates="recovery_verifications",
    )

    execution = relationship(
        "RemediationExecution",
        back_populates="recovery_verification",
    )

    __table_args__ = (
        CheckConstraint(
            "verification_status = 'PENDING' "
            "OR verified_at IS NOT NULL",
            name="ck_recovery_verification_verified_at",
        ),
        Index(
            "ix_recovery_verifications_remediation_id",
            "remediation_id",
        ),
    )


class SLOMetricType(str, enum.Enum):
    AVAILABILITY = "AVAILABILITY"
    P95_LATENCY = "P95_LATENCY"
    ERROR_RATE = "ERROR_RATE"


class ReliabilitySeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ErrorBudgetState(str, enum.Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    BREACHED = "BREACHED"
    EXHAUSTED = "EXHAUSTED"


class ReliabilityAlertType(str, enum.Enum):
    SLO_BREACH = "SLO_BREACH"
    ERROR_BUDGET_BURN = "ERROR_BUDGET_BURN"
    ERROR_BUDGET_EXHAUSTED = "ERROR_BUDGET_EXHAUSTED"
    LATENCY_BREACH = "LATENCY_BREACH"
    AVAILABILITY_BREACH = "AVAILABILITY_BREACH"
    ERROR_RATE_BREACH = "ERROR_RATE_BREACH"


class ReliabilityAlertStatus(str, enum.Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class SLODefinition(Base):
    __tablename__ = "slo_definitions"

    id = Column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    service_id = Column(
        String(36),
        ForeignKey("services.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    metric_type = Column(
        SQLEnum(SLOMetricType, name="slo_metric_type"),
        nullable=False,
    )

    target_value = Column(Float, nullable=False)

    window_minutes = Column(
        Integer,
        nullable=False,
        default=60,
        server_default="60",
    )

    severity_on_breach = Column(
        SQLEnum(
            ReliabilitySeverity,
            name="reliability_severity",
        ),
        nullable=False,
        default=ReliabilitySeverity.HIGH,
        server_default=ReliabilitySeverity.HIGH.value,
    )

    enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    service = relationship("Service")

    measurements = relationship(
        "SLOMeasurement",
        back_populates="slo_definition",
        cascade="all, delete-orphan",
    )

    error_budget_statuses = relationship(
        "ErrorBudgetStatus",
        back_populates="slo_definition",
        cascade="all, delete-orphan",
    )

    alerts = relationship(
        "ReliabilityAlert",
        back_populates="slo_definition",
        cascade="all, delete-orphan",
    )


class SLOMeasurement(Base):
    __tablename__ = "slo_measurements"

    id = Column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    slo_definition_id = Column(
        String(36),
        ForeignKey("slo_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    service_id = Column(
        String(36),
        ForeignKey("services.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    metric_type = Column(
        SQLEnum(SLOMetricType, name="slo_metric_type"),
        nullable=False,
    )

    measured_value = Column(Float, nullable=False)
    target_value = Column(Float, nullable=False)
    is_breached = Column(Boolean, nullable=False)
    window_minutes = Column(Integer, nullable=False)

    source = Column(
        String(50),
        nullable=False,
        default="PROMETHEUS",
        server_default="PROMETHEUS",
    )

    evaluated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    slo_definition = relationship(
        "SLODefinition",
        back_populates="measurements",
    )

    service = relationship("Service")


class ErrorBudgetStatus(Base):
    __tablename__ = "error_budget_statuses"

    id = Column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    slo_definition_id = Column(
        String(36),
        ForeignKey("slo_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    service_id = Column(
        String(36),
        ForeignKey("services.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    target_percentage = Column(Float, nullable=False)
    allowed_failure_percentage = Column(Float, nullable=False)

    consumed_percentage = Column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0",
    )

    remaining_percentage = Column(
        Float,
        nullable=False,
        default=100.0,
        server_default="100",
    )

    burn_rate = Column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0",
    )

    status = Column(
        SQLEnum(ErrorBudgetState, name="error_budget_state"),
        nullable=False,
        default=ErrorBudgetState.HEALTHY,
        server_default=ErrorBudgetState.HEALTHY.value,
    )

    window_minutes = Column(Integer, nullable=False)

    evaluated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    slo_definition = relationship(
        "SLODefinition",
        back_populates="error_budget_statuses",
    )

    service = relationship("Service")


class ReliabilityAlert(Base):
    __tablename__ = "reliability_alerts"

    id = Column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    service_id = Column(
        String(36),
        ForeignKey("services.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    slo_definition_id = Column(
        String(36),
        ForeignKey("slo_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    alert_type = Column(
        SQLEnum(
            ReliabilityAlertType,
            name="reliability_alert_type",
        ),
        nullable=False,
    )

    severity = Column(
        SQLEnum(
            ReliabilitySeverity,
            name="reliability_severity",
        ),
        nullable=False,
    )

    triggered_value = Column(Float, nullable=False)
    threshold_value = Column(Float, nullable=False)

    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("deployments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status = Column(
        SQLEnum(
            ReliabilityAlertStatus,
            name="reliability_alert_status",
        ),
        nullable=False,
        default=ReliabilityAlertStatus.OPEN,
        server_default=ReliabilityAlertStatus.OPEN.value,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    resolved_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    service = relationship("Service")

    slo_definition = relationship(
        "SLODefinition",
        back_populates="alerts",
    )

    deployment = relationship("Deployment")