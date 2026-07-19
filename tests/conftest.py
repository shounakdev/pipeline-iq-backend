import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# These values must be configured before importing anything from app.
os.environ.setdefault("TESTING", "1")

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    (
        "postgresql://postgres:postgres"
        "@postgres:5432/platformiq_test_db"
    ),
)

os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)

from app.database import (
    Base,
    get_db as database_get_db,
)

# Some authentication routes use a separate dependency module.
# Override it as well so registration and login use the test database.
try:
    from app.auth.dependencies import (
        get_db as auth_get_db,
    )
except ImportError:
    # If authentication imports app.database.get_db directly,
    # both dependency objects are the same.
    auth_get_db = database_get_db

from app.main import app
from app.models import Role


test_engine = create_engine(
    TEST_DATABASE_URL,
    pool_pre_ping=True,
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
)


def create_incident_number_database_objects() -> None:
    """
    Create the PostgreSQL sequence and function required by
    Incident.incident_number.

    Production creates these objects through Alembic. Tests use
    Base.metadata.create_all(), so they must be created explicitly
    before SQLAlchemy creates the incidents table.
    """
    with test_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE SEQUENCE IF NOT EXISTS incident_number_seq
                START WITH 1
                INCREMENT BY 1
                """
            )
        )

        connection.execute(
            text(
                """
                ALTER SEQUENCE incident_number_seq
                RESTART WITH 1
                """
            )
        )

        connection.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION next_incident_number()
                RETURNS VARCHAR
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RETURN
                        'INC-'
                        || LPAD(
                            nextval(
                                'incident_number_seq'
                            )::TEXT,
                            3,
                            '0'
                        );
                END;
                $$
                """
            )
        )


def drop_incident_number_database_objects() -> None:
    """
    Remove the PostgreSQL objects created for the test session.
    """
    with test_engine.begin() as connection:
        connection.execute(
            text(
                """
                DROP FUNCTION IF EXISTS next_incident_number()
                """
            )
        )

        connection.execute(
            text(
                """
                DROP SEQUENCE IF EXISTS incident_number_seq
                """
            )
        )


def override_get_db():
    """
    Return a new test database session for each API request.
    """
    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.rollback()
        db.close()


def seed_roles(db):
    """
    Insert the roles required by authentication tests.
    """
    required_roles = [
        "admin",
        "developer",
        "operator",
        "viewer",
    ]

    for role_name in required_roles:
        existing_role = (
            db.query(Role)
            .filter(Role.name == role_name)
            .first()
        )

        if existing_role is None:
            db.add(
                Role(
                    id=str(uuid4()),
                    name=role_name,
                )
            )

    db.commit()


@pytest.fixture(scope="session")
def database_schema():
    """
    Create database tables only when a database-related fixture
    is requested.

    Pure SLO and error-budget unit tests do not use PostgreSQL.
    """
    create_incident_number_database_objects()

    try:
        Base.metadata.create_all(bind=test_engine)
        yield
    finally:
        Base.metadata.drop_all(bind=test_engine)
        drop_incident_number_database_objects()


@pytest.fixture
def clean_database(database_schema):
    """
    Delete existing test data and seed required reference data
    before each database-backed test.

    This fixture is intentionally not autouse so pure unit tests
    do not connect to PostgreSQL.
    """
    db = TestingSessionLocal()

    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())

        # Keep generated incident numbers deterministic across tests.
        db.execute(
            text(
                """
                ALTER SEQUENCE incident_number_seq
                RESTART WITH 1
                """
            )
        )

        db.commit()

        seed_roles(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    yield


@pytest.fixture
def db_session(clean_database):
    """
    Provide a database session to tests that explicitly request
    db_session.
    """
    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def db(clean_database):
    """
    Backward-compatible database fixture used by existing tests.
    """
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(clean_database):
    """
    Provide a TestClient configured to use the test database.

    Both the standard application database dependency and the
    authentication database dependency are overridden.
    """
    dependencies_to_override = {
        database_get_db,
        auth_get_db,
    }

    for dependency in dependencies_to_override:
        app.dependency_overrides[dependency] = (
            override_get_db
        )

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        for dependency in dependencies_to_override:
            app.dependency_overrides.pop(
                dependency,
                None,
            )


def register_user(
    client,
    email,
    password,
    role,
):
    return client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "role": role,
        },
    )


def login_user(
    client,
    email,
    password,
):
    response = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 200, response.text

    return response.json()["access_token"]


def auth_headers(token):
    return {
        "Authorization": f"Bearer {token}",
    }