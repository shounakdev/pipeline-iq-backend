from uuid import uuid4

from app.models import RCAFeedback, RCAReport


def submit_rca_feedback(
    db,
    report_id,
    user_id,
    rating: str,
    comment: str | None = None,
):
    report = db.query(RCAReport).filter(RCAReport.id == report_id).first()

    if not report:
        raise ValueError("RCA report not found")

    reviewer_id = str(user_id) if user_id is not None else None

    existing = (
        db.query(RCAFeedback)
        .filter(
            RCAFeedback.report_id == report_id,
            RCAFeedback.reviewer_id == reviewer_id,
        )
        .first()
    )

    if existing:
        existing.rating = rating
        existing.comment = comment
        db.commit()
        db.refresh(existing)
        return existing

    feedback = RCAFeedback(
        id=uuid4(),
        incident_id=report.incident_id,
        report_id=report.id,
        reviewer_id=reviewer_id,
        rating=rating,
        comment=comment,
    )

    db.add(feedback)
    db.commit()
    db.refresh(feedback)

    return feedback