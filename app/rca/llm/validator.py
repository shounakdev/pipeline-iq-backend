from typing import Any

from app.rca.llm.schemas import RCAReportDraft


class RCAValidationResult(dict):
    pass


def _path_exists(data: dict[str, Any], path: str) -> bool:
    current: Any = data

    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return False
            current = current[index]
        else:
            return False

    return True


def _all_evidence_paths(report: RCAReportDraft) -> list[str]:
    paths: list[str] = []

    for observation in report.supporting_observations:
        paths.append(observation.evidence_path)

    for observation in report.contradicting_observations:
        paths.append(observation.evidence_path)

    for hypothesis in report.alternative_hypotheses:
        paths.extend(hypothesis.supporting_evidence_paths)

    for action in report.recommended_actions:
        if action.evidence_path:
            paths.append(action.evidence_path)

    return paths


def validate_rca_report(
    *,
    report: RCAReportDraft,
    evidence_json: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    for path in _all_evidence_paths(report):
        if not _path_exists(evidence_json, path):
            errors.append(f"Supporting evidence path {path} does not exist.")

    if report.confidence == "HIGH" and len(report.supporting_observations) < 2:
        warnings.append("High confidence requires at least two supporting observations.")
        report.confidence = "MEDIUM"

    if report.confidence == "HIGH":
        unique_roots = {
            observation.evidence_path.split(".")[0]
            for observation in report.supporting_observations
        }

        if len(unique_roots) < 2:
            warnings.append("High confidence requires multiple evidence sources.")
            report.confidence = "MEDIUM"

    if not report.supporting_observations:
        report.confidence = "LOW"
        if report.root_cause_category not in {"INSUFFICIENT_EVIDENCE", "UNKNOWN"}:
            warnings.append("No supporting observations found; confidence capped to LOW.")

    for action in report.recommended_actions:
        if action.advisory_only is not True:
            errors.append("Recommended actions must be advisory only.")

    return {
        "validation_status": "FAILED" if errors else "PASSED",
        "errors": errors,
        "warnings": warnings,
        "report": report,
    }