# Sprint 8D Evidence Collector Framework

## Objective

Create a reusable collector interface and orchestration layer for deterministic RCA evidence collection.

## Implemented

- EvidenceCollector protocol
- EvidenceCollectionContext
- CollectorResult
- CollectorStatus enum
- Deterministic evidence window calculation
- Independent collector failure handling
- Redaction before final bundle creation
- Payload limits before storage or LLM submission
- Collector duration tracking
- Completeness scoring

## Important rule

No LLM integration exists in Sprint 8D.

## Failure behavior

A failed collector returns a FAILED source result and does not discard other collector outputs.

Example:

{
  "source_name": "loki",
  "status": "FAILED",
  "data": null,
  "error": "Loki query timed out"
}

## Tests

- Evidence window tests
- Redaction tests
- Orchestrator failure isolation tests

## DB-backed orchestration

The orchestrator can now:

- Load an incident by ID
- Validate that the incident exists
- Resolve the primary service name
- Resolve environment from the incident
- Build a deterministic evidence collection context
- Execute collectors with timeout handling
- Store the final redacted and limited evidence bundle in IncidentEvidence
- Track source statuses and collection errors
- Increment evidence version per incident
