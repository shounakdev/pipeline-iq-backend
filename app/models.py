from sqlalchemy import Column, String, Text, DateTime, Float, ForeignKey, Integer, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime

from app.database import Base


class Pipeline(Base):
    __tablename__ = "pipelines"

    id = Column(String, primary_key=True, index=True)

    repo_url = Column(Text, nullable=False)
    branch = Column(String, nullable=False, default="main")
    status = Column(String, nullable=False, default="PENDING")

    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    quality_score = Column(Float, nullable=True)
    coverage = Column(Float, nullable=True)

    # Detailed SonarQube metrics
    bugs = Column(Integer, nullable=True)
    vulnerabilities = Column(Integer, nullable=True)
    code_smells = Column(Integer, nullable=True)
    duplicated_lines_density = Column(Float, nullable=True)
    quality_gate = Column(String, nullable=True)
    sonar_report_url = Column(Text, nullable=True)
    sonar_issues_json = Column(Text, nullable=True)

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
    

class Role(Base):
    __tablename__ = "roles"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="role")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=True)
    role_id = Column(String, ForeignKey("roles.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    role = relationship("Role", back_populates="users")
    projects = relationship("Project", back_populates="creator")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User", back_populates="projects")
    services = relationship(
        "Service",
        back_populates="project",
        cascade="all, delete-orphan",
    )


class Service(Base):
    __tablename__ = "services"

    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    service_type = Column(String, nullable=False, default="web")
    owner = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="services")
    repositories = relationship(
        "Repository",
        back_populates="service",
        cascade="all, delete-orphan",
    )
    environments = relationship(
        "Environment",
        back_populates="service",
        cascade="all, delete-orphan",
    )


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(String, primary_key=True, index=True)
    service_id = Column(String, ForeignKey("services.id"), nullable=False)
    provider = Column(String, nullable=False, default="github")
    repo_url = Column(Text, nullable=False)
    default_branch = Column(String, nullable=False, default="main")
    created_at = Column(DateTime, default=datetime.utcnow)

    service = relationship("Service", back_populates="repositories")


class Environment(Base):
    __tablename__ = "environments"

    id = Column(String, primary_key=True, index=True)
    service_id = Column(String, ForeignKey("services.id"), nullable=False)
    name = Column(String, nullable=False, default="development")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    service = relationship("Service", back_populates="environments")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True, index=True)
    actor_id = Column(String, nullable=True)
    action = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=True, index=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)