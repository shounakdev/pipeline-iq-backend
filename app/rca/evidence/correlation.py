def build_fact(
    fact_type: str,
    description: str,
    evidence_paths: list[str],
    polarity: str = "SUPPORTING",
) -> dict:
    return {
        "fact_type": fact_type,
        "description": description,
        "evidence_paths": evidence_paths,
        "polarity": polarity,
    }


def number_or_zero(value):
    return value if value is not None else 0


def build_correlation_facts(evidence: dict) -> list[dict]:
    facts = []

    deployment = evidence.get("deployment", {})
    metrics = evidence.get("metrics", {})
    logs = evidence.get("logs", {})
    traces = evidence.get("traces", {})
    kubernetes = evidence.get("kubernetes", {})
    slo = evidence.get("slo", {})
    pipeline = evidence.get("pipeline", {})

    minutes_before_failure = deployment.get("minutes_before_failure")
    if minutes_before_failure is not None and minutes_before_failure <= 15:
        facts.append(
            build_fact(
                "DEPLOYMENT_SHORTLY_BEFORE_FAILURE",
                "Deployment occurred shortly before the failure window.",
                ["deployment.deployed_at", "deployment.minutes_before_failure"],
            )
        )

    error_rate_before = number_or_zero(metrics.get("error_rate_before"))
    error_rate_after = number_or_zero(metrics.get("error_rate_after"))

    if error_rate_after > error_rate_before:
        facts.append(
            build_fact(
                "ERROR_RATE_INCREASED_AFTER_DEPLOYMENT",
                "Error rate increased after the deployment.",
                ["metrics.error_rate_before", "metrics.error_rate_after"],
            )
        )

    p95_latency_before_ms = number_or_zero(metrics.get("p95_latency_before_ms"))
    p95_latency_after_ms = number_or_zero(metrics.get("p95_latency_after_ms"))

    if p95_latency_after_ms > p95_latency_before_ms:
        facts.append(
            build_fact(
                "LATENCY_INCREASED_AFTER_DEPLOYMENT",
                "P95 latency increased after the deployment.",
                ["metrics.p95_latency_before_ms", "metrics.p95_latency_after_ms"],
            )
        )

    database_timeout_errors = number_or_zero(logs.get("database_timeout_errors"))

    if database_timeout_errors > 0:
        facts.append(
            build_fact(
                "DATABASE_TIMEOUT_LOGS_PRESENT",
                "Database timeout errors were found in logs.",
                ["logs.database_timeout_errors", "logs.top_error_signatures"],
            )
        )

    if traces.get("failed_traces_point_to") == "postgresql":
        facts.append(
            build_fact(
                "FAILED_TRACES_POINT_TO_POSTGRESQL",
                "Failed traces point to PostgreSQL.",
                ["traces.failed_traces_point_to"],
            )
        )

    cpu_before = metrics.get("cpu_before")
    cpu_after = metrics.get("cpu_after")

    if cpu_after is not None and cpu_before is not None:
        if cpu_after <= cpu_before * 1.2:
            facts.append(
                build_fact(
                    "CPU_REMAINED_NORMAL",
                    "CPU did not materially increase during the incident window.",
                    ["metrics.cpu_before", "metrics.cpu_after"],
                    polarity="CONTRADICTORY",
                )
            )

    pod_restart_count = number_or_zero(kubernetes.get("pod_restart_count"))
    failed_readiness_probe_count = number_or_zero(
        kubernetes.get("failed_readiness_probe_count")
    )

    if pod_restart_count == 0 and failed_readiness_probe_count == 0:
        facts.append(
            build_fact(
                "NO_POD_HEALTH_DEGRADATION",
                "No pod restarts or readiness failures occurred.",
                [
                    "kubernetes.pod_restart_count",
                    "kubernetes.failed_readiness_probe_count",
                ],
                polarity="CONTRADICTORY",
            )
        )

    if slo.get("status") == "COLLECTED" and slo.get("availability_breached") is True:
        facts.append(
            build_fact(
                "AVAILABILITY_SLO_BREACHED",
                "Availability SLO was breached during the incident.",
                ["slo.availability_breached", "slo.error_budget_status"],
            )
        )

    if pipeline.get("quality_gate") == "PASSED" and error_rate_after > error_rate_before:
        facts.append(
            build_fact(
                "QUALITY_GATE_PASSED_DESPITE_RUNTIME_REGRESSION",
                "Pipeline quality gate passed, but runtime error rate increased later.",
                [
                    "pipeline.quality_gate",
                    "metrics.error_rate_before",
                    "metrics.error_rate_after",
                ],
                polarity="CONTRADICTORY",
            )
        )

    return facts