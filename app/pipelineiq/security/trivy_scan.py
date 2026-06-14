import json
import subprocess
from pathlib import Path


def run_trivy_scan(repo_path: str) -> dict:
    """
    Runs Trivy filesystem scan and returns normalized vulnerability counts.
    """
    path = Path(repo_path)

    if not path.exists():
        return {
            "status": "FAILED",
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "unknown": 0,
            "total": 0,
            "report": {},
            "error": f"Repo path does not exist: {repo_path}",
        }

    try:
        result = subprocess.run(
            [
                "trivy",
                "fs",
                "--format",
                "json",
                "--quiet",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

        if not result.stdout.strip():
            return {
                "status": "FAILED",
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "unknown": 0,
                "total": 0,
                "report": {},
                "error": result.stderr or "Trivy produced no JSON output.",
            }

        report = json.loads(result.stdout)

        counts = {
            "CRITICAL": 0,
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
            "UNKNOWN": 0,
        }

        for item in report.get("Results", []):
            for vuln in item.get("Vulnerabilities", []) or []:
                severity = vuln.get("Severity", "UNKNOWN").upper()
                if severity in counts:
                    counts[severity] += 1
                else:
                    counts["UNKNOWN"] += 1

        total = sum(counts.values())

        return {
            "status": "SUCCESS",
            "critical": counts["CRITICAL"],
            "high": counts["HIGH"],
            "medium": counts["MEDIUM"],
            "low": counts["LOW"],
            "unknown": counts["UNKNOWN"],
            "total": total,
            "report": report,
            "error": None,
        }

    except subprocess.TimeoutExpired:
        return {
            "status": "FAILED",
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "unknown": 0,
            "total": 0,
            "report": {},
            "error": "Trivy scan timed out.",
        }

    except Exception as exc:
        return {
            "status": "FAILED",
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "unknown": 0,
            "total": 0,
            "report": {},
            "error": str(exc),
        }
