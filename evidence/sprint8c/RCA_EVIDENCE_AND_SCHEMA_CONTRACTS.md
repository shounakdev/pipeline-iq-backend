# Sprint 8C Evidence and RCA Schemas

## Objective

Define strict evidence and RCA response contracts before implementing collectors or calling an LLM.

## Added schema module

- app/rca/schemas.py

## Added tests

- tests/rca/test_evidence_schemas.py

## Evidence schemas added

- EvidenceSourceMetadata
- IncidentContextEvidence
- DeploymentEvidence
- PipelineEvidence
- SLOBreachEvidence
- MetricsEvidence
- LogsEvidence
- TraceEvidence
- KubernetesEvidence
- IncidentEvidenceBundle

## RCA output schemas added

- RCAOutputSchema
- SupportingEvidenceItem
- RecommendedAction
- AlternativeHypothesis
- RCAMissingEvidenceItem

## Controlled enums added

- EvidenceSourceStatus
- RCAConfidence
- RootCauseCategory
- RecommendationPriority

## Validation rules confirmed

- Invalid source statuses are rejected.
- Negative source record counts are rejected.
- Invalid RCA confidence values are rejected.
- HIGH confidence RCA output requires supporting evidence.
- Supporting evidence requires an evidence path.
- Missing evidence is represented as structured objects.
- ORM objects are not returned directly from RCA schema contracts.

## Test result

Schema test suite passed.
