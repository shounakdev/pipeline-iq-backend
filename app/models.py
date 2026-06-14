import uuid
from sqlalchemy import Column, String, Text, DateTime, Float, ForeignKey, Integer, Boolean, JSON, Table
from sqlalchemy.orm import relationship
from datetime import datetime
from sqlalchemy.sql import func
from sqlalchemy.ext.mutable import MutableList, MutableDict


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

    # Detailed SonarQube metrics
    bugs = Column(Integer, default=0)
    vulnerabilities = Column(Integer, default=0)
    code_smells = Column(Integer, default=0)
    duplicated_lines_density = Column(Float, nullable=True)
    quality_gate = Column(String, nullable=True)
    sonar_report_url = Column(Text, nullable=True)
    #sonar_issues_json = Column(Text, nullable=True)
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
        cascade="all, delete-orphan"
    )

    analysis = relationship(
        "Analysis",
        back_populates="pipeline",
        uselist=False,
        cascade="all, delete-orphan"
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

    # AI summary / final analysis fields
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


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    actor_id = Column(String, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)