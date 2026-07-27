# app/rca/collectors/telemetry/prometheus_collector.py

from app.rca.collectors.telemetry.utils import (
    build_incident_window,
    safe_subtract,
    safe_multiplier,
)


def collect_prometheus_evidence(db, incident: dict) -> dict:
    window = build_incident_window(incident)

    if window["status"] == "NO_DATA":
        return {
            "status": "NO_DATA",
            "reason": window["reason"],
            "missing_series": ["prometheus_window"],
        }

    service = incident.get("primary_service") or incident.get("affected_service")

    # Replace these with your real Prometheus client calls later.
    before = {}
    after = {}

    missing_series = [
        name for name in [
            "request_rate",
            "http_500_rate",
            "error_rate",
            "p95_latency_ms",
            "cpu",
            "memory",
            "available_replicas",
        ]
        if before.get(name) is None or after.get(name) is None
    ]

    return {
        "status": "COLLECTED" if not missing_series else "PARTIAL",
        "service": service,
        "query_window": window,
        "queries": {
            "request_rate": "http_request_rate",
            "http_500_rate": "http_500_rate",
            "error_rate": "service_error_rate",
            "p95_latency_ms": "service_p95_latency_ms",
            "cpu": "container_cpu_usage",
            "memory": "container_memory_usage",
            "available_replicas": "kube_deployment_available_replicas",
        },
        "request_rate_before": before.get("request_rate"),
        "request_rate_after": after.get("request_rate"),
        "http_500_rate_before": before.get("http_500_rate"),
        "http_500_rate_after": after.get("http_500_rate"),
        "http_500_rate_change": safe_subtract(after.get("http_500_rate"), before.get("http_500_rate")),
        "error_rate_before": before.get("error_rate"),
        "error_rate_after": after.get("error_rate"),
        "error_rate_change": safe_subtract(after.get("error_rate"), before.get("error_rate")),
        "p95_latency_before_ms": before.get("p95_latency_ms"),
        "p95_latency_after_ms": after.get("p95_latency_ms"),
        "p95_latency_change_ms": safe_subtract(after.get("p95_latency_ms"), before.get("p95_latency_ms")),
        "p95_latency_multiplier": safe_multiplier(after.get("p95_latency_ms"), before.get("p95_latency_ms")),
        "cpu_before": before.get("cpu"),
        "cpu_after": after.get("cpu"),
        "memory_before": before.get("memory"),
        "memory_after": after.get("memory"),
        "available_replicas_before": before.get("available_replicas"),
        "available_replicas_after": after.get("available_replicas"),
        "missing_series": missing_series,
    }