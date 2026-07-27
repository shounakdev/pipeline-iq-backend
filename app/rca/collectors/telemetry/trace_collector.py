# app/rca/collectors/telemetry/trace_collector.py

from collections import Counter

from app.rca.collectors.telemetry.utils import build_incident_window, safe_subtract


def collect_trace_evidence(db, incident: dict) -> dict:
    window = build_incident_window(incident)

    if window["status"] == "NO_DATA":
        return {
            "status": "NO_DATA",
            "reason": window["reason"],
        }

    # Replace with real tracing backend results later.
    traces = []

    failed = [t for t in traces if t.get("status") == "ERROR"]
    slow = [t for t in traces if t.get("duration_ms", 0) >= 1000]

    failed_dependencies = Counter(
        t.get("failed_dependency")
        for t in failed
        if t.get("failed_dependency")
    )

    failed_spans = Counter(
        t.get("failed_span")
        for t in failed
        if t.get("failed_span")
    )

    before_durations = [
        t["duration_ms"] for t in traces
        if t.get("started_at") and t["started_at"] < window["anchor"]
    ]

    after_durations = [
        t["duration_ms"] for t in traces
        if t.get("started_at") and t["started_at"] >= window["anchor"]
    ]

    def p95(values):
        if not values:
            return None
        values = sorted(values)
        index = int(len(values) * 0.95) - 1
        return values[max(index, 0)]

    before_p95 = p95(before_durations)
    after_p95 = p95(after_durations)

    return {
        "status": "COLLECTED",
        "query_window": window,
        "total_traces": len(traces),
        "failed_trace_count": len(failed),
        "failed_trace_percentage": (len(failed) / len(traces) * 100) if traces else 0,
        "slow_trace_count": len(slow),
        "top_failed_span": failed_spans.most_common(1)[0][0] if failed_spans else None,
        "top_failed_dependency": failed_dependencies.most_common(1)[0][0] if failed_dependencies else None,
        "dependency_error_counts": dict(failed_dependencies),
        "p95_trace_duration_before": before_p95,
        "p95_trace_duration_after": after_p95,
        "p95_trace_duration_change": safe_subtract(after_p95, before_p95),
        "representative_trace_ids": [str(t.get("trace_id")) for t in failed[:5] if t.get("trace_id")],
    }