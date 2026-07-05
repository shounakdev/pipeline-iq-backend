def classify_health(
    latency_ms: float | None,
    error_rate: float | None,
    pod_restart_count: int | None,
    available_replicas: int | None,
    replica_count: int | None,
) -> str:
    if available_replicas is not None and replica_count is not None:
        if available_replicas == 0:
            return "UNHEALTHY"
        if available_replicas < replica_count:
            return "DEGRADED"

    if error_rate is not None and error_rate > 10:
        return "UNHEALTHY"

    if error_rate is not None and error_rate > 5:
        return "DEGRADED"

    if latency_ms is not None and latency_ms > 2000:
        return "UNHEALTHY"

    if latency_ms is not None and latency_ms > 1000:
        return "DEGRADED"

    if pod_restart_count is not None and pod_restart_count > 3:
        return "DEGRADED"

    return "HEALTHY"