import importlib.util
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "c9a8e7d6f5b4_add_sprint_10a_chaos_data_models.py"
)
SPEC = importlib.util.spec_from_file_location(
    "sprint_10a_chaos_migration",
    MIGRATION_PATH,
)
assert SPEC is not None and SPEC.loader is not None
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


class RecordingOperations:
    def __init__(self):
        self.created_tables = []
        self.created_indexes = []
        self.dropped_tables = []
        self.dropped_indexes = []

    def get_bind(self):
        return object()

    def create_table(self, name, *args, **kwargs):
        self.created_tables.append(name)

    def create_index(self, name, *args, **kwargs):
        self.created_indexes.append(name)

    def drop_table(self, name, *args, **kwargs):
        self.dropped_tables.append(name)

    def drop_index(self, name, *args, **kwargs):
        self.dropped_indexes.append(name)


def test_chaos_foundation_migration_has_expected_parent():
    assert migration.down_revision == "86b465be9924"


def test_upgrade_and_downgrade_cover_all_chaos_tables(monkeypatch):
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)
    monkeypatch.setattr(
        migration.postgresql.ENUM,
        "create",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        migration.postgresql.ENUM,
        "drop",
        lambda *args, **kwargs: None,
    )

    migration.upgrade()
    migration.downgrade()

    expected_tables = [
        "chaos_experiments",
        "chaos_runs",
        "chaos_observations",
        "experiment_benchmarks",
    ]
    assert operations.created_tables == expected_tables
    assert operations.dropped_tables == list(reversed(expected_tables))
    assert "ix_chaos_runs_experiment_started" in operations.created_indexes
    assert (
        "ix_experiment_benchmarks_status_calculated"
        in operations.created_indexes
    )
