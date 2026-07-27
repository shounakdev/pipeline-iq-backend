from app.models import IncidentEvidence, RCAFeedback, RCAReport


def get_rca_evaluation_summary(db):
    total_reports = db.query(RCAReport).count()

    reports_generated = (
        db.query(RCAReport)
        .filter(RCAReport.status == "COMPLETED")
        .count()
    )

    reports_failed = (
        db.query(RCAReport)
        .filter(RCAReport.status == "FAILED")
        .count()
    )

    correct_count = (
        db.query(RCAFeedback)
        .filter(RCAFeedback.rating == "CORRECT")
        .count()
    )

    partial_count = (
        db.query(RCAFeedback)
        .filter(RCAFeedback.rating == "PARTIALLY_CORRECT")
        .count()
    )

    incorrect_count = (
        db.query(RCAFeedback)
        .filter(RCAFeedback.rating == "INCORRECT")
        .count()
    )

    feedback_count = db.query(RCAFeedback).count()

    evidence_records = db.query(IncidentEvidence).all()

    scores = [
        evidence.evidence_payload.get("completeness_score")
        for evidence in evidence_records
        if evidence.evidence_payload
        and evidence.evidence_payload.get("completeness_score") is not None
    ]

    avg_completeness_score = sum(scores) / len(scores) if scores else 0

    return {
        "reports_total": total_reports,
        "reports_generated": reports_generated,
        "reports_failed": reports_failed,
        "correct_rating_count": correct_count,
        "partially_correct_rating_count": partial_count,
        "incorrect_rating_count": incorrect_count,
        "feedback_count": feedback_count,
        "feedback_rate": feedback_count / reports_generated if reports_generated else 0,
        "average_generation_duration_ms": 0,
        "average_completeness_score": avg_completeness_score,
    }