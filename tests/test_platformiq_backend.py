from tests.conftest import register_user, login_user, auth_headers
from app.models import Role

import uuid

def test_register_user(client):
    email = f"admin-{uuid.uuid4()}@example.com"

    response = register_user(
        client,
        email,
        "admin123",
        "admin",
    )

    assert response.status_code in [200, 201], response.text

    data = response.json()
    user_data = data.get("user", data)

    assert user_data["email"] == email
    assert user_data["role"] == "admin"


def test_login_user(client):
    register_user(client, "admin@example.com", "admin123", "admin")

    response = client.post(
        "/auth/login",
        json={
            "email": "admin@example.com",
            "password": "admin123",
        },
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "admin@example.com"
    assert data["user"]["role"] == "admin"


def test_get_me_with_jwt(client):
    register_user(client, "developer@example.com", "developer123", "developer")
    token = login_user(client, "developer@example.com", "developer123")

    response = client.get(
        "/auth/me",
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["email"] == "developer@example.com"
    assert data["role"] == "developer"


def test_roles_seeded(db):
    roles = db.query(Role).all()
    role_names = sorted([role.name for role in roles])

    assert role_names == ["admin", "developer", "viewer"]


def test_admin_can_trigger_pipeline(client):
    register_user(client, "admin@example.com", "admin123", "admin")
    token = login_user(client, "admin@example.com", "admin123")

    response = client.post(
        "/pipeline/trigger",
        headers=auth_headers(token),
        json={
            "repo_url": "https://github.com/shounakdev/meetup",
            "branch": "main",
        },
    )

    assert response.status_code in [200, 201, 202], response.text


def test_developer_can_trigger_pipeline(client):
    register_user(client, "developer@example.com", "developer123", "developer")
    token = login_user(client, "developer@example.com", "developer123")

    response = client.post(
        "/pipeline/trigger",
        headers=auth_headers(token),
        json={
            "repo_url": "https://github.com/shounakdev/meetup",
            "branch": "main",
        },
    )

    assert response.status_code in [200, 201, 202], response.text


def test_viewer_cannot_trigger_pipeline(client):
    register_user(client, "viewer@example.com", "viewer123", "viewer")
    token = login_user(client, "viewer@example.com", "viewer123")

    response = client.post(
        "/pipeline/trigger",
        headers=auth_headers(token),
        json={
            "repo_url": "https://github.com/shounakdev/meetup",
            "branch": "main",
        },
    )

    assert response.status_code == 403, response.text

    data = response.json()
    assert data["detail"] == "Insufficient permissions"


def test_create_project(client):
    register_user(client, "admin@example.com", "admin123", "admin")
    token = login_user(client, "admin@example.com", "admin123")

    response = client.post(
        "/projects",
        headers=auth_headers(token),
        json={
            "name": "PlatformIQ Test Project",
            "description": "Test project created from automated test",
        },
    )

    assert response.status_code in [200, 201], response.text

    data = response.json()

    assert data["name"] == "PlatformIQ Test Project"
    assert data["description"] == "Test project created from automated test"


def test_create_service(client):
    register_user(client, "admin@example.com", "admin123", "admin")
    token = login_user(client, "admin@example.com", "admin123")

    project_response = client.post(
        "/projects",
        headers=auth_headers(token),
        json={
            "name": "PlatformIQ Test Project",
            "description": "Test project",
        },
    )

    assert project_response.status_code in [200, 201], project_response.text

    project_id = project_response.json()["id"]

    service_payload = {
        "project_id": project_id,
        "name": "Backend API",
        "description": "FastAPI backend service",
        "service_type": "backend",
        "owner": "platform-team",
    }

    response = client.post(
        "/services",
        headers=auth_headers(token),
        json=service_payload,
    )

    if response.status_code in [404, 422]:
        nested_payload = {
            "name": "Backend API",
            "description": "FastAPI backend service",
            "service_type": "backend",
            "owner": "platform-team",
        }

        response = client.post(
            f"/projects/{project_id}/services",
            headers=auth_headers(token),
            json=nested_payload,
        )

    assert response.status_code in [200, 201], response.text

    data = response.json()

    assert data["name"] == "Backend API"
    assert data["service_type"] == "backend"
