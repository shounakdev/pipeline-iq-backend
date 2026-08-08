"""add sprint 10a chaos data models

Revision ID: c9a8e7d6f5b4
Revises: 86b465be9924
Create Date: 2026-08-08 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c9a8e7d6f5b4"
down_revision: Union[str, Sequence[str], None] = "86b465be9924"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


chaos_scenario_type_enum = postgresql.ENUM(
    "FAULTY_RELEASE",
    "POD_KILL",
    "NETWORK_DELAY",
    "DATABASE_DELAY",
    "CPU_PRESSURE",
    name="chaos_scenario_type",
    create_type=False,
)
chaos_run_status_enum = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "FAULT_INJECTED",
    "OBSERVING",
    "RECOVERING",
    "COMPLETED",
    "FAILED",
    "ABORTED",
    name="chaos_run_status",
    create_type=False,
)
chaos_observation_type_enum = postgresql.ENUM(
    "FAILURE_INJECTED",
    "TELEMETRY_ANOMALY",
    "ALERT_CREATED",
    "INCIDENT_CREATED",
    "RCA_COMPLETED",
    "REMEDIATION_RECOMMENDED",
    "REMEDIATION_APPROVED",
    "REMEDIATION_EXECUTED",
    "RECOVERY_COMPLETED",
    name="chaos_observation_type",
    create_type=False,
)
diagnosis_rating_enum = postgresql.ENUM(
    "CORRECT",
    "PARTIALLY_CORRECT",
    "INCORRECT",
    "NOT_AVAILABLE",
    name="diagnosis_rating",
    create_type=False,
)
benchmark_status_enum = postgresql.ENUM(
    "PASSED",
    "FAILED",
    "INCOMPLETE",
    name="benchmark_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    chaos_scenario_type_enum.create(bind, checkfirst=True)
    chaos_run_status_enum.create(bind, checkfirst=True)
    chaos_observation_type_enum.create(bind, checkfirst=True)
    diagnosis_rating_enum.create(bind, checkfirst=True)
    benchmark_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "chaos_experiments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scenario_type", chaos_scenario_type_enum, nullable=False),
        sa.Column("target_service_id", sa.String(length=36), nullable=False),
        sa.Column("target_environment", sa.String(length=100), nullable=False),
        sa.Column("target_namespace", sa.String(length=255), nullable=False),
        sa.Column("failure_type", sa.String(length=100), nullable=False),
        sa.Column(
            "failure_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "expected_behavior",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_service_id"],
            ["services.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chaos_experiments_service_environment",
        "chaos_experiments",
        ["target_service_id", "target_environment"],
    )
    op.create_index(
        "ix_chaos_experiments_scenario_enabled",
        "chaos_experiments",
        ["scenario_type", "enabled"],
    )

    op.create_table(
        "chaos_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("experiment_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            chaos_run_status_enum,
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("triggered_by", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "failure_injected_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aborted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("incident_id", sa.UUID(), nullable=True),
        sa.Column("rca_report_id", sa.UUID(), nullable=True),
        sa.Column("remediation_id", sa.UUID(), nullable=True),
        sa.Column("remediation_execution_id", sa.UUID(), nullable=True),
        sa.Column("recovery_verification_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL "
            "OR completed_at >= started_at",
            name="ck_chaos_run_completed_after_started",
        ),
        sa.CheckConstraint(
            "aborted_at IS NULL OR started_at IS NULL "
            "OR aborted_at >= started_at",
            name="ck_chaos_run_aborted_after_started",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["chaos_experiments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rca_report_id"],
            ["rca_reports.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["remediation_id"],
            ["remediation_recommendations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["remediation_execution_id"],
            ["remediation_executions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_verification_id"],
            ["recovery_verifications.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chaos_runs_experiment_started",
        "chaos_runs",
        ["experiment_id", "started_at"],
    )
    op.create_index("ix_chaos_runs_status", "chaos_runs", ["status"])
    op.create_index(
        "ix_chaos_runs_incident_id",
        "chaos_runs",
        ["incident_id"],
    )

    op.create_table(
        "chaos_observations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chaos_run_id", sa.UUID(), nullable=False),
        sa.Column(
            "observation_type",
            chaos_observation_type_enum,
            nullable=False,
        ),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(length=100), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chaos_run_id"],
            ["chaos_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chaos_observations_run_observed",
        "chaos_observations",
        ["chaos_run_id", "observed_at"],
    )
    op.create_index(
        "ix_chaos_observations_type_observed",
        "chaos_observations",
        ["observation_type", "observed_at"],
    )

    op.create_table(
        "experiment_benchmarks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chaos_run_id", sa.UUID(), nullable=False),
        sa.Column("failure_injection_timestamp", sa.DateTime(timezone=True)),
        sa.Column("first_anomaly_timestamp", sa.DateTime(timezone=True)),
        sa.Column("alert_creation_timestamp", sa.DateTime(timezone=True)),
        sa.Column("incident_creation_timestamp", sa.DateTime(timezone=True)),
        sa.Column("rca_completion_timestamp", sa.DateTime(timezone=True)),
        sa.Column("remediation_approval_timestamp", sa.DateTime(timezone=True)),
        sa.Column("recovery_completion_timestamp", sa.DateTime(timezone=True)),
        sa.Column("time_to_detect_ms", sa.Integer(), nullable=True),
        sa.Column("time_to_alert_ms", sa.Integer(), nullable=True),
        sa.Column("time_to_incident_ms", sa.Integer(), nullable=True),
        sa.Column("time_to_diagnose_ms", sa.Integer(), nullable=True),
        sa.Column("time_to_approve_ms", sa.Integer(), nullable=True),
        sa.Column("time_to_recover_ms", sa.Integer(), nullable=True),
        sa.Column(
            "diagnosis_rating",
            diagnosis_rating_enum,
            server_default="NOT_AVAILABLE",
            nullable=False,
        ),
        sa.Column("expected_root_cause", sa.Text(), nullable=True),
        sa.Column("actual_root_cause", sa.Text(), nullable=True),
        sa.Column("detection_succeeded", sa.Boolean(), nullable=True),
        sa.Column("recovery_succeeded", sa.Boolean(), nullable=True),
        sa.Column(
            "benchmark_status",
            benchmark_status_enum,
            server_default="INCOMPLETE",
            nullable=False,
        ),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "time_to_detect_ms IS NULL OR time_to_detect_ms >= 0",
            name="ck_experiment_benchmark_detect_nonnegative",
        ),
        sa.CheckConstraint(
            "time_to_alert_ms IS NULL OR time_to_alert_ms >= 0",
            name="ck_experiment_benchmark_alert_nonnegative",
        ),
        sa.CheckConstraint(
            "time_to_incident_ms IS NULL OR time_to_incident_ms >= 0",
            name="ck_experiment_benchmark_incident_nonnegative",
        ),
        sa.CheckConstraint(
            "time_to_diagnose_ms IS NULL OR time_to_diagnose_ms >= 0",
            name="ck_experiment_benchmark_diagnose_nonnegative",
        ),
        sa.CheckConstraint(
            "time_to_approve_ms IS NULL OR time_to_approve_ms >= 0",
            name="ck_experiment_benchmark_approve_nonnegative",
        ),
        sa.CheckConstraint(
            "time_to_recover_ms IS NULL OR time_to_recover_ms >= 0",
            name="ck_experiment_benchmark_recover_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["chaos_run_id"],
            ["chaos_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chaos_run_id"),
    )
    op.create_index(
        "ix_experiment_benchmarks_status_calculated",
        "experiment_benchmarks",
        ["benchmark_status", "calculated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_experiment_benchmarks_status_calculated",
        table_name="experiment_benchmarks",
    )
    op.drop_table("experiment_benchmarks")
    op.drop_index(
        "ix_chaos_observations_type_observed",
        table_name="chaos_observations",
    )
    op.drop_index(
        "ix_chaos_observations_run_observed",
        table_name="chaos_observations",
    )
    op.drop_table("chaos_observations")
    op.drop_index("ix_chaos_runs_incident_id", table_name="chaos_runs")
    op.drop_index("ix_chaos_runs_status", table_name="chaos_runs")
    op.drop_index(
        "ix_chaos_runs_experiment_started",
        table_name="chaos_runs",
    )
    op.drop_table("chaos_runs")
    op.drop_index(
        "ix_chaos_experiments_scenario_enabled",
        table_name="chaos_experiments",
    )
    op.drop_index(
        "ix_chaos_experiments_service_environment",
        table_name="chaos_experiments",
    )
    op.drop_table("chaos_experiments")

    bind = op.get_bind()
    benchmark_status_enum.drop(bind, checkfirst=True)
    diagnosis_rating_enum.drop(bind, checkfirst=True)
    chaos_observation_type_enum.drop(bind, checkfirst=True)
    chaos_run_status_enum.drop(bind, checkfirst=True)
    chaos_scenario_type_enum.drop(bind, checkfirst=True)