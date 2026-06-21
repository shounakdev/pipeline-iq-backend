"""add deployment models

Revision ID: 533b2a32e166
Revises: 9cf7d8bd1263
Create Date: 2026-06-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "533b2a32e166"
down_revision: Union[str, Sequence[str], None] = "9cf7d8bd1263"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deployments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", sa.String(length=36), nullable=False),
        sa.Column("pipeline_run_id", sa.String(length=36), nullable=True),
        sa.Column("environment_id", sa.String(length=36), nullable=True),
        sa.Column("commit_sha", sa.String(length=100), nullable=True),
        sa.Column("image_tag", sa.String(length=255), nullable=False),
        sa.Column("deployment_version", sa.String(length=50), nullable=True),
        sa.Column("argo_sync_status", sa.String(length=50), nullable=True),
        sa.Column("kubernetes_rollout_status", sa.String(length=50), nullable=True),
        sa.Column("previous_revision", sa.String(length=100), nullable=True),
        sa.Column("namespace", sa.String(length=100), nullable=True),
        sa.Column("cluster_name", sa.String(length=100), nullable=True),
        sa.Column("service_name", sa.String(length=150), nullable=True),
        sa.Column("argo_application_name", sa.String(length=150), nullable=True),
        sa.Column("pod_count", sa.Integer(), nullable=True),
        sa.Column("restart_count", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"]),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "deployment_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deployment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.String(length=100), nullable=True),
        sa.Column("image_tag", sa.String(length=255), nullable=True),
        sa.Column("commit_sha", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "kubernetes_workloads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deployment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workload_name", sa.String(length=150), nullable=False),
        sa.Column("namespace", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("desired_replicas", sa.Integer(), nullable=True),
        sa.Column("available_replicas", sa.Integer(), nullable=True),
        sa.Column("pod_count", sa.Integer(), nullable=True),
        sa.Column("restart_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("kubernetes_workloads")
    op.drop_table("deployment_revisions")
    op.drop_table("deployments")
