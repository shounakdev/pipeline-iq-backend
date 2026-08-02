"""persist structured rca report payload

Revision ID: 2a1af6d32b59
Revises: 18c41c7de399
Create Date: 2026-08-01 20:33:17.154166
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "2a1af6d32b59"
down_revision: Union[str, Sequence[str], None] = "18c41c7de399"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rca_reports",
        sa.Column(
            "report_json",
            postgresql.JSONB(
                astext_type=sa.Text(),
            ),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "rca_reports",
        "report_json",
    )