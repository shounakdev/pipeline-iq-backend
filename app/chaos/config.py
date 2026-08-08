"""Runtime configuration and allowlists for chaos execution."""

from __future__ import annotations

from dataclasses import dataclass
import os


def _csv(name: str, default: str = "") -> frozenset[str]:
    return frozenset(
        value.strip()
        for value in os.getenv(name, default).split(",")
        if value.strip()
    )


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))

    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc

    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")

    return value


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()

    if raw in {"1", "true", "yes", "on"}:
        return True

    if raw in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class ChaosSettings:
    enabled: bool
    allowed_environments: frozenset[str]
    allowed_namespaces: frozenset[str]
    allowed_services: frozenset[str]
    max_duration_seconds: int
    max_concurrent_runs: int
    watchdog_interval_seconds: int
    adapter_backend: str = "chaos-mesh"
    max_detection_seconds: int = 30
    max_alert_seconds: int = 60
    max_incident_seconds: int = 90
    max_diagnosis_seconds: int = 180
    max_recovery_seconds: int = 600

    @classmethod
    def from_env(cls) -> "ChaosSettings":
        settings = cls(
            enabled=_boolean("CHAOS_ENGINE_ENABLED", False),
            allowed_environments=_csv(
                "CHAOS_ALLOWED_ENVIRONMENTS"
            ),
            allowed_namespaces=_csv(
                "CHAOS_ALLOWED_NAMESPACES"
            ),
            allowed_services=_csv(
                "CHAOS_ALLOWED_SERVICES"
            ),
            max_duration_seconds=_positive_int(
                "CHAOS_MAX_DURATION_SECONDS",
                600,
            ),
            max_concurrent_runs=_positive_int(
                "CHAOS_MAX_CONCURRENT_RUNS",
                1,
            ),
            watchdog_interval_seconds=_positive_int(
                "CHAOS_WATCHDOG_INTERVAL_SECONDS",
                30,
            ),
            adapter_backend=os.getenv(
                "CHAOS_ADAPTER",
                "chaos-mesh",
            ).strip().lower(),
            max_detection_seconds=_positive_int(
                "CHAOS_MAX_DETECTION_SECONDS",
                30,
            ),
            max_alert_seconds=_positive_int(
                "CHAOS_MAX_ALERT_SECONDS",
                60,
            ),
            max_incident_seconds=_positive_int(
                "CHAOS_MAX_INCIDENT_SECONDS",
                90,
            ),
            max_diagnosis_seconds=_positive_int(
                "CHAOS_MAX_DIAGNOSIS_SECONDS",
                180,
            ),
            max_recovery_seconds=_positive_int(
                "CHAOS_MAX_RECOVERY_SECONDS",
                600,
            ),
        )

        if settings.adapter_backend not in {
            "chaos-mesh",
            "mock",
        }:
            raise ValueError(
                "CHAOS_ADAPTER must be 'chaos-mesh' or 'mock'"
            )

        if settings.max_concurrent_runs != 1:
            raise ValueError(
                "CHAOS_MAX_CONCURRENT_RUNS must remain 1 while the "
                "database global safety index is enabled"
            )

        return settings

    @property
    def environment_namespace_map(self) -> dict[str, str]:
        return {
            "development": "platformiq-dev",
            "staging": "platformiq-staging",
        }