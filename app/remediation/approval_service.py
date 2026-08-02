from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import (
    ApprovalDecision,
    RecommendationStatus,
    RemediationApproval,
    RemediationRecommendation,
)
from app.remediation import repository
from app.remediation.events import (
    create_remediation_approved_event,
    create_remediation_rejected_event,
)


class RemediationApprovalError(Exception):
    pass


class RemediationNotFoundError(
    RemediationApprovalError,
):
    pass


class RemediationAlreadyDecidedError(
    RemediationApprovalError,
):
    pass


class RejectionReasonRequiredError(
    RemediationApprovalError,
):
    pass


@dataclass(frozen=True)
class RemediationDecisionResult:
    recommendation: RemediationRecommendation
    approval: RemediationApproval


def _record_decision(
    *,
    db: Session,
    remediation_id: UUID,
    decided_by: str,
    decision: ApprovalDecision,
    rejection_reason: str | None = None,
) -> RemediationDecisionResult:
    try:
        remediation = repository.get_remediation_by_id(
            db,
            remediation_id,
            for_update=True,
        )

        if remediation is None:
            raise RemediationNotFoundError(
                "Remediation recommendation was not found"
            )

        if (
            remediation.status
            != RecommendationStatus.PENDING_APPROVAL
        ):
            current_status = getattr(
                remediation.status,
                "value",
                remediation.status,
            )

            raise RemediationAlreadyDecidedError(
                "Remediation recommendation is no "
                "longer pending approval. Current "
                f"status: {current_status}"
            )

        if remediation.approval is not None:
            raise RemediationAlreadyDecidedError(
                "Remediation recommendation already "
                "has an approval decision"
            )

        cleaned_reason = (
            rejection_reason.strip()
            if rejection_reason is not None
            else None
        )

        if (
            decision == ApprovalDecision.REJECTED
            and not cleaned_reason
        ):
            raise RejectionReasonRequiredError(
                "A rejection reason is required"
            )

        if decision == ApprovalDecision.APPROVED:
            cleaned_reason = None

        approval = (
            repository.create_remediation_decision(
                db,
                remediation=remediation,
                approved_by=decided_by,
                decision=decision,
                rejection_reason=cleaned_reason,
            )
        )

        repository.create_remediation_decision_audit_event(
            db,
            remediation=remediation,
            approval=approval,
        )

        if decision == ApprovalDecision.APPROVED:
            create_remediation_approved_event(
                db=db,
                recommendation=remediation,
                approval=approval,
            )
        else:
            create_remediation_rejected_event(
                db=db,
                recommendation=remediation,
                approval=approval,
            )

        db.commit()
        db.refresh(remediation)
        db.refresh(approval)

        return RemediationDecisionResult(
            recommendation=remediation,
            approval=approval,
        )

    except RemediationApprovalError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def approve_remediation(
    *,
    db: Session,
    remediation_id: UUID,
    approved_by: str,
) -> RemediationDecisionResult:
    return _record_decision(
        db=db,
        remediation_id=remediation_id,
        decided_by=approved_by,
        decision=ApprovalDecision.APPROVED,
    )


def reject_remediation(
    *,
    db: Session,
    remediation_id: UUID,
    rejected_by: str,
    rejection_reason: str,
) -> RemediationDecisionResult:
    return _record_decision(
        db=db,
        remediation_id=remediation_id,
        decided_by=rejected_by,
        decision=ApprovalDecision.REJECTED,
        rejection_reason=rejection_reason,
    )
