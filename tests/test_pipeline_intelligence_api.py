import uuid

from app.models import Pipeline


def auth_headers(client):
    email = f"admin-{uuid.uuid4()}@example.com"
    password = "password123"

    client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "role": "admin",
        },
    )

    response = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 200, response.text
    token = response.json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


def create_pipeline(db, **overrides):
    defaults = {
        "id": str(uuid.uuid4()),
        "repo_url": "https://github.com/shounakdev/meetup",
        "branch": "cicd_test",
        "status": "SUCCESS",
        "stage": "COMPLETED",
        "progress": 100,
        "build_status": "SUCCESS",
        "test_status": "SUCCESS",
        "sonar_status": "SUCCESS",
        "trivy_status": "SUCCESS",
        "coverage": 85,
        "bugs": 0,
        "vulnerabilities": 0,
        "code_smells": 5,
        "quality_gate": "OK",
        "trivy_critical": 0,
        "trivy_high": 0,
        "trivy_medium": 1,
        "trivy_low": 2,
        "trivy_total": 3,
        "risk_score": 12.5,
        "risk_level": "LOW",
        "risk_summary": "Low release risk.",
        "ai_summary": "Pipeline completed successfully.",
        "recommendations": ["Keep dependencies updated."],
    }

    defaults.update(overrides)

    pipeline = Pipeline(**defaults)
    db.add(pipeline)
    db.commit()
    db.refresh(pipeline)

    return pipeline


def test_pipeline_detail_returns_intelligence_fields(client, db):
    headers = auth_headers(client)

    pipeline = create_pipeline(
        db,
        sonar_status="SUCCESS",
        trivy_status="SUCCESS",
        risk_score=18.0,
        risk_level="LOW",
    )

    response = client.get(f"/pipeline/{pipeline.id}", headers=headers)

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["id"] == pipeline.id
    assert data["status"] == "SUCCESS"
    assert data["stage"] == "COMPLETED"

    assert data["build_status"] == "SUCCESS"
    assert data["test_status"] == "SUCCESS"

    assert data["sonar_status"] == "SUCCESS"
    assert "coverage" in data
    assert "bugs" in data
    assert "vulnerabilities" in data
    assert "code_smells" in data
    assert "quality_gate" in data

    assert data["trivy_status"] == "SUCCESS"
    assert "trivy_critical" in data
    assert "trivy_high" in data
    assert "trivy_medium" in data
    assert "trivy_total" in data

    assert data["risk_score"] == 18.0
    assert data["risk_level"] == "LOW"
    assert data["risk_summary"]


def test_pipeline_filters_work(client, db):
    headers = auth_headers(client)

    low_pipeline = create_pipeline(
        db,
        repo_url="https://github.com/shounakdev/meetup",
        branch="cicd_test",
        status="SUCCESS",
        risk_level="LOW",
    )

    create_pipeline(
        db,
        repo_url="https://github.com/example/bad-repo",
        branch="main",
        status="FAILED",
        risk_level="CRITICAL",
    )

    response = client.get(
        "/pipelines?status=SUCCESS&risk_level=LOW&branch=cicd_test&repo_url=meetup",
        headers=headers,
    )

    assert response.status_code == 200, response.text

    data = response.json()
    ids = [item["id"] for item in data]

    assert low_pipeline.id in ids

    for item in data:
        assert item["status"] == "SUCCESS"
        assert item["risk_level"] == "LOW"
        assert "cicd_test" in item["branch"]
        assert "meetup" in item["repo_url"]
