"""add reliability tables

Revision ID: fbe13f728ba0
Revises: fef4a77ac3b0
Create Date: 2026-07-11 17:05:56.264851
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "fbe13f728ba0"
down_revision: Union[str, None] = "fef4a77ac3b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


slo_metric_type_enum = postgresql.ENUM(
    "AVAILABILITY",
    "P95_LATENCY",
    "ERROR_RATE",
    name="slo_metric_type",
    create_type=False,
)

reliability_severity_enum = postgresql.ENUM(
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
    name="reliability_severity",
    create_type=False,
)

error_budget_state_enum = postgresql.ENUM(
    "HEALTHY",
    "WARNING",
    "BREACHED",
    "EXHAUSTED",
    name="error_budget_state",
    create_type=False,
)

reliability_alert_type_enum = postgresql.ENUM(
    "SLO_BREACH",
    "ERROR_BUDGET_BURN",
    "ERROR_BUDGET_EXHAUSTED",
    "LATENCY_BREACH",
    "AVAILABILITY_BREACH",
    "ERROR_RATE_BREACH",
    name="reliability_alert_type",
    create_type=False,
)

reliability_alert_status_enum = postgresql.ENUM(
    "OPEN",
    "ACKNOWLEDGED",
    "RESOLVED",
    "FALSE_POSITIVE",
    name="reliability_alert_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    slo_metric_type_enum.create(bind, checkfirst=True)
    reliability_severity_enum.create(bind, checkfirst=True)
    error_budget_state_enum.create(bind, checkfirst=True)
    reliability_alert_type_enum.create(bind, checkfirst=True)
    reliability_alert_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "slo_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("service_id", sa.String(length=36), nullable=False),
        sa.Column(
            "metric_type",
            slo_metric_type_enum,
            nullable=False,
        ),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column(
            "window_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "severity_on_breach",
            reliability_severity_enum,
            nullable=False,
            server_default=sa.text("'HIGH'"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_slo_definitions_service_id",
        "slo_definitions",
        ["service_id"],
        unique=False,
    )

    op.create_table(
        "slo_measurements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "slo_definition_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("service_id", sa.String(length=36), nullable=False),
        sa.Column(
            "metric_type",
            slo_metric_type_enum,
            nullable=False,
        ),
        sa.Column("measured_value", sa.Float(), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("is_breached", sa.Boolean(), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'PROMETHEUS'"),
        ),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["slo_definition_id"],
            ["slo_definitions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_slo_measurements_slo_definition_id",
        "slo_measurements",
        ["slo_definition_id"],
        unique=False,
    )

    op.create_index(
        "ix_slo_measurements_service_id",
        "slo_measurements",
        ["service_id"],
        unique=False,
    )

    op.create_index(
        "ix_slo_measurements_evaluated_at",
        "slo_measurements",
        ["evaluated_at"],
        unique=False,
    )

    op.create_table(
        "error_budget_statuses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "slo_definition_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("service_id", sa.String(length=36), nullable=False),
        sa.Column("target_percentage", sa.Float(), nullable=False),
        sa.Column(
            "allowed_failure_percentage",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "consumed_percentage",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "remaining_percentage",
            sa.Float(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "burn_rate",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "status",
            error_budget_state_enum,
            nullable=False,
            server_default=sa.text("'HEALTHY'"),
        ),
        sa.Column("window_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["slo_definition_id"],
            ["slo_definitions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_error_budget_statuses_slo_definition_id",
        "error_budget_statuses",
        ["slo_definition_id"],
        unique=False,
    )

    op.create_index(
        "ix_error_budget_statuses_service_id",
        "error_budget_statuses",
        ["service_id"],
        unique=False,
    )

    op.create_index(
        "ix_error_budget_statuses_evaluated_at",
        "error_budget_statuses",
        ["evaluated_at"],
        unique=False,
    )

    op.create_table(
        "reliability_alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("service_id", sa.String(length=36), nullable=False),
        sa.Column(
            "slo_definition_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "alert_type",
            reliability_alert_type_enum,
            nullable=False,
        ),
        sa.Column(
            "severity",
            reliability_severity_enum,
            nullable=False,
        ),
        sa.Column("triggered_value", sa.Float(), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column(
            "deployment_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            reliability_alert_status_enum,
            nullable=False,
            server_default=sa.text("'OPEN'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["slo_definition_id"],
            ["slo_definitions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deployment_id"],
            ["deployments.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_reliability_alerts_service_id",
        "reliability_alerts",
        ["service_id"],
        unique=False,
    )

    op.create_index(
        "ix_reliability_alerts_slo_definition_id",
        "reliability_alerts",
        ["slo_definition_id"],
        unique=False,
    )

    op.create_index(
        "ix_reliability_alerts_deployment_id",
        "reliability_alerts",
        ["deployment_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index(
        "ix_reliability_alerts_deployment_id",
        table_name="reliability_alerts",
    )
    op.drop_index(
        "ix_reliability_alerts_slo_definition_id",
        table_name="reliability_alerts",
    )
    op.drop_index(
        "ix_reliability_alerts_service_id",
        table_name="reliability_alerts",
    )
    op.drop_table("reliability_alerts")

    op.drop_index(
        "ix_error_budget_statuses_evaluated_at",
        table_name="error_budget_statuses",
    )
    op.drop_index(
        "ix_error_budget_statuses_service_id",
        table_name="error_budget_statuses",
    )
    op.drop_index(
        "ix_error_budget_statuses_slo_definition_id",
        table_name="error_budget_statuses",
    )
    op.drop_table("error_budget_statuses")

    op.drop_index(
        "ix_slo_measurements_evaluated_at",
        table_name="slo_measurements",
    )
    op.drop_index(
        "ix_slo_measurements_service_id",
        table_name="slo_measurements",
    )
    op.drop_index(
        "ix_slo_measurements_slo_definition_id",
        table_name="slo_measurements",
    )
    op.drop_table("slo_measurements")

    op.drop_index(
        "ix_slo_definitions_service_id",
        table_name="slo_definitions",
    )
    op.drop_table("slo_definitions")

    reliability_alert_status_enum.drop(bind, checkfirst=True)
    reliability_alert_type_enum.drop(bind, checkfirst=True)
    error_budget_state_enum.drop(bind, checkfirst=True)
    reliability_severity_enum.drop(bind, checkfirst=True)
    slo_metric_type_enum.drop(bind, checkfirst=True)