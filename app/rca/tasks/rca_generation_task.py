from datetime import datetime, timezone

from fastapi.encoders import jsonable_encoder

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import IncidentEvidence, RCAReport
from app.rca.collectors.evidence_collector import collect_native_evidence
from app.rca.llm.gateway import generate_rca_from_evidence


EVIDENCE_SOURCES = (
    "deployment",
    "pipeline",
    "slo",
    "metrics",
    "logs",
    "traces",
    "kubernetes",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_dict(value):
    if isinstance(value, dict):
        return value

    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")

    if hasattr(value, "dict"):
        return value.dict()

    return value


def _normalise_evidence_status(value: str | None) -> str:
    status = str(value or "").upper()

    if status in {"COMPLETE", "COMPLETED"}:
        return "COMPLETED"

    if status == "FAILED":
        return "FAILED"

    return "PARTIAL"


def _build_source_statuses(evidence_bundle: dict) -> dict:
    statuses = {}

    for source in EVIDENCE_SOURCES:
        source_payload = evidence_bundle.get(source)

        if isinstance(source_payload, dict):
            statuses[source] = source_payload.get(
                "status",
                "NO_DATA",
            )
        else:
            statuses[source] = "NO_DATA"

    return statuses


def _normalise_report_payload(report_payload: dict) -> dict:
    payload = dict(report_payload)

    if "supporting_evidence" not in payload:
        payload["supporting_evidence"] = payload.get(
            "supporting_observations",
            [],
        )

    if "contradictory_evidence" not in payload:
        payload["contradictory_evidence"] = payload.get(
            "contradicting_observations",
            [],
        )

    return payload


def build_fallback_rca_report(
    evidence_bundle: dict,
    error: Exception,
) -> dict:
    missing_sources = evidence_bundle.get(
        "missing_sources",
        [],
    )

    return {
        "probable_root_cause": (
            "RCA generation could not produce a strict LLM report because "
            "the collected evidence bundle did not match the expected RCA schema."
        ),
        "root_cause_category": "INSUFFICIENT_STRUCTURED_EVIDENCE",
        "confidence": "LOW",
        "confidence_explanation": (
            "Confidence is low because evidence was collected, but the bundle "
            "failed strict validation before LLM report generation."
        ),
        "supporting_evidence": [
            {
                "summary": (
                    "Evidence collection completed but schema validation failed."
                ),
                "evidence_path": "evidence_bundle",
            }
        ],
        "contradictory_evidence": [],
        "recommended_actions": [
            (
                "Recommended investigation: align evidence collector output "
                "with IncidentEvidenceBundle schema."
            ),
            (
                "Suggested validation step: ensure time-window, source metadata, "
                "and derived-fact fields are present."
            ),
        ],
        "alternative_hypotheses": [],
        "missing_evidence": missing_sources,
        "failure_reason": str(error),
    }


@celery_app.task(name="app.rca.tasks.generate_rca")
def generate_rca_task(
    incident_id: str,
    evidence_id: str,
    report_id: str,
    prompt_version: str = "rca_v1",
    model: str = "gpt-4.1-mini",
):
    db = SessionLocal()

    try:
        evidence = (
            db.query(IncidentEvidence)
            .filter(IncidentEvidence.id == evidence_id)
            .first()
        )

        report = (
            db.query(RCAReport)
            .filter(RCAReport.id == report_id)
            .first()
        )

        if not evidence or not report:
            return

        evidence.status = "COLLECTING"
        db.commit()

        collected_evidence = collect_native_evidence(
            db,
            incident_id,
        )

        evidence_bundle = jsonable_encoder(
            collected_evidence,
        )

        evidence.evidence_payload = evidence_bundle
        evidence.source_statuses = _build_source_statuses(
            evidence_bundle,
        )
        evidence.collection_errors = evidence_bundle.get(
            "collector_errors",
            [],
        )
        evidence.status = _normalise_evidence_status(
            evidence_bundle.get("status"),
        )

        db.commit()
        db.refresh(evidence)

        report.status = "GENERATING"
        db.commit()

        try:
            llm_response = generate_rca_from_evidence(
                evidence_bundle=evidence_bundle,
                prompt_version=prompt_version,
                model=model,
            )

            raw_report_payload = _as_dict(
                llm_response,
            )

            report_payload = _normalise_report_payload(
                jsonable_encoder(raw_report_payload),
            )
        except Exception as validation_error:
            report_payload = build_fallback_rca_report(
                evidence_bundle=evidence_bundle,
                error=validation_error,
            )

        report.report_json = report_payload
        report.probable_root_cause = report_payload.get(
            "probable_root_cause",
        )
        report.summary = report_payload.get(
            "confidence_explanation",
        )
        report.confidence = report_payload.get(
            "confidence",
        )
        report.supporting_evidence = report_payload.get(
            "supporting_evidence",
            [],
        )
        report.contradictory_evidence = report_payload.get(
            "contradictory_evidence",
            [],
        )
        report.alternative_hypotheses = report_payload.get(
            "alternative_hypotheses",
            [],
        )
        report.missing_evidence = report_payload.get(
            "missing_evidence",
            [],
        )
        report.model_provider = report_payload.get(
            "model",
        )
        report.model_name = model
        report.prompt_version = report_payload.get(
            "prompt_version",
            prompt_version,
        )
        report.generated_at = utcnow()
        report.status = "COMPLETED"

        db.commit()

    except Exception as exc:
        db.rollback()

        report = (
            db.query(RCAReport)
            .filter(RCAReport.id == report_id)
            .first()
        )

        evidence = (
            db.query(IncidentEvidence)
            .filter(IncidentEvidence.id == evidence_id)
            .first()
        )

        if report:
            report.status = "FAILED"
            report.summary = str(exc)
            report.generated_at = utcnow()

        if evidence:
            evidence.status = "FAILED"

            existing_errors = list(
                evidence.collection_errors or [],
            )
            existing_errors.append(
                {
                    "source": "rca_generation_task",
                    "error": str(exc),
                    "occurred_at": utcnow().isoformat(),
                }
            )
            evidence.collection_errors = existing_errors

        db.commit()
        raise

    finally:
        db.close()