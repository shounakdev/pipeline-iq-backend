"""add event backbone tables

Revision ID: 4d8e1746b82e
Revises: 533b2a32e166
Create Date: 2026-06-27 14:37:20.888314
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4d8e1746b82e"
down_revision: Union[str, Sequence[str], None] = "533b2a32e166"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_records",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("service_id", sa.String(), nullable=True),
        sa.Column("environment", sa.String(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("processing_status", sa.String(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_event_records_event_id", "event_records", ["event_id"], unique=True)
    op.create_index("ix_event_records_event_type", "event_records", ["event_type"])
    op.create_index("ix_event_records_topic", "event_records", ["topic"])
    op.create_index("ix_event_records_correlation_id", "event_records", ["correlation_id"])
    op.create_index("ix_event_records_service_id", "event_records", ["service_id"])
    op.create_index("ix_event_records_environment", "event_records", ["environment"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("service_id", sa.String(), nullable=True),
        sa.Column("environment", sa.String(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_outbox_events_event_id", "outbox_events", ["event_id"], unique=True)
    op.create_index("ix_outbox_events_topic", "outbox_events", ["topic"])
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_correlation_id", "outbox_events", ["correlation_id"])
    op.create_index("ix_outbox_events_service_id", "outbox_events", ["service_id"])
    op.create_index("ix_outbox_events_environment", "outbox_events", ["environment"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])

    op.create_table(
        "consumer_checkpoints",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("consumer_name", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("partition", sa.Integer(), nullable=False),
        sa.Column("offset", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "consumer_name",
            "topic",
            "partition",
            name="uq_consumer_topic_partition",
        ),
    )

    op.create_table(
        "dead_letter_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("original_topic", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("service_id", sa.String(), nullable=True),
        sa.Column("environment", sa.String(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_dead_letter_events_event_id", "dead_letter_events", ["event_id"])
    op.create_index("ix_dead_letter_events_original_topic", "dead_letter_events", ["original_topic"])
    op.create_index("ix_dead_letter_events_event_type", "dead_letter_events", ["event_type"])
    op.create_index("ix_dead_letter_events_correlation_id", "dead_letter_events", ["correlation_id"])
    op.create_index("ix_dead_letter_events_service_id", "dead_letter_events", ["service_id"])
    op.create_index("ix_dead_letter_events_environment", "dead_letter_events", ["environment"])
    op.create_index("ix_dead_letter_events_status", "dead_letter_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_dead_letter_events_status", table_name="dead_letter_events")
    op.drop_index("ix_dead_letter_events_environment", table_name="dead_letter_events")
    op.drop_index("ix_dead_letter_events_service_id", table_name="dead_letter_events")
    op.drop_index("ix_dead_letter_events_correlation_id", table_name="dead_letter_events")
    op.drop_index("ix_dead_letter_events_event_type", table_name="dead_letter_events")
    op.drop_index("ix_dead_letter_events_original_topic", table_name="dead_letter_events")
    op.drop_index("ix_dead_letter_events_event_id", table_name="dead_letter_events")
    op.drop_table("dead_letter_events")

    op.drop_table("consumer_checkpoints")

    op.drop_index("ix_outbox_events_status", table_name="outbox_events")
    op.drop_index("ix_outbox_events_environment", table_name="outbox_events")
    op.drop_index("ix_outbox_events_service_id", table_name="outbox_events")
    op.drop_index("ix_outbox_events_correlation_id", table_name="outbox_events")
    op.drop_index("ix_outbox_events_event_type", table_name="outbox_events")
    op.drop_index("ix_outbox_events_topic", table_name="outbox_events")
    op.drop_index("ix_outbox_events_event_id", table_name="outbox_events")
    op.drop_table("outbox_events")

    op.drop_index("ix_event_records_environment", table_name="event_records")
    op.drop_index("ix_event_records_service_id", table_name="event_records")
    op.drop_index("ix_event_records_correlation_id", table_name="event_records")
    op.drop_index("ix_event_records_topic", table_name="event_records")
    op.drop_index("ix_event_records_event_type", table_name="event_records")
    op.drop_index("ix_event_records_event_id", table_name="event_records")
    op.drop_table("event_records")
