"""add sprint 9a remediation models

Revision ID: 18c41c7de399
Revises: 588e4ea72ee4
Create Date: 2026-08-01 19:36:31.812789

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "18c41c7de399"
down_revision: Union[str, Sequence[str], None] = "588e4ea72ee4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


remediation_action_type_enum = postgresql.ENUM(
    "ROLLBACK_DEPLOYMENT",
    "RESTART_POD",
    "SCALE_REPLICAS",
    "REDEPLOY_REVISION",
    name="remediation_action_type",
    create_type=False,
)


recommendation_status_enum = postgresql.ENUM(
    "PENDING_APPROVAL",
    "APPROVED",
    "REJECTED",
    "EXECUTING",
    "COMPLETED",
    "FAILED",
    "RECOVERY_VERIFIED",
    "RECOVERY_FAILED",
    name="recommendation_status",
    create_type=False,
)


remediation_approval_decision_enum = postgresql.ENUM(
    "APPROVED",
    "REJECTED",
    name="remediation_approval_decision",
    create_type=False,
)


remediation_execution_status_enum = postgresql.ENUM(
    "PENDING",
    "IN_PROGRESS",
    "SUCCEEDED",
    "FAILED",
    name="remediation_execution_status",
    create_type=False,
)


recovery_verification_status_enum = postgresql.ENUM(
    "PENDING",
    "VERIFIED",
    "FAILED",
    name="recovery_verification_status",
    create_type=False,
)


# This enum already exists from Sprint 8B.
rca_confidence_enum = postgresql.ENUM(
    "LOW",
    "MEDIUM",
    "HIGH",
    name="rca_confidence",
    create_type=False,
)


def upgrade() -> None:
    """Create the Sprint 9A remediation persistence models."""

    bind = op.get_bind()

    remediation_action_type_enum.create(bind, checkfirst=True)
    recommendation_status_enum.create(bind, checkfirst=True)
    remediation_approval_decision_enum.create(bind, checkfirst=True)
    remediation_execution_status_enum.create(bind, checkfirst=True)
    recovery_verification_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "remediation_recommendations",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "incident_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "service_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "environment",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "action_type",
            remediation_action_type_enum,
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "evidence_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "confidence",
            rca_confidence_enum,
            nullable=False,
        ),
        sa.Column(
            "status",
            recommendation_status_enum,
            server_default="PENDING_APPROVAL",
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.String(length=36),
            nullable=True,
        ),
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
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_remediation_recommendations_incident_created",
        "remediation_recommendations",
        ["incident_id", "created_at"],
        unique=False,
    )

    op.create_index(
        "ix_remediation_recommendations_service_environment",
        "remediation_recommendations",
        ["service_id", "environment"],
        unique=False,
    )

    op.create_index(
        "ix_remediation_recommendations_status",
        "remediation_recommendations",
        ["status"],
        unique=False,
    )

    op.create_table(
        "remediation_approvals",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "remediation_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "approved_by",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column(
            "decision",
            remediation_approval_decision_enum,
            nullable=False,
        ),
        sa.Column(
            "rejection_reason",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision != 'REJECTED' OR "
            "(rejection_reason IS NOT NULL "
            "AND length(trim(rejection_reason)) > 0)",
            name="ck_remediation_approval_rejection_reason",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["remediation_id"],
            ["remediation_recommendations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "remediation_id",
            name="uq_remediation_approvals_remediation_id",
        ),
    )

    op.create_index(
        "ix_remediation_approvals_remediation_id",
        "remediation_approvals",
        ["remediation_id"],
        unique=False,
    )

    op.create_table(
        "remediation_executions",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "remediation_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "command_type",
            remediation_action_type_enum,
            nullable=False,
        ),
        sa.Column(
            "command_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "execution_status",
            remediation_execution_status_enum,
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "result_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "completed_at IS NULL "
            "OR started_at IS NULL "
            "OR completed_at >= started_at",
            name="ck_remediation_execution_timestamp_order",
        ),
        sa.ForeignKeyConstraint(
            ["remediation_id"],
            ["remediation_recommendations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_remediation_executions_remediation_status",
        "remediation_executions",
        ["remediation_id", "execution_status"],
        unique=False,
    )

    op.create_index(
        "ix_remediation_executions_started_at",
        "remediation_executions",
        ["started_at"],
        unique=False,
    )

    op.create_table(
        "recovery_verifications",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "remediation_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "remediation_execution_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "verification_status",
            recovery_verification_status_enum,
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "error_rate_recovered",
            sa.Boolean(),
            nullable=True,
        ),
        sa.Column(
            "latency_recovered",
            sa.Boolean(),
            nullable=True,
        ),
        sa.Column(
            "pods_healthy",
            sa.Boolean(),
            nullable=True,
        ),
        sa.Column(
            "restart_loop_absent",
            sa.Boolean(),
            nullable=True,
        ),
        sa.Column(
            "availability_restored",
            sa.Boolean(),
            nullable=True,
        ),
        sa.Column(
            "metrics_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "verification_status = 'PENDING' "
            "OR verified_at IS NOT NULL",
            name="ck_recovery_verification_verified_at",
        ),
        sa.ForeignKeyConstraint(
            ["remediation_execution_id"],
            ["remediation_executions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["remediation_id"],
            ["remediation_recommendations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "remediation_execution_id",
            name="uq_recovery_verifications_execution_id",
        ),
    )

    op.create_index(
        "ix_recovery_verifications_remediation_id",
        "recovery_verifications",
        ["remediation_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the Sprint 9A remediation persistence models."""

    op.drop_index(
        "ix_recovery_verifications_remediation_id",
        table_name="recovery_verifications",
    )
    op.drop_table("recovery_verifications")

    op.drop_index(
        "ix_remediation_executions_started_at",
        table_name="remediation_executions",
    )
    op.drop_index(
        "ix_remediation_executions_remediation_status",
        table_name="remediation_executions",
    )
    op.drop_table("remediation_executions")

    op.drop_index(
        "ix_remediation_approvals_remediation_id",
        table_name="remediation_approvals",
    )
    op.drop_table("remediation_approvals")

    op.drop_index(
        "ix_remediation_recommendations_status",
        table_name="remediation_recommendations",
    )
    op.drop_index(
        "ix_remediation_recommendations_service_environment",
        table_name="remediation_recommendations",
    )
    op.drop_index(
        "ix_remediation_recommendations_incident_created",
        table_name="remediation_recommendations",
    )
    op.drop_table("remediation_recommendations")

    bind = op.get_bind()

    recovery_verification_status_enum.drop(bind, checkfirst=True)
    remediation_execution_status_enum.drop(bind, checkfirst=True)
    remediation_approval_decision_enum.drop(bind, checkfirst=True)
    recommendation_status_enum.drop(bind, checkfirst=True)
    remediation_action_type_enum.drop(bind, checkfirst=True)