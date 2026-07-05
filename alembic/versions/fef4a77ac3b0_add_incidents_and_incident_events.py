"""add incidents and incident events

Revision ID: fef4a77ac3b0
Revises: 34cd9e1fdbc6
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "fef4a77ac3b0"
down_revision = "34cd9e1fdbc6"
branch_labels = None
depends_on = None


incident_severity = postgresql.ENUM(
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
    name="incidentseverity",
    create_type=False,
)

incident_status = postgresql.ENUM(
    "OPEN",
    "ACKNOWLEDGED",
    "RESOLVED",
    "FALSE_POSITIVE",
    name="incidentstatus",
    create_type=False,
)


def upgrade():
    # Local/dev cleanup from previous incident-table attempts.
    op.execute("DROP TABLE IF EXISTS incident_events CASCADE")
    op.execute("DROP TABLE IF EXISTS incidents CASCADE")
    op.execute("DROP TYPE IF EXISTS incidentstatus CASCADE")
    op.execute("DROP TYPE IF EXISTS incidentseverity CASCADE")

    incident_severity.create(op.get_bind(), checkfirst=True)
    incident_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", incident_severity, nullable=False),
        sa.Column("status", incident_status, nullable=False),
        sa.Column("service_id", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("triggered_by_event_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "incident_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_index("ix_incidents_service_id", "incidents", ["service_id"])
    op.create_index("ix_incidents_environment", "incidents", ["environment"])
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_severity", "incidents", ["severity"])
    op.create_index("ix_incidents_correlation_id", "incidents", ["correlation_id"])
    op.create_index(
        "ix_incidents_triggered_by_event_id",
        "incidents",
        ["triggered_by_event_id"],
    )

    op.create_index("ix_incident_events_incident_id", "incident_events", ["incident_id"])
    op.create_index("ix_incident_events_event_type", "incident_events", ["event_type"])


def downgrade():
    op.execute("DROP TABLE IF EXISTS incident_events CASCADE")
    op.execute("DROP TABLE IF EXISTS incidents CASCADE")
    op.execute("DROP TYPE IF EXISTS incidentstatus CASCADE")
    op.execute("DROP TYPE IF EXISTS incidentseverity CASCADE")