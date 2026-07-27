# app/rca/collectors/telemetry/kubernetes_collector.py

from app.rca.collectors.telemetry.utils import build_incident_window, safe_subtract


def collect_kubernetes_evidence(db, incident: dict) -> dict:
    window = build_incident_window(incident)

    if window["status"] == "NO_DATA":
        return {
            "status": "NO_DATA",
            "reason": window["reason"],
        }

    # Replace with Kubernetes client / stored runtime snapshot later.
    before = {}
    after = {}
    events = []

    warning_events = [
        {
            "reason": event.get("reason"),
            "message": event.get("message"),
            "timestamp": event.get("timestamp"),
        }
        for event in events
        if event.get("type") == "Warning"
    ][:10]

    return {
        "status": "COLLECTED",
        "query_window": window,
        "desired_replicas": after.get("desired_replicas"),
        "available_replicas": after.get("available_replicas"),
        "unavailable_replicas": after.get("unavailable_replicas"),
        "pod_restart_count": after.get("pod_restart_count"),
        "restart_delta": safe_subtract(after.get("pod_restart_count"), before.get("pod_restart_count")),
        "oom_killed_count": after.get("oom_killed_count"),
        "crash_loop_count": after.get("crash_loop_count"),
        "failed_readiness_probe_count": after.get("failed_readiness_probe_count"),
        "failed_liveness_probe_count": after.get("failed_liveness_probe_count"),
        "pending_pod_count": after.get("pending_pod_count"),
        "recent_warning_events": warning_events,
        "cpu_status": after.get("cpu_status"),
        "memory_status": after.get("memory_status"),
    }