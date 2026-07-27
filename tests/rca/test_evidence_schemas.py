from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.rca.schemas import (
    EvidenceSourceMetadata,
    EvidenceSourceStatus,
    RCAConfidence,
    RCAOutputSchema,
    RootCauseCategory,
)


def now():
    return datetime.now(timezone.utc)


def test_source_metadata_rejects_invalid_status():
    with pytest.raises(ValidationError):
        EvidenceSourceMetadata(
            source="prometheus",
            status="BROKEN",
            queried_at=now(),
            record_count=1,
        )


def test_source_metadata_rejects_negative_record_count():
    with pytest.raises(ValidationError):
        EvidenceSourceMetadata(
            source="loki",
            status=EvidenceSourceStatus.AVAILABLE,
            queried_at=now(),
            record_count=-1,
        )


def test_rca_rejects_invalid_confidence():
    with pytest.raises(ValidationError):
        RCAOutputSchema(
            probable_root_cause="Database timeout",
            root_cause_category=RootCauseCategory.DATABASE_DEPENDENCY,
            confidence="VERY_HIGH",
            confidence_score=0.9,
            confidence_reason="Strong evidence",
            supporting_evidence=[
                {
                    "observation": "Timeout errors increased",
                    "evidence_path": "logs.error_patterns",
                    "significance": "Errors align with incident window",
                }
            ],
        )


def test_high_confidence_requires_supporting_evidence():
    with pytest.raises(ValidationError):
        RCAOutputSchema(
            probable_root_cause="Database timeout",
            root_cause_category=RootCauseCategory.DATABASE_DEPENDENCY,
            confidence=RCAConfidence.HIGH,
            confidence_score=0.9,
            confidence_reason="High confidence but no evidence",
            supporting_evidence=[],
        )


def test_supporting_evidence_requires_path():
    with pytest.raises(ValidationError):
        RCAOutputSchema(
            probable_root_cause="Database timeout",
            root_cause_category=RootCauseCategory.DATABASE_DEPENDENCY,
            confidence=RCAConfidence.MEDIUM,
            confidence_score=0.6,
            confidence_reason="Some supporting signs",
            supporting_evidence=[
                {
                    "observation": "Timeout errors increased",
                    "evidence_path": "",
                    "significance": "Important signal",
                }
            ],
        )