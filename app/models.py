from sqlalchemy import Column, String, Text, DateTime, Float, ForeignKey, Integer
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