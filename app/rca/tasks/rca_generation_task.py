from datetime import datetime, timezone

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import IncidentEvidence, RCAReport
from app.rca.collectors.evidence_collector import collect_native_evidence
from app.rca.llm.gateway import generate_rca_from_evidence


def utcnow():
    return datetime.now(timezone.utc)


def _as_dict(value):
    if isinstance(value, dict):
        return value

    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")

    if hasattr(value, "dict"):
        return value.dict()

    return value


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
        "root_cause_category": (
            "INSUFFICIENT_STRUCTURED_EVIDENCE"
        ),
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
        "recommended_actions": [
            (
                "Recommended investigation: align evidence collector output "
                "with IncidentEvidenceBundle schema."
            ),
            (
                "Suggested validation step: ensure time_window, source metadata, "
                "and derived fact fields are present."
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
    started_at = utcnow()

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
        evidence.collection_started_at = utcnow()
        db.commit()

        evidence_bundle = collect_native_evidence(
            db,
            incident_id,
        )

        evidence.evidence_json = evidence_bundle
        evidence.completeness_score = evidence_bundle.get(
            "completeness_score"
        )
        evidence.status = evidence_bundle.get(
            "status",
            "PARTIAL",
        )
        evidence.collection_completed_at = utcnow()

        db.commit()
        db.refresh(evidence)

        report.status = "GENERATING"
        report.generation_started_at = utcnow()
        db.commit()

        try:
            llm_response = generate_rca_from_evidence(
                evidence_bundle=evidence_bundle,
                prompt_version=prompt_version,
                model=model,
            )
            report_payload = _as_dict(llm_response)
        except Exception as validation_error:
            report_payload = build_fallback_rca_report(
                evidence_bundle=evidence_bundle,
                error=validation_error,
            )

        report.report_json = report_payload
        report.status = "COMPLETED"

        if isinstance(report_payload, dict):
            report.confidence = report_payload.get(
                "confidence"
            )
        else:
            report.confidence = None

        report.generation_completed_at = utcnow()
        report.generation_duration_ms = int(
            (utcnow() - started_at).total_seconds()
            * 1000
        )

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
            report.error_message = str(exc)
            report.generation_completed_at = utcnow()

        if evidence:
            evidence.status = "FAILED"
            evidence.collection_completed_at = utcnow()

        db.commit()
        raise

    finally:
        db.close()