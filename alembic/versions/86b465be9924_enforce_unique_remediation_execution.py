"""enforce unique remediation execution

Revision ID: 86b465be9924
Revises: 2a1af6d32b59
Create Date: 2026-08-01 22:40:04.082433

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '86b465be9924'
down_revision: Union[str, Sequence[str], None] = '2a1af6d32b59'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_remediation_executions_remediation_id",
        "remediation_executions",
        ["remediation_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_remediation_executions_remediation_id",
        "remediation_executions",
        type_="unique",
    )