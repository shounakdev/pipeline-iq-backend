"""add chaos execution safety

Revision ID: e7b8c9d0a1f2
Revises: c9a8e7d6f5b4
Create Date: 2026-08-08 20:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b8c9d0a1f2"
down_revision: Union[str, Sequence[str], None] = "c9a8e7d6f5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ACTIVE_STATUS_SQL = (
    "status IN ('PENDING', 'RUNNING', 'FAULT_INJECTED', "
    "'OBSERVING', 'RECOVERING')"
)


def upgrade() -> None:
    op.add_column(
        "chaos_runs",
        sa.Column("target_environment", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "chaos_runs",
        sa.Column("target_service_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "chaos_runs",
        sa.Column("target_namespace", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "chaos_runs",
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "chaos_runs",
        sa.Column(
            "cleanup_behavior",
            sa.String(length=32),
            server_default="delete",
            nullable=False,
        ),
    )
    op.add_column(
        "chaos_runs",
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("chaos_runs", sa.Column("kubernetes_resource_kind", sa.String(length=100), nullable=True))
    op.add_column("chaos_runs", sa.Column("kubernetes_resource_name", sa.String(length=253), nullable=True))
    op.add_column("chaos_runs", sa.Column("kubernetes_resource_uid", sa.String(length=128), nullable=True))
    op.add_column("chaos_runs", sa.Column("cleanup_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chaos_runs", sa.Column("cleanup_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chaos_runs", sa.Column("cleanup_succeeded", sa.Boolean(), nullable=True))
    op.add_column("chaos_runs", sa.Column("cleanup_error", sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE chaos_runs AS run
        SET target_environment = experiment.target_environment,
            target_service_id = experiment.target_service_id,
            target_namespace = experiment.target_namespace,
            duration_seconds = 600,
            deadline_at = COALESCE(run.started_at, now()) + interval '10 minutes'
        FROM chaos_experiments AS experiment
        WHERE experiment.id = run.experiment_id
        """
    )
    op.alter_column("chaos_runs", "target_environment", nullable=False)
    op.alter_column("chaos_runs", "target_service_id", nullable=False)
    op.alter_column("chaos_runs", "target_namespace", nullable=False)
    op.alter_column("chaos_runs", "duration_seconds", nullable=False)
    op.alter_column("chaos_runs", "deadline_at", nullable=False)
    op.create_foreign_key(
        "fk_chaos_runs_target_service",
        "chaos_runs",
        "services",
        ["target_service_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_chaos_run_duration_positive",
        "chaos_runs",
        "duration_seconds > 0",
    )
    op.create_check_constraint(
        "ck_chaos_run_cleanup_delete",
        "chaos_runs",
        "cleanup_behavior = 'delete'",
    )
    op.create_check_constraint(
        "ck_chaos_run_cleanup_started",
        "chaos_runs",
        "cleanup_completed_at IS NULL OR cleanup_started_at IS NOT NULL",
    )
    op.create_index("ix_chaos_runs_deadline", "chaos_runs", ["deadline_at"])
    op.create_index(
        "one_active_chaos_run_per_target",
        "chaos_runs",
        ["target_environment", "target_service_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_STATUS_SQL),
    )
    op.create_index(
        "one_active_chaos_run_global",
        "chaos_runs",
        [sa.text("(1)")],
        unique=True,
        postgresql_where=sa.text(ACTIVE_STATUS_SQL),
    )


def downgrade() -> None:
    op.drop_index("one_active_chaos_run_global", table_name="chaos_runs")
    op.drop_index("one_active_chaos_run_per_target", table_name="chaos_runs")
    op.drop_index("ix_chaos_runs_deadline", table_name="chaos_runs")
    op.drop_constraint("ck_chaos_run_cleanup_started", "chaos_runs", type_="check")
    op.drop_constraint("ck_chaos_run_cleanup_delete", "chaos_runs", type_="check")
    op.drop_constraint("ck_chaos_run_duration_positive", "chaos_runs", type_="check")
    op.drop_constraint("fk_chaos_runs_target_service", "chaos_runs", type_="foreignkey")
    for column in (
        "cleanup_error",
        "cleanup_succeeded",
        "cleanup_completed_at",
        "cleanup_started_at",
        "kubernetes_resource_uid",
        "kubernetes_resource_name",
        "kubernetes_resource_kind",
        "deadline_at",
        "cleanup_behavior",
        "duration_seconds",
        "target_namespace",
        "target_service_id",
        "target_environment",
    ):
        op.drop_column("chaos_runs", column)
