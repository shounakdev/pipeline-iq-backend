# Sprint 8E Native Evidence Collectors

## Objective

Collect PlatformIQ-native evidence before external telemetry.

## Implemented collectors

- Incident collector
- Deployment collector
- Pipeline collector
- SLO collector
- Native evidence orchestrator
- Deterministic derived facts

## Verified behavior

- Missing deployment data returns NO_DATA
- Pipeline run fields are normalized
- Native evidence bundle includes incident, deployment, pipeline, SLO and derived facts
- Derived facts are calculated without an LLM
- Missing deployment evidence does not create false deployment correlation

## Test evidence

See native_collector_tests.txt
