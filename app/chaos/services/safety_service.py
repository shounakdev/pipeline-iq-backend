"""Safety gates which must pass before a chaos run is queued."""

from app.chaos.config import ChaosSettings
from app.chaos.exceptions import (
    ChaosDisabledError,
    ChaosValidationError,
)
from app.chaos.schemas import ChaosRunCreateRequest


def validate_run_request(
    request: ChaosRunCreateRequest,
    settings: ChaosSettings,
) -> None:
    """Reject targets outside the server-owned chaos allowlist."""
    if not settings.enabled:
        raise ChaosDisabledError("Chaos execution is disabled")
    if request.environment == "production":
        raise ChaosValidationError("Production chaos is forbidden")
    if request.environment not in settings.allowed_environments:
        raise ChaosValidationError("Environment is not allowlisted")
    if request.namespace not in settings.allowed_namespaces:
        raise ChaosValidationError("Namespace is not allowlisted")
    expected_namespace = settings.environment_namespace_map.get(
        request.environment
    )
    if expected_namespace != request.namespace:
        raise ChaosValidationError(
            "Environment does not map to the requested namespace"
        )
    if request.service not in settings.allowed_services:
        raise ChaosValidationError("Service is not allowlisted")
    if request.duration_seconds > settings.max_duration_seconds:
        raise ChaosValidationError(
            "Duration exceeds CHAOS_MAX_DURATION_SECONDS"
        )
    if request.cleanup_behavior != "delete":
        raise ChaosValidationError("Cleanup behavior must be delete")