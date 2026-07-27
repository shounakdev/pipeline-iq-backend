from datetime import datetime, timezone
from uuid import uuid4
import time

from app.rca.collectors.base import (
    CollectorResult,
    CollectorStatus,
    EvidenceCollectionContext,
)
from app.rca.collectors.orchestrator import collect_evidence_bundle, run_collector


class GoodCollector:
    source_name = "deployment"

    def collect(self, context):
        return CollectorResult(
            source_name=self.source_name,
            status=CollectorStatus.COMPLETED,
            data={"version": "v1.8.2"},
        )


class FailingCollector:
    source_name = "loki"

    def collect(self, context):
        raise TimeoutError("Loki query timed out")


class SlowCollector:
    source_name = "loki"

    def collect(self, context):
        time.sleep(1)
        return CollectorResult(
            source_name=self.source_name,
            status=CollectorStatus.COMPLETED,
            data={"logs": []},
        )


def build_context():
    now = datetime.now(timezone.utc)

    return EvidenceCollectionContext(
        incident_id=uuid4(),
        incident_number="INC-001",
        service_id=uuid4(),
        service_name="payment-service",
        environment="staging",
        failure_started_at=now,
        detected_at=now,
        current_time=now,
        before_window_start=now,
        before_window_end=now,
        after_window_start=now,
        after_window_end=now,
    )


def test_collector_timeout_returns_failed_result():
    context = build_context()

    result = run_collector(
        collector=SlowCollector(),
        context=context,
        timeout_seconds=0,
    )

    assert result.source_name == "loki"
    assert result.status == CollectorStatus.FAILED
    assert result.data is None
    assert result.error is not None
    assert "timed out" in result.error
    assert result.duration_ms is not None


def test_one_collector_failure_does_not_fail_bundle():
    context = build_context()

    bundle = collect_evidence_bundle(
        context=context,
        collectors=[GoodCollector(), FailingCollector()],
    )

    sources = {source["source_name"]: source for source in bundle["sources"]}

    assert sources["deployment"]["status"] == "COMPLETED"
    assert sources["loki"]["status"] == "FAILED"
    assert sources["loki"]["data"] is None
    assert sources["loki"]["error"] == "Loki query timed out"
    assert sources["loki"]["duration_ms"] is not None
    assert bundle["completeness"]["failed_sources"] == 1