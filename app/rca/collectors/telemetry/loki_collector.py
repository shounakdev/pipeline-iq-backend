# app/rca/collectors/telemetry/loki_collector.py

from collections import Counter, defaultdict

from app.rca.collectors.telemetry.utils import (
    build_incident_window,
    normalize_error_signature,
    redact_log_line,
)


def classify_error(line: str) -> str:
    lowered = line.lower()

    if "database" in lowered and "timeout" in lowered:
        return "database_timeout_errors"
    if "connection refused" in lowered:
        return "connection_refused_errors"
    if "out of memory" in lowered or "oom" in lowered:
        return "out_of_memory_errors"
    if "uncaught" in lowered or "exception" in lowered:
        return "uncaught_exception_errors"

    return "other_error_logs"


def collect_loki_evidence(db, incident: dict) -> dict:
    window = build_incident_window(incident)

    if window["status"] == "NO_DATA":
        return {
            "status": "NO_DATA",
            "reason": window["reason"],
        }

    # Replace with real Loki query result later.
    logs = []

    counts = Counter()
    signatures = Counter()
    samples_by_signature = defaultdict(list)

    first_error_timestamp = None
    error_count_before = 0
    error_count_after = 0

    for item in logs:
        timestamp = item.get("timestamp")
        line = item.get("line", "")

        category = classify_error(line)
        counts[category] += 1

        signature = normalize_error_signature(line)
        signatures[signature] += 1

        if len(samples_by_signature[signature]) < 3:
            samples_by_signature[signature].append(redact_log_line(line))

        if first_error_timestamp is None or timestamp < first_error_timestamp:
            first_error_timestamp = timestamp

        if timestamp and timestamp < window["anchor"]:
            error_count_before += 1
        else:
            error_count_after += 1

    top_signatures = []
    for signature, count in signatures.most_common(5):
        top_signatures.append({
            "signature": signature,
            "count": count,
            "redacted_samples": samples_by_signature[signature],
        })

    return {
        "status": "COLLECTED",
        "query_window": window,
        "total_error_logs": sum(counts.values()),
        "database_timeout_errors": counts["database_timeout_errors"],
        "connection_refused_errors": counts["connection_refused_errors"],
        "out_of_memory_errors": counts["out_of_memory_errors"],
        "uncaught_exception_errors": counts["uncaught_exception_errors"],
        "top_error_signatures": top_signatures,
        "first_error_timestamp": first_error_timestamp,
        "error_count_before": error_count_before,
        "error_count_after": error_count_after,
    }