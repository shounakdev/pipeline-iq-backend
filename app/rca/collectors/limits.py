from __future__ import annotations

import json
from typing import Any


MAX_ERROR_SIGNATURES = 20
MAX_LOG_SAMPLES = 50
MAX_TRACE_EXAMPLES = 20
MAX_KUBERNETES_EVENTS = 50
MAX_CHARS_PER_SAMPLE = 2_000
MAX_TOTAL_EVIDENCE_CHARS = 120_000


def truncate_string(value: str, max_chars: int = MAX_CHARS_PER_SAMPLE) -> str:
    if len(value) <= max_chars:
        return value

    return value[:max_chars] + "...[TRUNCATED]"


def enforce_payload_limits(value: Any) -> Any:
    limited = _limit_recursive(value)

    serialized = json.dumps(limited, default=str)

    if len(serialized) <= MAX_TOTAL_EVIDENCE_CHARS:
        return limited

    return {
        "payload_truncated": True,
        "reason": "Evidence payload exceeded maximum allowed size.",
        "max_total_chars": MAX_TOTAL_EVIDENCE_CHARS,
    }


def _limit_recursive(value: Any) -> Any:
    if isinstance(value, dict):
        output = {}

        for key, item in value.items():
            normalized_key = str(key).lower()

            if normalized_key in {"logs", "log_samples"} and isinstance(item, list):
                output[key] = [_limit_recursive(x) for x in item[:MAX_LOG_SAMPLES]]
            elif normalized_key in {"traces", "trace_examples"} and isinstance(item, list):
                output[key] = [_limit_recursive(x) for x in item[:MAX_TRACE_EXAMPLES]]
            elif normalized_key in {"kubernetes_events", "events"} and isinstance(item, list):
                output[key] = [_limit_recursive(x) for x in item[:MAX_KUBERNETES_EVENTS]]
            elif normalized_key in {"error_signatures", "errors"} and isinstance(item, list):
                output[key] = [_limit_recursive(x) for x in item[:MAX_ERROR_SIGNATURES]]
            else:
                output[key] = _limit_recursive(item)

        return output

    if isinstance(value, list):
        return [_limit_recursive(item) for item in value]

    if isinstance(value, str):
        return truncate_string(value)

    return value