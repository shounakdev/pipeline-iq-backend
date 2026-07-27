from datetime import datetime


def calculate_minutes_between(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end:
        return None

    delta = end - start
    return int(delta.total_seconds() // 60)


def build_deployment_temporal_correlation_fact(
    deployment: dict,
    incident: dict,
) -> dict | None:
    minutes = deployment.get("minutes_before_failure")

    if minutes is None:
        deployed_at = deployment.get("deployed_at")
        failure_started_at = incident.get("failure_started_at")

        if not deployed_at or not failure_started_at:
            return None

        minutes = calculate_minutes_between(deployed_at, failure_started_at)

    if minutes is None or minutes < 0:
        return None

    return {
        "fact_type": "DEPLOYMENT_TEMPORAL_CORRELATION",
        "description": f"Deployment completed {minutes} minutes before failure began.",
        "evidence_paths": [
            "deployment.deployed_at",
            "incident.failure_started_at",
        ],
    }


def build_slo_breach_fact(slo: dict) -> dict | None:
    if slo.get("status") != "COLLECTED":
        return None

    breach_status = slo.get("breach_status")

    if breach_status and breach_status != "BREACHED":
        return None

    return {
        "fact_type": "SLO_BREACH",
        "description": "A reliability alert indicates the measured value breached the configured threshold.",
        "evidence_paths": [
            "slo.measured_value",
            "slo.target",
            "slo.alert_severity",
        ],
    }


def build_derived_facts(
    incident: dict,
    deployment: dict | None,
    slo: dict | None,
) -> list[dict]:
    facts: list[dict] = []

    if deployment and deployment.get("status") == "COLLECTED":
        deployment_fact = build_deployment_temporal_correlation_fact(
            deployment,
            incident,
        )
        if deployment_fact:
            facts.append(deployment_fact)

    if slo and slo.get("status") == "COLLECTED":
        slo_fact = build_slo_breach_fact(slo)
        if slo_fact:
            facts.append(slo_fact)

    return facts