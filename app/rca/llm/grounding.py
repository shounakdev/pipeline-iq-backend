from dataclasses import dataclass, field
from typing import Any


@dataclass
class GroundingValidationResult:
    is_valid: bool
    unsupported_claims: list[str] = field(default_factory=list)
    missing_evidence_paths: list[str] = field(default_factory=list)


def _resolve_json_path(data: dict[str, Any], path: str) -> Any:
    if not path or not path.startswith("$."):
        raise KeyError(path)

    current: Any = data
    parts = path[2:].split(".")

    for part in parts:
        if "[" in part and part.endswith("]"):
            key, index_text = part[:-1].split("[", 1)
            current = current[key]
            current = current[int(index_text)]
        else:
            current = current[part]

    return current


def _collect_evidence_paths(report: dict[str, Any]) -> list[str]:
    paths: list[str] = []

    for item in report.get("supporting_evidence", []):
        path = item.get("evidence_path")
        if path:
            paths.append(path)

    for item in report.get("alternative_hypotheses", []):
        path = item.get("contradicting_evidence_path")
        if path:
            paths.append(path)

    for item in report.get("missing_evidence", []):
        path = item.get("evidence_path")
        if path:
            paths.append(path)

    return paths


def validate_rca_grounding(
    report: dict[str, Any],
    evidence: dict[str, Any],
) -> GroundingValidationResult:
    missing_paths: list[str] = []

    for path in _collect_evidence_paths(report):
        try:
            _resolve_json_path(evidence, path)
        except (KeyError, IndexError, TypeError, ValueError):
            missing_paths.append(path)

    unsupported_claims = []

    if report.get("confidence") == "HIGH":
        collected_sources = [
            source
            for source in evidence.get("sources", {}).values()
            if isinstance(source, dict) and source.get("status") == "COLLECTED"
        ]

        if len(collected_sources) <= 1:
            unsupported_claims.append(
                "HIGH confidence requires more than one collected evidence source."
            )

    return GroundingValidationResult(
        is_valid=not missing_paths and not unsupported_claims,
        unsupported_claims=unsupported_claims,
        missing_evidence_paths=missing_paths,
    )
