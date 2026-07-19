"""add sprint 7b incident response data model

Revision ID: 26e5497f9375
Revises: fbe13f728ba0
Create Date: 2026-07-16 10:11:50.728253

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "26e5497f9375"
down_revision: Union[str, Sequence[str], None] = "fbe13f728ba0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


incident_status_sprint7_enum = postgresql.ENUM(
    "DETECTED",
    "ACKNOWLEDGED",
    "INVESTIGATING",
    "ACTION_RECOMMENDED",
    "REMEDIATING",
    "RESOLVED",
    "FAILED_RECOVERY",
    name="incidentstatus_sprint7",
    create_type=False,
)

incident_severity_sprint7_enum = postgresql.ENUM(
    "SEV-1",
    "SEV-2",
    "SEV-3",
    name="incidentseverity_sprint7",
    create_type=False,
)

incident_status_enum = postgresql.ENUM(
    "DETECTED",
    "ACKNOWLEDGED",
    "INVESTIGATING",
    "ACTION_RECOMMENDED",
    "REMEDIATING",
    "RESOLVED",
    "FAILED_RECOVERY",
    name="incidentstatus",
    create_type=False,
)

legacy_incident_status_enum = postgresql.ENUM(
    "OPEN",
    "ACKNOWLEDGED",
    "RESOLVED",
    "FALSE_POSITIVE",
    name="incidentstatus_legacy",
    create_type=False,
)

legacy_incident_severity_enum = postgresql.ENUM(
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
    name="incidentseverity_legacy",
    create_type=False,
)


_CREATE_ALL_SCAFFOLDING_TABLES = (
    "incident_alert_links",
    "incident_metrics",
    "incident_comments",
    "incident_assignments",
    "incident_timeline_events",
)


def _remove_empty_create_all_scaffolding() -> None:
    """Remove empty Sprint 7 tables created before Alembic ran.

    Some deployments still call ``Base.metadata.create_all()`` during
    backend startup. After the Sprint 7 models were introduced, that call
    created the new tables alongside the legacy ``incident_events`` table.
    Alembic must remove only those empty scaffolding tables before it can
    rename and migrate the legacy table.

    The migration deliberately aborts rather than dropping any table that
    already contains data.
    """

    bind = op.get_bind()

    for table_name in _CREATE_ALL_SCAFFOLDING_TABLES:
        relation_kind = bind.execute(
            sa.text(
                """
                SELECT c.relkind
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = current_schema()
                  AND c.relname = :table_name
                """
            ),
            {"table_name": table_name},
        ).scalar()

        if relation_kind is None:
            continue

        if relation_kind not in ("r", "p"):
            raise RuntimeError(
                f"Expected {table_name!r} to be a table, "
                f"but PostgreSQL reports relation kind {relation_kind!r}."
            )

        row_count = bind.execute(
            sa.text(f'SELECT COUNT(*) FROM "{table_name}"')
        ).scalar_one()

        if row_count:
            raise RuntimeError(
                f"Refusing to drop pre-created table {table_name!r}: "
                f"it contains {row_count} row(s). Back up and reconcile "
                "those rows before rerunning the migration."
            )

        op.execute(sa.text(f'DROP TABLE "{table_name}" CASCADE'))


def upgrade() -> None:
    """Upgrade the legacy Sprint 5 incident schema without losing data."""

    # Remove only empty tables accidentally created by metadata.create_all().
    # The legacy incident_events table remains untouched and is migrated below.
    _remove_empty_create_all_scaffolding()

    # ------------------------------------------------------------------
    # 1. Create replacement enum types and the incident-number generator.
    #
    # Temporary enum names are required because the legacy enum types use
    # the final names incidentstatus and incidentseverity.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TYPE incidentstatus_sprint7 AS ENUM (
            'DETECTED',
            'ACKNOWLEDGED',
            'INVESTIGATING',
            'ACTION_RECOMMENDED',
            'REMEDIATING',
            'RESOLVED',
            'FAILED_RECOVERY'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE incidentseverity_sprint7 AS ENUM (
            'SEV-1',
            'SEV-2',
            'SEV-3'
        )
        """
    )

    op.execute(
        """
        CREATE SEQUENCE incident_number_seq
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1
        """
    )
    op.execute(
        """
        CREATE FUNCTION next_incident_number()
        RETURNS varchar
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RETURN 'INC-' ||
                   lpad(nextval('incident_number_seq'::regclass)::text, 3, '0');
        END;
        $$
        """
    )

    # Remove legacy indexes before changing enum types and renaming the
    # timeline table. The final index set is recreated at the end.
    op.drop_index("ix_incident_events_event_type", table_name="incident_events")
    op.drop_index("ix_incident_events_incident_id", table_name="incident_events")

    op.drop_index("ix_incidents_service_id", table_name="incidents")
    op.drop_index("ix_incidents_environment", table_name="incidents")
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_index("ix_incidents_severity", table_name="incidents")
    op.drop_index("ix_incidents_correlation_id", table_name="incidents")
    op.drop_index("ix_incidents_triggered_by_event_id", table_name="incidents")

    # ------------------------------------------------------------------
    # 2. Add new incident columns as nullable columns.
    # ------------------------------------------------------------------
    op.add_column(
        "incidents",
        sa.Column("incident_number", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("primary_service_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("triggering_alert_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column(
            "suspected_deployment_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "incidents",
        sa.Column("deduplication_key", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("failure_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column(
            "investigation_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "incidents",
        sa.Column(
            "remediation_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "incidents",
        sa.Column("current_assignee_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("resolution_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("rca_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("remediation_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("created_by", sa.String(length=36), nullable=True),
    )

    # Rename the existing event table instead of dropping it.
    op.rename_table("incident_events", "incident_timeline_events")
    op.execute(
        """
        ALTER TABLE incident_timeline_events
        RENAME CONSTRAINT incident_events_incident_id_fkey
        TO fk_incident_timeline_events_incident_id
        """
    )
    op.alter_column(
        "incident_timeline_events",
        "metadata",
        new_column_name="metadata_json",
        existing_type=postgresql.JSON(),
        existing_nullable=True,
    )
    op.execute(
        """
        ALTER TABLE incident_timeline_events
        ALTER COLUMN metadata_json TYPE jsonb
        USING metadata_json::jsonb
        """
    )
    op.execute(
        """
        ALTER TABLE incident_timeline_events
        ALTER COLUMN event_type TYPE varchar(100)
        USING event_type::varchar(100)
        """
    )

    op.add_column(
        "incident_timeline_events",
        sa.Column(
            "source",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "incident_timeline_events",
        sa.Column("from_status", incident_status_sprint7_enum, nullable=True),
    )
    op.add_column(
        "incident_timeline_events",
        sa.Column("to_status", incident_status_sprint7_enum, nullable=True),
    )
    op.add_column(
        "incident_timeline_events",
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "incident_timeline_events",
        sa.Column("alert_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "incident_timeline_events",
        sa.Column(
            "deployment_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "incident_timeline_events",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # 3. Backfill historical incident and timeline data.
    #
    # Legacy datetimes were written as naive UTC values. AT TIME ZONE UTC
    # preserves the intended instant while converting them to timestamptz.
    # ------------------------------------------------------------------
    op.execute(
        """
        WITH numbered AS (
            SELECT
                id,
                row_number() OVER (ORDER BY created_at, id) AS sequence_number
            FROM incidents
        )
        UPDATE incidents AS incident
        SET incident_number =
            'INC-' || lpad(numbered.sequence_number::text, 3, '0')
        FROM numbered
        WHERE incident.id = numbered.id
        """
    )

    op.execute(
        """
        UPDATE incidents
        SET
            primary_service_id = service_id,
            deduplication_key = correlation_id,
            failure_started_at = started_at AT TIME ZONE 'UTC',
            detected_at = created_at AT TIME ZONE 'UTC'
        """
    )

    op.execute(
        """
        UPDATE incidents
        SET acknowledged_at = updated_at AT TIME ZONE 'UTC'
        WHERE status::text = 'ACKNOWLEDGED'
        """
    )

    op.execute(
        """
        UPDATE incidents
        SET resolution_summary =
            COALESCE(
                resolution_summary,
                'Migrated from legacy FALSE_POSITIVE status'
            )
        WHERE status::text = 'FALSE_POSITIVE'
        """
    )

    # Only establish an alert association when the legacy value exactly
    # matches a real reliability_alerts.id. Values such as evt_<uuid> are
    # event IDs and intentionally remain only in triggered_by_event_id.
    op.execute(
        """
        UPDATE incidents AS incident
        SET triggering_alert_id = alert.id
        FROM reliability_alerts AS alert
        WHERE incident.triggered_by_event_id = alert.id
        """
    )

    # Protect the upcoming service foreign key from any historical orphan.
    op.execute(
        """
        UPDATE incidents AS incident
        SET primary_service_id = NULL
        WHERE primary_service_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM services AS service
              WHERE service.id = incident.primary_service_id
          )
        """
    )

    op.execute(
        """
        UPDATE incident_timeline_events
        SET
            source = 'SYSTEM',
            occurred_at = created_at AT TIME ZONE 'UTC'
        """
    )

    # ------------------------------------------------------------------
    # 4. Convert status and severity to the Sprint 7 enums.
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE incidents ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE incidents ALTER COLUMN severity DROP DEFAULT")

    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN status TYPE incidentstatus_sprint7
        USING (
            CASE status::text
                WHEN 'OPEN' THEN 'DETECTED'
                WHEN 'ACKNOWLEDGED' THEN 'ACKNOWLEDGED'
                WHEN 'RESOLVED' THEN 'RESOLVED'
                WHEN 'FALSE_POSITIVE' THEN 'RESOLVED'
                ELSE 'DETECTED'
            END
        )::incidentstatus_sprint7
        """
    )
    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN severity TYPE incidentseverity_sprint7
        USING (
            CASE severity::text
                WHEN 'CRITICAL' THEN 'SEV-1'
                WHEN 'HIGH' THEN 'SEV-2'
                WHEN 'MEDIUM' THEN 'SEV-3'
                WHEN 'LOW' THEN 'SEV-3'
                ELSE 'SEV-3'
            END
        )::incidentseverity_sprint7
        """
    )

    # No columns reference the old enums now, so replace their type names.
    op.execute("DROP TYPE incidentstatus")
    op.execute("DROP TYPE incidentseverity")
    op.execute("ALTER TYPE incidentstatus_sprint7 RENAME TO incidentstatus")
    op.execute("ALTER TYPE incidentseverity_sprint7 RENAME TO incidentseverity")

    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN status SET DEFAULT 'DETECTED'::incidentstatus
        """
    )
    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN severity SET DEFAULT 'SEV-3'::incidentseverity
        """
    )

    # Align existing timestamps with the timezone-aware Sprint 7 model.
    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN resolved_at TYPE timestamptz
        USING resolved_at AT TIME ZONE 'UTC'
        """
    )
    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN created_at TYPE timestamptz
        USING created_at AT TIME ZONE 'UTC'
        """
    )
    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN updated_at TYPE timestamptz
        USING updated_at AT TIME ZONE 'UTC'
        """
    )
    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN created_at SET DEFAULT now(),
        ALTER COLUMN updated_at SET DEFAULT now()
        """
    )

    op.execute(
        """
        ALTER TABLE incident_timeline_events
        ALTER COLUMN created_at TYPE timestamptz
        USING created_at AT TIME ZONE 'UTC'
        """
    )
    op.execute(
        """
        ALTER TABLE incident_timeline_events
        ALTER COLUMN created_at SET DEFAULT now()
        """
    )

    # ------------------------------------------------------------------
    # 5. Add foreign keys after all historical values are safe.
    # ------------------------------------------------------------------
    op.create_foreign_key(
        "fk_incidents_primary_service_id_services",
        "incidents",
        "services",
        ["primary_service_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_incidents_triggering_alert_id_reliability_alerts",
        "incidents",
        "reliability_alerts",
        ["triggering_alert_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_incidents_suspected_deployment_id_deployments",
        "incidents",
        "deployments",
        ["suspected_deployment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_incidents_current_assignee_id_users",
        "incidents",
        "users",
        ["current_assignee_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_incidents_created_by_users",
        "incidents",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_foreign_key(
        "fk_incident_timeline_events_actor_user_id_users",
        "incident_timeline_events",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_incident_timeline_events_alert_id_reliability_alerts",
        "incident_timeline_events",
        "reliability_alerts",
        ["alert_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_incident_timeline_events_deployment_id_deployments",
        "incident_timeline_events",
        "deployments",
        ["deployment_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ------------------------------------------------------------------
    # 6. Apply required defaults, uniqueness and non-null constraints.
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        DECLARE
            maximum_number bigint;
        BEGIN
            SELECT COALESCE(
                MAX(substring(incident_number FROM 5)::bigint),
                0
            )
            INTO maximum_number
            FROM incidents;

            IF maximum_number = 0 THEN
                PERFORM setval('incident_number_seq', 1, false);
            ELSE
                PERFORM setval('incident_number_seq', maximum_number, true);
            END IF;
        END;
        $$
        """
    )

    op.alter_column(
        "incidents",
        "incident_number",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default=sa.text("next_incident_number()"),
    )
    op.alter_column(
        "incidents",
        "detected_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    op.create_unique_constraint(
        "uq_incidents_incident_number",
        "incidents",
        ["incident_number"],
    )

    op.alter_column(
        "incident_timeline_events",
        "source",
        existing_type=sa.String(length=100),
        nullable=False,
        server_default=sa.text("'SYSTEM'"),
    )
    op.alter_column(
        "incident_timeline_events",
        "occurred_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )

    # ------------------------------------------------------------------
    # 7. Create the Sprint 7 child tables.
    # ------------------------------------------------------------------
    op.create_table(
        "incident_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("assigned_to_user_id", sa.String(length=36), nullable=True),
        sa.Column("assigned_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("assignment_note", sa.Text(), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_incident_assignments_incident_id_incidents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_user_id"],
            ["users.id"],
            name="fk_incident_assignments_assigned_to_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"],
            ["users.id"],
            name="fk_incident_assignments_assigned_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_incident_assignments"),
    )

    op.create_table(
        "incident_comments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("author_user_id", sa.String(length=36), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_incident_comments_incident_id_incidents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name="fk_incident_comments_author_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_incident_comments"),
    )

    op.create_table(
        "incident_metrics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("metric_type", sa.String(length=100), nullable=False),
        sa.Column("metric_name", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column(
            "source",
            sa.String(length=100),
            nullable=False,
            server_default=sa.text("'UNKNOWN'"),
        ),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_incident_metrics_incident_id_incidents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_incident_metrics"),
    )

    op.create_table(
        "incident_alert_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "reliability_alert_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "is_triggering_alert",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_incident_alert_links_incident_id_incidents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reliability_alert_id"],
            ["reliability_alerts.id"],
            name=(
                "fk_incident_alert_links_reliability_alert_id_"
                "reliability_alerts"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_incident_alert_links"),
        sa.UniqueConstraint(
            "incident_id",
            "reliability_alert_id",
            name="uq_incident_alert_link",
        ),
    )

    # ------------------------------------------------------------------
    # 8. Populate genuine triggering-alert links only.
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO incident_alert_links (
            id,
            incident_id,
            reliability_alert_id,
            linked_at,
            is_triggering_alert
        )
        SELECT
            md5(incident.id::text || ':' || incident.triggering_alert_id)::uuid,
            incident.id,
            incident.triggering_alert_id,
            incident.detected_at,
            true
        FROM incidents AS incident
        WHERE incident.triggering_alert_id IS NOT NULL
        ON CONFLICT (incident_id, reliability_alert_id) DO NOTHING
        """
    )

    # ------------------------------------------------------------------
    # 9. Create the final index set.
    # ------------------------------------------------------------------
    op.create_index(
        "ix_incidents_status",
        "incidents",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_incidents_severity",
        "incidents",
        ["severity"],
        unique=False,
    )
    op.create_index(
        "ix_incidents_primary_service_id",
        "incidents",
        ["primary_service_id"],
        unique=False,
    )
    op.create_index(
        "ix_incidents_environment",
        "incidents",
        ["environment"],
        unique=False,
    )
    op.create_index(
        "ix_incidents_detected_at",
        "incidents",
        ["detected_at"],
        unique=False,
    )
    op.create_index(
        "ix_incidents_current_assignee_id",
        "incidents",
        ["current_assignee_id"],
        unique=False,
    )
    op.create_index(
        "ix_incidents_deduplication_key",
        "incidents",
        ["deduplication_key"],
        unique=False,
    )

    op.create_index(
        "ix_incident_timeline_incident_occurred_id",
        "incident_timeline_events",
        ["incident_id", "occurred_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_incident_timeline_event_type",
        "incident_timeline_events",
        ["event_type"],
        unique=False,
    )

    op.create_index(
        "ix_incident_assignments_incident_id",
        "incident_assignments",
        ["incident_id"],
        unique=False,
    )
    op.create_index(
        "ix_incident_comments_incident_id",
        "incident_comments",
        ["incident_id"],
        unique=False,
    )
    op.create_index(
        "ix_incident_metrics_incident_id",
        "incident_metrics",
        ["incident_id"],
        unique=False,
    )
    op.create_index(
        "ix_incident_alert_links_incident_id",
        "incident_alert_links",
        ["incident_id"],
        unique=False,
    )
    op.create_index(
        "ix_incident_alert_links_reliability_alert_id",
        "incident_alert_links",
        ["reliability_alert_id"],
        unique=False,
    )

    # Temporary compatibility surface for the active Sprint 5 raw-SQL
    # router. This simple view remains automatically insertable/updatable.
    op.execute(
        """
        CREATE VIEW incident_events AS
        SELECT
            id,
            incident_id,
            event_type,
            message,
            metadata_json AS metadata,
            created_at
        FROM incident_timeline_events
        """
    )


def downgrade() -> None:
    """Return to the legacy incident schema, with lossy lifecycle mapping."""

    op.execute("DROP VIEW IF EXISTS incident_events")

    # Drop Sprint 7 indexes first.
    op.drop_index(
        "ix_incident_alert_links_reliability_alert_id",
        table_name="incident_alert_links",
    )
    op.drop_index(
        "ix_incident_alert_links_incident_id",
        table_name="incident_alert_links",
    )
    op.drop_index(
        "ix_incident_metrics_incident_id",
        table_name="incident_metrics",
    )
    op.drop_index(
        "ix_incident_comments_incident_id",
        table_name="incident_comments",
    )
    op.drop_index(
        "ix_incident_assignments_incident_id",
        table_name="incident_assignments",
    )

    op.drop_index(
        "ix_incident_timeline_event_type",
        table_name="incident_timeline_events",
    )
    op.drop_index(
        "ix_incident_timeline_incident_occurred_id",
        table_name="incident_timeline_events",
    )

    op.drop_index(
        "ix_incidents_deduplication_key",
        table_name="incidents",
    )
    op.drop_index(
        "ix_incidents_current_assignee_id",
        table_name="incidents",
    )
    op.drop_index("ix_incidents_detected_at", table_name="incidents")
    op.drop_index(
        "ix_incidents_primary_service_id",
        table_name="incidents",
    )
    op.drop_index("ix_incidents_environment", table_name="incidents")
    op.drop_index("ix_incidents_severity", table_name="incidents")
    op.drop_index("ix_incidents_status", table_name="incidents")

    # New child data has no representation in Sprint 5.
    op.drop_table("incident_alert_links")
    op.drop_table("incident_metrics")
    op.drop_table("incident_comments")
    op.drop_table("incident_assignments")

    # Remove new timeline foreign keys and columns.
    op.drop_constraint(
        "fk_incident_timeline_events_deployment_id_deployments",
        "incident_timeline_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_incident_timeline_events_alert_id_reliability_alerts",
        "incident_timeline_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_incident_timeline_events_actor_user_id_users",
        "incident_timeline_events",
        type_="foreignkey",
    )

    # Remove new incident constraints before changing enum types.
    op.drop_constraint(
        "fk_incidents_created_by_users",
        "incidents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_incidents_current_assignee_id_users",
        "incidents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_incidents_suspected_deployment_id_deployments",
        "incidents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_incidents_triggering_alert_id_reliability_alerts",
        "incidents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_incidents_primary_service_id_services",
        "incidents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_incidents_incident_number",
        "incidents",
        type_="unique",
    )

    # Recreate legacy enums under temporary names.
    op.execute(
        """
        CREATE TYPE incidentstatus_legacy AS ENUM (
            'OPEN',
            'ACKNOWLEDGED',
            'RESOLVED',
            'FALSE_POSITIVE'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE incidentseverity_legacy AS ENUM (
            'LOW',
            'MEDIUM',
            'HIGH',
            'CRITICAL'
        )
        """
    )

    op.execute("ALTER TABLE incidents ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE incidents ALTER COLUMN severity DROP DEFAULT")

    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN status TYPE incidentstatus_legacy
        USING (
            CASE status::text
                WHEN 'ACKNOWLEDGED' THEN 'ACKNOWLEDGED'
                WHEN 'RESOLVED' THEN 'RESOLVED'
                ELSE 'OPEN'
            END
        )::incidentstatus_legacy
        """
    )
    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN severity TYPE incidentseverity_legacy
        USING (
            CASE severity::text
                WHEN 'SEV-1' THEN 'CRITICAL'
                WHEN 'SEV-2' THEN 'HIGH'
                WHEN 'SEV-3' THEN 'MEDIUM'
                ELSE 'MEDIUM'
            END
        )::incidentseverity_legacy
        """
    )

    # Timeline enum columns still reference incidentstatus, so remove them
    # before replacing the enum type.
    op.drop_column("incident_timeline_events", "to_status")
    op.drop_column("incident_timeline_events", "from_status")

    op.execute("DROP TYPE incidentstatus")
    op.execute("DROP TYPE incidentseverity")
    op.execute("ALTER TYPE incidentstatus_legacy RENAME TO incidentstatus")
    op.execute("ALTER TYPE incidentseverity_legacy RENAME TO incidentseverity")

    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN status SET DEFAULT 'OPEN'::incidentstatus
        """
    )

    # Convert timezone-aware timestamps back to naive UTC values.
    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN resolved_at TYPE timestamp
        USING resolved_at AT TIME ZONE 'UTC'
        """
    )
    op.execute(
        """
        ALTER TABLE incidents
        ALTER COLUMN created_at DROP DEFAULT,
        ALTER COLUMN created_at TYPE timestamp
            USING created_at AT TIME ZONE 'UTC',
        ALTER COLUMN updated_at DROP DEFAULT,
        ALTER COLUMN updated_at TYPE timestamp
            USING updated_at AT TIME ZONE 'UTC'
        """
    )

    op.execute(
        """
        ALTER TABLE incident_timeline_events
        ALTER COLUMN created_at DROP DEFAULT,
        ALTER COLUMN created_at TYPE timestamp
            USING created_at AT TIME ZONE 'UTC'
        """
    )

    op.drop_column("incident_timeline_events", "occurred_at")
    op.drop_column("incident_timeline_events", "deployment_id")
    op.drop_column("incident_timeline_events", "alert_id")
    op.drop_column("incident_timeline_events", "actor_user_id")
    op.drop_column("incident_timeline_events", "source")

    op.execute(
        """
        ALTER TABLE incident_timeline_events
        ALTER COLUMN metadata_json TYPE json
        USING metadata_json::json
        """
    )
    op.alter_column(
        "incident_timeline_events",
        "metadata_json",
        new_column_name="metadata",
        existing_type=postgresql.JSON(),
        existing_nullable=True,
    )
    op.execute(
        """
        ALTER TABLE incident_timeline_events
        ALTER COLUMN event_type TYPE varchar
        USING event_type::varchar
        """
    )

    op.execute(
        """
        ALTER TABLE incident_timeline_events
        RENAME CONSTRAINT fk_incident_timeline_events_incident_id
        TO incident_events_incident_id_fkey
        """
    )
    op.rename_table("incident_timeline_events", "incident_events")

    # Drop Sprint 7 incident columns.
    op.drop_column("incidents", "created_by")
    op.drop_column("incidents", "remediation_summary")
    op.drop_column("incidents", "rca_summary")
    op.drop_column("incidents", "resolution_summary")
    op.drop_column("incidents", "current_assignee_id")
    op.drop_column("incidents", "remediation_started_at")
    op.drop_column("incidents", "investigation_started_at")
    op.drop_column("incidents", "acknowledged_at")
    op.drop_column("incidents", "detected_at")
    op.drop_column("incidents", "failure_started_at")
    op.drop_column("incidents", "deduplication_key")
    op.drop_column("incidents", "suspected_deployment_id")
    op.drop_column("incidents", "triggering_alert_id")
    op.drop_column("incidents", "primary_service_id")
    op.drop_column("incidents", "incident_number")

    op.execute("DROP FUNCTION next_incident_number()")
    op.execute("DROP SEQUENCE incident_number_seq")

    # Restore the Sprint 5 index set.
    op.create_index(
        "ix_incidents_service_id",
        "incidents",
        ["service_id"],
        unique=False,
    )
    op.create_index(
        "ix_incidents_environment",
        "incidents",
        ["environment"],
        unique=False,
    )
    op.create_index(
        "ix_incidents_status",
        "incidents",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_incidents_severity",
        "incidents",
        ["severity"],
        unique=False,
    )
    op.create_index(
        "ix_incidents_correlation_id",
        "incidents",
        ["correlation_id"],
        unique=False,
    )
    op.create_index(
        "ix_incidents_triggered_by_event_id",
        "incidents",
        ["triggered_by_event_id"],
        unique=False,
    )
    op.create_index(
        "ix_incident_events_incident_id",
        "incident_events",
        ["incident_id"],
        unique=False,
    )
    op.create_index(
        "ix_incident_events_event_type",
        "incident_events",
        ["event_type"],
        unique=False,
    )
