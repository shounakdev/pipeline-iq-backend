# Sprint 8G Evidence Quality, Correlation and Storage

## Objective

Convert deterministic collector output into one trustworthy RCA evidence bundle.

## Implemented

- Completeness scoring
- Evidence status calculation
- Missing source tracking
- Collector error preservation
- Deterministic correlation facts
- Contradictory evidence facts
- Stable SHA-256 evidence hash
- LLM-independent bundle generation

## Important rule

Completeness measures evidence availability only. It does not prove correctness or root cause.

## Status rules

- COMPLETED: all weighted evidence sources are usable
- PARTIAL: at least one useful evidence source exists, but one or more are missing
- FAILED: incident missing or no useful evidence collected

## Hashing rules

The evidence hash excludes non-deterministic fields such as collection timestamps and durations.
