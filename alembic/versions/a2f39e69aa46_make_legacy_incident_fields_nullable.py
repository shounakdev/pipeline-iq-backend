"""make legacy incident fields nullable

Revision ID: a2f39e69aa46
Revises: 26e5497f9375
Create Date: 2026-07-16 16:26:43.231657

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2f39e69aa46'
down_revision: Union[str, Sequence[str], None] = '26e5497f9375'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "incidents",
        "service_id",
        existing_type=sa.String(),
        nullable=True,
    )

    op.alter_column(
        "incidents",
        "correlation_id",
        existing_type=sa.String(),
        nullable=True,
    )

    op.alter_column(
        "incidents",
        "started_at",
        existing_type=sa.DateTime(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE incidents
        SET service_id = primary_service_id
        WHERE service_id IS NULL
        """
    )

    op.execute(
        """
        UPDATE incidents
        SET correlation_id = incident_number
        WHERE correlation_id IS NULL
        """
    )

    op.execute(
        """
        UPDATE incidents
        SET started_at = detected_at
        WHERE started_at IS NULL
        """
    )

    op.alter_column(
        "incidents",
        "started_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )

    op.alter_column(
        "incidents",
        "correlation_id",
        existing_type=sa.String(),
        nullable=False,
    )

    op.alter_column(
        "incidents",
        "service_id",
        existing_type=sa.String(),
        nullable=False,
    )