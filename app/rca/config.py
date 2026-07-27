import os


def _bool_from_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()

    if normalized in {"1", "true", "yes", "on"}:
        return True

    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ValueError(
        f"{name} must be one of: true, false, 1, 0, yes, no, on, off"
    )


RCA_ENABLED = _bool_from_env("RCA_ENABLED", False)
RCA_LLM_ENABLED = _bool_from_env("RCA_LLM_ENABLED", False)
RCA_LOG_COLLECTION_ENABLED = _bool_from_env(
    "RCA_LOG_COLLECTION_ENABLED",
    False,
)
RCA_TRACE_COLLECTION_ENABLED = _bool_from_env(
    "RCA_TRACE_COLLECTION_ENABLED",
    False,
)
RCA_KUBERNETES_EVENTS_ENABLED = _bool_from_env(
    "RCA_KUBERNETES_EVENTS_ENABLED",
    False,
)

RCA_PROVIDER = os.getenv("RCA_PROVIDER", "disabled")
RCA_MODEL = os.getenv("RCA_MODEL", "")

RCA_EVIDENCE_WINDOW_BEFORE_MINUTES = int(
    os.getenv("RCA_EVIDENCE_WINDOW_BEFORE_MINUTES", "15")
)
RCA_EVIDENCE_WINDOW_AFTER_MINUTES = int(
    os.getenv("RCA_EVIDENCE_WINDOW_AFTER_MINUTES", "30")
)
