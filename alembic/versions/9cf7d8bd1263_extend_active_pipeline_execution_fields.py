"""extend active pipeline execution fields

Revision ID: 9cf7d8bd1263
Revises: 1decaa63e574
Create Date: 2026-06-13 16:44:16.240257

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9cf7d8bd1263'
down_revision: Union[str, Sequence[str], None] = '1decaa63e574'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column("pipelines", sa.Column("stage", sa.String(), nullable=True))
    op.add_column("pipelines", sa.Column("failure_reason", sa.Text(), nullable=True))

    op.add_column("pipelines", sa.Column("commit_sha", sa.String(), nullable=True))
    op.add_column("pipelines", sa.Column("commit_message", sa.Text(), nullable=True))

    op.add_column("pipelines", sa.Column("build_status", sa.String(), nullable=True))
    op.add_column("pipelines", sa.Column("test_status", sa.String(), nullable=True))
    op.add_column("pipelines", sa.Column("sonar_status", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_column("pipelines", "sonar_status")
    op.drop_column("pipelines", "test_status")
    op.drop_column("pipelines", "build_status")

    op.drop_column("pipelines", "commit_message")
    op.drop_column("pipelines", "commit_sha")

    op.drop_column("pipelines", "failure_reason")
    op.drop_column("pipelines", "stage")