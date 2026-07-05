"""add incidents table

Revision ID: 34cd9e1fdbc6
Revises: 847c900aa085
Create Date: 2026-07-04 19:51:49.424569

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '34cd9e1fdbc6'
down_revision: Union[str, Sequence[str], None] = '847c900aa085'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),

        sa.Column("service_id", sa.String(), nullable=True),
        sa.Column("service_name", sa.String(), nullable=True),
        sa.Column("environment", sa.String(), nullable=True),

        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),

        sa.Column("incident_type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),

        sa.Column("source_event_id", sa.String(), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("snapshot_id", sa.String(), nullable=True),

        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("raw_event", sa.JSON(), nullable=True),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),

        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_event_id"),
    )

    op.create_index("ix_incidents_service_id", "incidents", ["service_id"])
    op.create_index("ix_incidents_service_name", "incidents", ["service_name"])
    op.create_index("ix_incidents_environment", "incidents", ["environment"])
    op.create_index("ix_incidents_severity", "incidents", ["severity"])
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_incident_type", "incidents", ["incident_type"])
    op.create_index("ix_incidents_source_event_id", "incidents", ["source_event_id"])
    op.create_index("ix_incidents_correlation_id", "incidents", ["correlation_id"])
    op.create_index("ix_incidents_snapshot_id", "incidents", ["snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_incidents_snapshot_id", table_name="incidents")
    op.drop_index("ix_incidents_correlation_id", table_name="incidents")
    op.drop_index("ix_incidents_source_event_id", table_name="incidents")
    op.drop_index("ix_incidents_incident_type", table_name="incidents")
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_index("ix_incidents_severity", table_name="incidents")
    op.drop_index("ix_incidents_environment", table_name="incidents")
    op.drop_index("ix_incidents_service_name", table_name="incidents")
    op.drop_index("ix_incidents_service_id", table_name="incidents")
    op.drop_table("incidents")