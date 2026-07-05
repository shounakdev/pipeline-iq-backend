from dataclasses import dataclass
from typing import Any


@dataclass
class Alert:
    event_type: str
    severity: str
    payload: dict[str, Any]


def _status_value(snapshot) -> str | None:
    status = getattr(snapshot, "status", None)
    return getattr(status, "value", status)


def evaluate_alerts(snapshot) -> list[Alert]:
    alerts: list[Alert] = []

    if snapshot.error_rate is not None and snapshot.error_rate > 5:
        alerts.append(
            Alert(
                event_type="HIGH_ERROR_RATE",
                severity="HIGH" if snapshot.error_rate > 10 else "MEDIUM",
                payload={
                    "error_rate": snapshot.error_rate,
                    "threshold_percent": 5,
                },
            )
        )

    if snapshot.latency_ms is not None and snapshot.latency_ms > 1000:
        alerts.append(
            Alert(
                event_type="HIGH_LATENCY",
                severity="HIGH" if snapshot.latency_ms > 2000 else "MEDIUM",
                payload={
                    "latency_ms": snapshot.latency_ms,
                    "threshold_ms": 1000,
                },
            )
        )

    if snapshot.pod_restart_count is not None and snapshot.pod_restart_count > 3:
        alerts.append(
            Alert(
                event_type="POD_RESTART_SPIKE",
                severity="HIGH",
                payload={
                    "pod_restart_count": snapshot.pod_restart_count,
                    "threshold": 3,
                },
            )
        )

    if (
        snapshot.available_replicas is not None
        and snapshot.replica_count is not None
        and snapshot.available_replicas < snapshot.replica_count
    ):
        alerts.append(
            Alert(
                event_type="SERVICE_DEGRADED",
                severity="HIGH" if snapshot.available_replicas == 0 else "MEDIUM",
                payload={
                    "available_replicas": snapshot.available_replicas,
                    "replica_count": snapshot.replica_count,
                },
            )
        )

    if _status_value(snapshot) == "UNHEALTHY":
        alerts.append(
            Alert(
                event_type="SERVICE_DOWN",
                severity="CRITICAL",
                payload={
                    "status": "UNHEALTHY",
                },
            )
        )

    return alerts
