"""add service health snapshots

Revision ID: 847c900aa085
Revises: 4869788f7f72
Create Date: 2026-07-04 18:14:40.947822

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '847c900aa085'
down_revision: Union[str, Sequence[str], None] = '4869788f7f72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
    DO $$
    BEGIN
        CREATE TYPE servicehealthstatus AS ENUM ('HEALTHY', 'DEGRADED', 'UNHEALTHY', 'UNKNOWN');
    EXCEPTION
        WHEN duplicate_object THEN null;
    END $$;
    """)

    service_health_status_enum = postgresql.ENUM(
        "HEALTHY",
        "DEGRADED",
        "UNHEALTHY",
        "UNKNOWN",
        name="servicehealthstatus",
        create_type=False,
    )

    op.create_table(
        "service_health_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", sa.String(), nullable=False),
        sa.Column("service_name", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("status", service_health_status_enum, nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("error_rate", sa.Float(), nullable=True),
        sa.Column("cpu_usage", sa.Float(), nullable=True),
        sa.Column("memory_usage", sa.Float(), nullable=True),
        sa.Column("pod_restart_count", sa.Integer(), nullable=True),
        sa.Column("replica_count", sa.Integer(), nullable=True),
        sa.Column("available_replicas", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_service_health_snapshots_service_id"),
        "service_health_snapshots",
        ["service_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_service_health_snapshots_service_name"),
        "service_health_snapshots",
        ["service_name"],
        unique=False,
    )

    op.alter_column(
        "dead_letter_events",
        "updated_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        existing_server_default=sa.text("now()"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "dead_letter_events",
        "updated_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
        existing_server_default=sa.text("now()"),
    )

    op.drop_index(
        op.f("ix_service_health_snapshots_service_name"),
        table_name="service_health_snapshots",
    )
    op.drop_index(
        op.f("ix_service_health_snapshots_service_id"),
        table_name="service_health_snapshots",
    )
    op.drop_table("service_health_snapshots")

    op.execute("DROP TYPE IF EXISTS servicehealthstatus")