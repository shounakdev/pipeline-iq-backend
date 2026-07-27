from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Iterable
from concurrent.futures import ThreadPoolExecutor, wait

from uuid import UUID
from app.models import EvidenceCollectionStatus, Incident, IncidentEvidence, Service

from sqlalchemy.orm import Session

from app.rca.collectors.base import (
    CollectorResult,
    CollectorStatus,
    EvidenceCollectionContext,
    EvidenceCollector,
)
from app.rca.collectors.redaction import redact_evidence
from app.rca.collectors.limits import enforce_payload_limits


DEFAULT_BEFORE_MINUTES = 15
DEFAULT_AFTER_MINUTES = 15
DEFAULT_COLLECTOR_TIMEOUT_SECONDS = 10


def calculate_evidence_window(
    *,
    failure_started_at: datetime | None,
    detected_at: datetime,
    current_time: datetime,
    before_minutes: int = DEFAULT_BEFORE_MINUTES,
    after_minutes: int = DEFAULT_AFTER_MINUTES,
) -> dict[str, datetime]:
    anchor = failure_started_at or detected_at

    before_start = anchor - timedelta(minutes=before_minutes)
    before_end = anchor - timedelta(minutes=1)

    after_start = anchor
    after_end = min(current_time, anchor + timedelta(minutes=after_minutes))

    return {
        "before_window_start": before_start,
        "before_window_end": before_end,
        "after_window_start": after_start,
        "after_window_end": after_end,
    }

def collect_and_store_incident_evidence(
    *,
    db: Session,
    incident_id: UUID,
    collectors: Iterable[EvidenceCollector],
    before_minutes: int = DEFAULT_BEFORE_MINUTES,
    after_minutes: int = DEFAULT_AFTER_MINUTES,
    timeout_seconds: int = DEFAULT_COLLECTOR_TIMEOUT_SECONDS,
) -> IncidentEvidence:
    incident = db.query(Incident).filter(Incident.id == incident_id).first()

    if incident is None:
        raise ValueError(f"Incident not found: {incident_id}")

    current_time = datetime.now(timezone.utc)

    window = calculate_evidence_window(
        failure_started_at=incident.failure_started_at,
        detected_at=incident.detected_at,
        current_time=current_time,
        before_minutes=before_minutes,
        after_minutes=after_minutes,
    )

    service = None
    if incident.primary_service_id:
        service = (
            db.query(Service)
            .filter(Service.id == incident.primary_service_id)
            .first()
        )

    related_alert_ids = []
    if getattr(incident, "triggering_alert_id", None):
        related_alert_ids.append(incident.triggering_alert_id)

    context = EvidenceCollectionContext(
        incident_id=incident.id,
        incident_number=incident.incident_number,
        service_id=incident.primary_service_id,
        service_name=service.name if service else None,
        environment=incident.environment,
        failure_started_at=incident.failure_started_at,
        detected_at=incident.detected_at,
        current_time=current_time,
        before_window_start=window["before_window_start"],
        before_window_end=window["before_window_end"],
        after_window_start=window["after_window_start"],
        after_window_end=window["after_window_end"],
        suspected_deployment_id=incident.suspected_deployment_id,
        related_alert_ids=related_alert_ids,
    )

    results = [
        run_collector(
            collector=collector,
            context=context,
            timeout_seconds=timeout_seconds,
        )
        for collector in collectors
    ]

    bundle = build_evidence_bundle(context=context, results=results)

    source_statuses = {
        result.source_name: result.status.value
        for result in results
    }

    collection_errors = [
        {
            "source_name": result.source_name,
            "error": result.error,
        }
        for result in results
        if result.error
    ]

    latest_version = (
        db.query(IncidentEvidence.version)
        .filter(IncidentEvidence.incident_id == incident.id)
        .order_by(IncidentEvidence.version.desc())
        .first()
    )

    next_version = 1
    if latest_version:
        next_version = latest_version[0] + 1

    evidence = IncidentEvidence(
        incident_id=incident.id,
        version=next_version,
        status=EvidenceCollectionStatus.COMPLETED,
        schema_version="1.0",
        window_start=context.before_window_start,
        window_end=context.after_window_end,
        anchor_time=context.failure_started_at or context.detected_at,
        evidence_payload=bundle,
        source_statuses=source_statuses,
        collection_errors=collection_errors,
    )

    db.add(evidence)
    db.commit()
    db.refresh(evidence)

    return evidence

def normalize_failed_result(source_name: str, error: Exception, duration_ms: int) -> CollectorResult:
    return CollectorResult(
        source_name=source_name,
        status=CollectorStatus.FAILED,
        data=None,
        metadata={},
        error=str(error),
        duration_ms=duration_ms,
    )

def collect_and_store_incident_evidence(
    *,
    db: Session,
    incident_id: UUID,
    collectors: Iterable[EvidenceCollector],
    before_minutes: int = DEFAULT_BEFORE_MINUTES,
    after_minutes: int = DEFAULT_AFTER_MINUTES,
    timeout_seconds: int = DEFAULT_COLLECTOR_TIMEOUT_SECONDS,
) -> IncidentEvidence:
    incident = db.query(Incident).filter(Incident.id == incident_id).first()

    if incident is None:
        raise ValueError(f"Incident not found: {incident_id}")

    current_time = datetime.now(timezone.utc)

    window = calculate_evidence_window(
        failure_started_at=incident.failure_started_at,
        detected_at=incident.detected_at,
        current_time=current_time,
        before_minutes=before_minutes,
        after_minutes=after_minutes,
    )

    service_name = None

    if getattr(incident, "primary_service_id", None):
        service = db.query(Service).filter(Service.id == incident.primary_service_id).first()
        if service:
            service_name = getattr(service, "name", None)

    context = EvidenceCollectionContext(
        incident_id=incident.id,
        incident_number=getattr(incident, "incident_number", None),
        service_id=getattr(incident, "primary_service_id", None),
        service_name=service_name,
        environment=getattr(incident, "environment", None),
        failure_started_at=getattr(incident, "failure_started_at", None),
        detected_at=incident.detected_at,
        current_time=current_time,
        before_window_start=window["before_window_start"],
        before_window_end=window["before_window_end"],
        after_window_start=window["after_window_start"],
        after_window_end=window["after_window_end"],
        suspected_deployment_id=getattr(incident, "suspected_deployment_id", None),
        related_alert_ids=[],
    )

    results = [
        run_collector(
            collector=collector,
            context=context,
            timeout_seconds=timeout_seconds,
        )
        for collector in collectors
    ]

    bundle = build_evidence_bundle(context=context, results=results)

    evidence = IncidentEvidence(
        incident_id=incident.id,
        version=1,
        status="COMPLETED",
        schema_version="rca_evidence.v1",
        window_start=context.before_window_start,
        window_end=context.after_window_end,
        anchor_time=context.failure_started_at or context.detected_at,
        evidence_json=bundle,
        completeness_score=bundle["completeness"]["score"],
    )

    db.add(evidence)
    db.commit()
    db.refresh(evidence)

    return evidence

def run_collector(
    collector: EvidenceCollector,
    context: EvidenceCollectionContext,
    timeout_seconds: int = DEFAULT_COLLECTOR_TIMEOUT_SECONDS,
) -> CollectorResult:
    started = time.perf_counter()
    executor = ThreadPoolExecutor(max_workers=1)

    try:
        future = executor.submit(collector.collect, context)
        done, _ = wait([future], timeout=timeout_seconds)

        duration_ms = int((time.perf_counter() - started) * 1000)

        if not done:
            future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

            return CollectorResult(
                source_name=collector.source_name,
                status=CollectorStatus.FAILED,
                data=None,
                metadata={"timeout_seconds": timeout_seconds},
                error=f"{collector.source_name} collector timed out",
                duration_ms=duration_ms,
            )

        result = future.result()
        result.duration_ms = duration_ms
        return result

    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)

        return normalize_failed_result(
            source_name=collector.source_name,
            error=exc,
            duration_ms=duration_ms,
        )

    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        
def calculate_completeness(results: list[CollectorResult]) -> dict[str, object]:
    total = len(results)

    completed = sum(1 for result in results if result.status == CollectorStatus.COMPLETED)
    partial = sum(1 for result in results if result.status == CollectorStatus.PARTIAL)
    failed = sum(1 for result in results if result.status == CollectorStatus.FAILED)

    score = 0.0
    if total:
        score = round(((completed + partial * 0.5) / total) * 100, 2)

    return {
        "total_sources": total,
        "completed_sources": completed,
        "partial_sources": partial,
        "failed_sources": failed,
        "score": score,
    }


def build_evidence_bundle(
    *,
    context: EvidenceCollectionContext,
    results: list[CollectorResult],
) -> dict:
    raw_bundle = {
        "incident_id": str(context.incident_id),
        "incident_number": context.incident_number,
        "affected_service": context.service_name,
        "service_id": str(context.service_id) if context.service_id else None,
        "environment": context.environment,
        "window": {
            "before": {
                "start": context.before_window_start.isoformat(),
                "end": context.before_window_end.isoformat(),
            },
            "after": {
                "start": context.after_window_start.isoformat(),
                "end": context.after_window_end.isoformat(),
            },
        },
        "sources": [
            {
                "source_name": result.source_name,
                "status": result.status.value,
                "data": result.data,
                "metadata": result.metadata,
                "error": result.error,
                "duration_ms": result.duration_ms,
            }
            for result in results
        ],
        "derived_facts": {
            "suspected_deployment_id": str(context.suspected_deployment_id)
            if context.suspected_deployment_id
            else None,
            "related_alert_ids": [str(alert_id) for alert_id in context.related_alert_ids],
        },
        "completeness": calculate_completeness(results),
    }

    redacted = redact_evidence(raw_bundle)
    return enforce_payload_limits(redacted)


def collect_evidence_bundle(
    *,
    context: EvidenceCollectionContext,
    collectors: Iterable[EvidenceCollector],
) -> dict:
    results = []

    for collector in collectors:
        result = run_collector(collector, context)
        results.append(result)

    return build_evidence_bundle(context=context, results=results)