"""fix event timestamp defaults

Revision ID: 4869788f7f72
Revises: 9b9bb1e4597e
Create Date: 2026-06-28

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4869788f7f72"
down_revision = "9b9bb1e4597e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "event_records",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.text("now()"),
    )

    op.alter_column(
        "dead_letter_events",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.text("now()"),
    )

    op.alter_column(
        "dead_letter_events",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.alter_column(
        "dead_letter_events",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=None,
    )

    op.alter_column(
        "dead_letter_events",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=None,
    )

    op.alter_column(
        "event_records",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=None,
    )
