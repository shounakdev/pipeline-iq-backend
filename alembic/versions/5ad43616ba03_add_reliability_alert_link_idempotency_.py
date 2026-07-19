"""add reliability alert link idempotency constraint

Revision ID: 5ad43616ba03
Revises: a2f39e69aa46
Create Date: 2026-07-17

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "5ad43616ba03"
down_revision = "a2f39e69aa46"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Ensure one reliability alert can only link to one incident."""

    op.create_unique_constraint(
        "uq_incident_alert_links_reliability_alert_id",
        "incident_alert_links",
        ["reliability_alert_id"],
    )


def downgrade() -> None:
    """Remove the global reliability-alert uniqueness constraint."""

    op.drop_constraint(
        "uq_incident_alert_links_reliability_alert_id",
        "incident_alert_links",
        type_="unique",
    )
