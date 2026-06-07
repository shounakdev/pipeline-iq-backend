"""add platformiq auth and control plane tables

Revision ID: a4317896711c
Revises: 
Create Date: 2026-06-07 01:38:37.050866

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4317896711c'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column('users', sa.Column('password_hash', sa.String(), nullable=True))
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=True))

    op.add_column('audit_events', sa.Column('details', sa.Text(), nullable=True))
    
def downgrade() -> None:
    """Downgrade schema."""

    op.drop_column('audit_events', 'details')
    op.drop_column('users', 'is_active')
    op.drop_column('users', 'password_hash')