"""clear legacy incident failure started at

Revision ID: 7a2aae75fdfd
Revises: 5ad43616ba03
"""

from typing import Sequence, Union

from alembic import op


revision: str = "7a2aae75fdfd"
down_revision: Union[str, Sequence[str], None] = "5ad43616ba03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Clear timestamps backfilled for incidents created before this field."""
    op.execute(
        """
        UPDATE incidents
        SET failure_started_at = NULL
        """
    )


def downgrade() -> None:
    """Legacy fabricated timestamps cannot be safely restored."""
    pass
