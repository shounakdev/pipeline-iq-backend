"""extend pipeline run intelligence fields

Revision ID: 1decaa63e574
Revises: a4317896711c
Create Date: 2026-06-13 08:56:50.821164
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1decaa63e574"
down_revision: Union[str, Sequence[str], None] = "a4317896711c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column("pipeline_runs", sa.Column("repo_url", sa.String(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("stage", sa.String(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("failure_reason", sa.Text(), nullable=True))

    op.add_column("pipeline_runs", sa.Column("commit_sha", sa.String(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("commit_message", sa.Text(), nullable=True))

    op.add_column("pipeline_runs", sa.Column("build_status", sa.String(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("test_status", sa.String(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("sonar_status", sa.String(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("trivy_status", sa.String(), nullable=True))

    op.add_column("pipeline_runs", sa.Column("coverage", sa.Float(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("bugs", sa.Integer(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("vulnerabilities", sa.Integer(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("code_smells", sa.Integer(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("duplicated_lines_density", sa.Float(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("quality_gate", sa.String(), nullable=True))

    op.add_column("pipeline_runs", sa.Column("sonar_report_url", sa.String(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("sonar_issues", sa.JSON(), nullable=True))

    op.add_column("pipeline_runs", sa.Column("trivy_critical", sa.Integer(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("trivy_high", sa.Integer(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("trivy_medium", sa.Integer(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("trivy_low", sa.Integer(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("trivy_unknown", sa.Integer(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("trivy_total", sa.Integer(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("trivy_report", sa.JSON(), nullable=True))

    op.add_column("pipeline_runs", sa.Column("risk_score", sa.Float(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("risk_level", sa.String(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("risk_summary", sa.Text(), nullable=True))

    op.add_column("pipeline_runs", sa.Column("ai_summary", sa.Text(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("recommendations", sa.JSON(), nullable=True))

    op.add_column("pipeline_runs", sa.Column("logs", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_column("pipeline_runs", "logs")
    op.drop_column("pipeline_runs", "recommendations")
    op.drop_column("pipeline_runs", "ai_summary")

    op.drop_column("pipeline_runs", "risk_summary")
    op.drop_column("pipeline_runs", "risk_level")
    op.drop_column("pipeline_runs", "risk_score")

    op.drop_column("pipeline_runs", "trivy_report")
    op.drop_column("pipeline_runs", "trivy_total")
    op.drop_column("pipeline_runs", "trivy_unknown")
    op.drop_column("pipeline_runs", "trivy_low")
    op.drop_column("pipeline_runs", "trivy_medium")
    op.drop_column("pipeline_runs", "trivy_high")
    op.drop_column("pipeline_runs", "trivy_critical")

    op.drop_column("pipeline_runs", "sonar_issues")
    op.drop_column("pipeline_runs", "sonar_report_url")

    op.drop_column("pipeline_runs", "quality_gate")
    op.drop_column("pipeline_runs", "duplicated_lines_density")
    op.drop_column("pipeline_runs", "code_smells")
    op.drop_column("pipeline_runs", "vulnerabilities")
    op.drop_column("pipeline_runs", "bugs")
    op.drop_column("pipeline_runs", "coverage")

    op.drop_column("pipeline_runs", "trivy_status")
    op.drop_column("pipeline_runs", "sonar_status")
    op.drop_column("pipeline_runs", "test_status")
    op.drop_column("pipeline_runs", "build_status")

    op.drop_column("pipeline_runs", "commit_message")
    op.drop_column("pipeline_runs", "commit_sha")

    op.drop_column("pipeline_runs", "failure_reason")
    op.drop_column("pipeline_runs", "stage")
    op.drop_column("pipeline_runs", "repo_url")
