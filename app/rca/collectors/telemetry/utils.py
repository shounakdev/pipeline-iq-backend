# app/rca/collectors/telemetry/utils.py

import re
from datetime import timedelta


def safe_subtract(after, before):
    if after is None or before is None:
        return None
    return after - before


def safe_multiplier(after, before):
    if after is None or before in (None, 0):
        return None
    return after / before


def build_incident_window(incident: dict, before_minutes: int = 15, after_minutes: int = 15):
    anchor = incident.get("failure_started_at") or incident.get("detected_at")

    if not anchor:
        return {
            "status": "NO_DATA",
            "reason": "No failure_started_at or detected_at available",
        }

    return {
        "status": "COLLECTED",
        "anchor": anchor,
        "before_start": anchor - timedelta(minutes=before_minutes),
        "before_end": anchor,
        "after_start": anchor,
        "after_end": anchor + timedelta(minutes=after_minutes),
    }


def redact_log_line(line: str) -> str:
    if not line:
        return line

    redacted = line
    redacted = re.sub(r"\b[0-9a-fA-F-]{32,36}\b", "<id>", redacted)
    redacted = re.sub(r"request[_-]?id=[^\s]+", "request_id=<id>", redacted, flags=re.I)
    redacted = re.sub(r"trace[_-]?id=[^\s]+", "trace_id=<id>", redacted, flags=re.I)
    redacted = re.sub(r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?", "<timestamp>", redacted)
    redacted = re.sub(r"\b\d+\b", "<num>", redacted)
    return redacted[:500]


def normalize_error_signature(line: str) -> str:
    return redact_log_line(line).lower().strip()