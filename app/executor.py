import os
import subprocess
import tempfile
import shutil
from typing import Any

from app.sonar_service import run_sonar_scan
from app.shared.log_sanitizer import sanitize_log_text, sanitize_log_lines

try:
    from app.pipelineiq.security.trivy_scan import run_trivy_scan
except Exception:
    run_trivy_scan = None

try:
    from app.pipelineiq.risk.risk_engine import calculate_release_risk
except Exception:
    try:
        from app.pipelineiq.risk.release_risk_engine import calculate_release_risk
    except Exception:
        calculate_release_risk = None


def run_command(
    command: list[str],
    cwd: str | None = None,
    log_fn=None,
    timeout: int = 180,
):
    command_text = sanitize_log_text(" ".join(command))

    if log_fn:
        log_fn(f"$ {command_text}")

    try:
        env = os.environ.copy()

        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = ""

        if result.stdout:
            output += result.stdout

        if result.stderr:
            output += result.stderr

        if output.strip() and log_fn:
            log_fn(sanitize_log_text(output.strip()))

        return {
            "success": result.returncode == 0,
            "output": output,
            "return_code": result.returncode,
        }

    except subprocess.TimeoutExpired:
        output = f"Command timed out: {command_text}"

        if log_fn:
            log_fn(sanitize_log_text(output))

        return {
            "success": False,
            "output": output,
            "return_code": -1,
        }


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_present(source: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]

    return default


def _normalize_sonar_result(sonar_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(sonar_result, dict):
        return {}

    metrics = sonar_result.get("metrics")

    if not isinstance(metrics, dict):
        metrics = {}

    return {
        "coverage": _safe_float(
            _first_present(sonar_result, ["coverage"], metrics.get("coverage"))
        ),
        "bugs": _safe_int(
            _first_present(sonar_result, ["bugs"], metrics.get("bugs"))
        ),
        "vulnerabilities": _safe_int(
            _first_present(
                sonar_result,
                ["vulnerabilities"],
                metrics.get("vulnerabilities"),
            )
        ),
        "code_smells": _safe_int(
            _first_present(
                sonar_result,
                ["code_smells", "codeSmells"],
                metrics.get("code_smells") or metrics.get("codeSmells"),
            )
        ),
        "duplicated_lines_density": _safe_float(
            _first_present(
                sonar_result,
                ["duplicated_lines_density", "duplicatedLinesDensity"],
                metrics.get("duplicated_lines_density")
                or metrics.get("duplicatedLinesDensity"),
            )
        ),
        "quality_gate": _first_present(
            sonar_result,
            ["quality_gate", "quality_gate_status", "qualityGate"],
            metrics.get("quality_gate") or metrics.get("qualityGate"),
        ),
        "sonar_issues": _first_present(
            sonar_result,
            ["sonar_issues", "issues"],
            [],
        ),
        "sonar_report_url": _first_present(
            sonar_result,
            ["sonar_report_url", "dashboard_url", "report_url"],
            None,
        ),
    }


def _extract_trivy_counts_from_report(report: dict[str, Any] | None) -> dict[str, int]:
    counts = {
        "trivy_critical": 0,
        "trivy_high": 0,
        "trivy_medium": 0,
        "trivy_low": 0,
        "trivy_unknown": 0,
    }

    if not isinstance(report, dict):
        counts["trivy_total"] = 0
        return counts

    for result in report.get("Results", []) or []:
        vulnerabilities = result.get("Vulnerabilities", []) or []

        for vulnerability in vulnerabilities:
            severity = str(vulnerability.get("Severity", "UNKNOWN")).upper()

            if severity == "CRITICAL":
                counts["trivy_critical"] += 1
            elif severity == "HIGH":
                counts["trivy_high"] += 1
            elif severity == "MEDIUM":
                counts["trivy_medium"] += 1
            elif severity == "LOW":
                counts["trivy_low"] += 1
            else:
                counts["trivy_unknown"] += 1

    counts["trivy_total"] = sum(counts.values())
    return counts


def _normalize_trivy_result(trivy_result: dict[str, Any] | None) -> dict[str, Any]:
    default_counts = {
        "trivy_critical": 0,
        "trivy_high": 0,
        "trivy_medium": 0,
        "trivy_low": 0,
        "trivy_unknown": 0,
        "trivy_total": 0,
    }

    if not isinstance(trivy_result, dict):
        return {
            **default_counts,
            "trivy_report": None,
        }

    report = _first_present(trivy_result, ["trivy_report", "report"], None)

    counts_source = trivy_result.get("counts")

    if not isinstance(counts_source, dict):
        counts_source = trivy_result.get("summary")

    if isinstance(counts_source, dict):
        counts = {
            "trivy_critical": _safe_int(
                _first_present(counts_source, ["critical", "CRITICAL", "trivy_critical"])
            ),
            "trivy_high": _safe_int(
                _first_present(counts_source, ["high", "HIGH", "trivy_high"])
            ),
            "trivy_medium": _safe_int(
                _first_present(counts_source, ["medium", "MEDIUM", "trivy_medium"])
            ),
            "trivy_low": _safe_int(
                _first_present(counts_source, ["low", "LOW", "trivy_low"])
            ),
            "trivy_unknown": _safe_int(
                _first_present(counts_source, ["unknown", "UNKNOWN", "trivy_unknown"])
            ),
        }

        counts["trivy_total"] = _safe_int(
            _first_present(counts_source, ["total", "trivy_total"]),
            sum(counts.values()),
        )

    else:
        counts = {
            "trivy_critical": _safe_int(
                _first_present(trivy_result, ["trivy_critical", "critical"])
            ),
            "trivy_high": _safe_int(
                _first_present(trivy_result, ["trivy_high", "high"])
            ),
            "trivy_medium": _safe_int(
                _first_present(trivy_result, ["trivy_medium", "medium"])
            ),
            "trivy_low": _safe_int(
                _first_present(trivy_result, ["trivy_low", "low"])
            ),
            "trivy_unknown": _safe_int(
                _first_present(trivy_result, ["trivy_unknown", "unknown"])
            ),
        }

        counts["trivy_total"] = _safe_int(
            _first_present(trivy_result, ["trivy_total", "total"]),
            sum(counts.values()),
        )

    if counts["trivy_total"] == 0 and isinstance(report, dict):
        counts = _extract_trivy_counts_from_report(report)

    return {
        **counts,
        "trivy_report": report,
    }


def _run_trivy_scan(repo_path: str, log_fn=None) -> dict[str, Any]:
    if run_trivy_scan is None:
        return {
            "success": False,
            "skipped": True,
            "failure_reason": (
                "Trivy scan module not found. Expected "
                "app.pipelineiq.security.trivy_scan.run_trivy_scan."
            ),
        }

    try:
        try:
            return run_trivy_scan(repo_path=repo_path, log_fn=log_fn)
        except TypeError:
            try:
                return run_trivy_scan(repo_path, log_fn=log_fn)
            except TypeError:
                return run_trivy_scan(repo_path)

    except FileNotFoundError:
        return {
            "success": False,
            "failure_reason": "Trivy binary not found inside the backend container.",
        }

    except Exception as exc:
        return {
            "success": False,
            "failure_reason": f"Trivy scan failed: {str(exc)}",
        }


def _fallback_release_risk(payload: dict[str, Any]) -> dict[str, Any]:
    score = 0
    recommendations: list[str] = []

    build_status = payload.get("build_status")
    test_status = payload.get("test_status")
    sonar_status = payload.get("sonar_status")
    trivy_status = payload.get("trivy_status")

    quality_gate = str(payload.get("quality_gate") or "").upper()

    coverage = _safe_float(payload.get("coverage"))
    bugs = _safe_int(payload.get("bugs"))
    vulnerabilities = _safe_int(payload.get("vulnerabilities"))

    trivy_critical = _safe_int(payload.get("trivy_critical"))
    trivy_high = _safe_int(payload.get("trivy_high"))
    trivy_medium = _safe_int(payload.get("trivy_medium"))

    if build_status == "FAILED":
        score += 35
        recommendations.append("Fix the build failure before release.")

    if test_status == "FAILED":
        score += 30
        recommendations.append("Fix failing tests before release.")

    if sonar_status == "FAILED":
        score += 10
        recommendations.append("Review the SonarQube scan failure.")

    if trivy_status == "FAILED":
        score += 10
        recommendations.append("Review the Trivy scan failure.")

    if quality_gate in {"ERROR", "FAILED", "FAIL"}:
        score += 15
        recommendations.append("Fix SonarQube quality gate issues.")

    elif quality_gate in {"WARN", "WARNING"}:
        score += 5
        recommendations.append("Review SonarQube quality gate warnings.")

    if coverage is not None:
        if coverage < 50:
            score += 15
            recommendations.append("Increase test coverage; it is below 50%.")
        elif coverage < 80:
            score += 5
            recommendations.append("Consider improving test coverage.")

    if bugs > 0:
        score += min(20, bugs * 2)
        recommendations.append("Fix SonarQube bugs before release.")

    if vulnerabilities > 0:
        score += min(20, vulnerabilities * 3)
        recommendations.append("Fix SonarQube-reported vulnerabilities.")

    if trivy_critical > 0:
        score += min(40, trivy_critical * 20)
        recommendations.append("Resolve critical Trivy vulnerabilities immediately.")

    if trivy_high > 0:
        score += min(30, trivy_high * 10)
        recommendations.append("Resolve high Trivy vulnerabilities before production release.")

    if trivy_medium > 0:
        score += min(15, trivy_medium * 2)

    score = min(score, 100)

    if score >= 80:
        risk_level = "CRITICAL"
    elif score >= 55:
        risk_level = "HIGH"
    elif score >= 25:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    if not recommendations:
        recommendations.append(
            "Build, tests, SonarQube, and Trivy look acceptable for this demo run."
        )

    risk_summary = (
        f"Release risk is {risk_level} with score {score}/100. "
        f"Build={build_status or 'UNKNOWN'}, "
        f"Tests={test_status or 'UNKNOWN'}, "
        f"Sonar={sonar_status or 'UNKNOWN'}, "
        f"Trivy={trivy_status or 'UNKNOWN'}, "
        f"Trivy critical/high={trivy_critical}/{trivy_high}."
    )

    return {
        "risk_score": score,
        "risk_level": risk_level,
        "risk_summary": risk_summary,
        "recommendations": recommendations,
        "ai_summary": risk_summary,
    }


def _calculate_release_risk(payload: dict[str, Any], log_fn=None) -> dict[str, Any]:
    if calculate_release_risk is None:
        return _fallback_release_risk(payload)

    try:
        try:
            risk_result = calculate_release_risk(payload)
        except TypeError:
            risk_result = calculate_release_risk(**payload)

        if isinstance(risk_result, dict):
            fallback = _fallback_release_risk(payload)

            return {
                "risk_score": _safe_int(
                    risk_result.get("risk_score"),
                    fallback["risk_score"],
                ),
                "risk_level": risk_result.get("risk_level") or fallback["risk_level"],
                "risk_summary": risk_result.get("risk_summary")
                or fallback["risk_summary"],
                "recommendations": risk_result.get("recommendations")
                or fallback["recommendations"],
                "ai_summary": risk_result.get("ai_summary")
                or risk_result.get("summary")
                or fallback["ai_summary"],
            }

    except Exception as exc:
        if log_fn:
            log_fn(
                "WARNING: Release risk engine failed. "
                f"Using fallback risk engine. Error: {str(exc)}"
            )

    return _fallback_release_risk(payload)


def execute_node_pipeline(
    repo_url: str,
    branch: str,
    stage_fn=None,
    cleanup: bool = True,
):
    logs: list[str] = []
    temp_dir = tempfile.mkdtemp(prefix="platformiq-pipeline-")
    repo_path = os.path.join(temp_dir, "repo")

    state: dict[str, Any] = {
        "commit_sha": None,
        "commit_message": None,

        "build_status": None,
        "test_status": None,
        "sonar_status": None,
        "trivy_status": None,

        "coverage": None,
        "bugs": None,
        "vulnerabilities": None,
        "code_smells": None,
        "duplicated_lines_density": None,
        "quality_gate": None,
        "sonar_issues": [],
        "sonar_report_url": None,

        "trivy_critical": 0,
        "trivy_high": 0,
        "trivy_medium": 0,
        "trivy_low": 0,
        "trivy_unknown": 0,
        "trivy_total": 0,
        "trivy_report": None,

        "risk_score": None,
        "risk_level": None,
        "risk_summary": None,
        "recommendations": [],
        "ai_summary": None,
    }

    def log(message: str):
        if not message:
            return

        clean_message = sanitize_log_text(str(message).strip())

        if not clean_message:
            return

        if logs and logs[-1] == clean_message:
            return

        logs.append(clean_message)

    def stage(stage_name: str, **fields):
        if stage_fn:
            stage_fn(stage_name, **fields)

    def update_state(**fields):
        state.update(fields)

    def finalize(success: bool, failure_reason: str | None = None) -> dict[str, Any]:
        risk_payload = {
            "success": success,
            "failure_reason": failure_reason,
            **state,
        }

        risk_result = _calculate_release_risk(risk_payload, log_fn=log)
        update_state(**risk_result)

        if state.get("risk_summary"):
            log(state["risk_summary"])

        final_stage = "COMPLETED" if success else "FAILED"

        stage(
            final_stage,
            failure_reason=failure_reason,
            **state,
        )

        result = {
            "success": success,
            "logs": sanitize_log_lines(logs),
            "failure_reason": failure_reason,
            **state,
        }

        if not cleanup:
            result["workspace_path"] = temp_dir

        return result

    def fail(failure_reason: str, **fields) -> dict[str, Any]:
        if fields:
            update_state(**fields)

        log(failure_reason)

        return finalize(False, failure_reason=failure_reason)

    try:
        log("Starting real Node.js pipeline execution...")
        log(f"Repo: {repo_url}")
        log(f"Branch: {branch}")

        stage("CLONING")

        clone_result = run_command(
            ["git", "clone", repo_url, "repo"],
            cwd=temp_dir,
            log_fn=log,
            timeout=300,
        )

        if not clone_result["success"]:
            return fail("Git clone failed")

        stage("CHECKOUT")

        checkout_result = run_command(
            ["git", "checkout", branch],
            cwd=repo_path,
            log_fn=log,
            timeout=120,
        )

        if not checkout_result["success"]:
            return fail("Branch checkout failed")

        commit_sha_result = run_command(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            log_fn=None,
            timeout=30,
        )

        if commit_sha_result["success"]:
            update_state(commit_sha=commit_sha_result.get("output", "").strip())

        commit_message_result = run_command(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=repo_path,
            log_fn=None,
            timeout=30,
        )

        if commit_message_result["success"]:
            update_state(commit_message=commit_message_result.get("output", "").strip())

        stage(
            "CHECKOUT",
            commit_sha=state["commit_sha"],
            commit_message=state["commit_message"],
        )

        package_json_path = os.path.join(repo_path, "package.json")

        if not os.path.exists(package_json_path):
            return fail(
                "package.json not found. Only Node.js projects are supported right now."
            )

        package_lock_path = os.path.join(repo_path, "package-lock.json")
        install_command = (
            ["npm", "ci"] if os.path.exists(package_lock_path) else ["npm", "install"]
        )

        stage("INSTALLING")

        install_result = run_command(
            install_command,
            cwd=repo_path,
            log_fn=log,
            timeout=300,
        )

        if not install_result["success"]:
            return fail("npm install failed")

        update_state(test_status="RUNNING")
        stage("TESTING", test_status="RUNNING")

        test_result = run_command(
            ["npm", "test"],
            cwd=repo_path,
            log_fn=log,
            timeout=300,
        )

        if not test_result["success"]:
            return fail("npm test failed", test_status="FAILED")

        update_state(test_status="SUCCESS")
        stage("TESTING", test_status="SUCCESS")

        update_state(build_status="RUNNING")
        stage("BUILDING", build_status="RUNNING")

        build_result = run_command(
            ["npm", "run", "build"],
            cwd=repo_path,
            log_fn=log,
            timeout=300,
        )

        if not build_result["success"]:
            return fail("npm run build failed", build_status="FAILED")

        update_state(build_status="SUCCESS")
        stage("BUILDING", build_status="SUCCESS")

        project_key = os.getenv("SONARQUBE_PROJECT_KEY", "cicd-demo")

        update_state(sonar_status="RUNNING")
        stage("SONAR", sonar_status="RUNNING")

        sonar_result = run_sonar_scan(
            repo_path=repo_path,
            project_key=project_key,
            log_fn=log,
        ) or {}

        sonar_fields = _normalize_sonar_result(sonar_result)
        update_state(**sonar_fields)

        if sonar_result.get("skipped"):
            update_state(sonar_status="SKIPPED")
            stage("SONAR", sonar_status="SKIPPED", **sonar_fields)
            log(
                "WARNING: SonarQube scan skipped. "
                "Continuing because build and tests passed."
            )

        elif not sonar_result.get("success"):
            update_state(sonar_status="FAILED")
            stage("SONAR", sonar_status="FAILED", **sonar_fields)
            log(
                "WARNING: SonarQube scan failed or timed out. "
                "Continuing because build and tests passed."
            )
            log(
                "SonarQube issue: "
                + str(
                    sonar_result.get("error")
                    or sonar_result.get("failure_reason")
                    or "Unknown SonarQube scan issue"
                )
            )

        else:
            update_state(sonar_status="SUCCESS")
            stage("SONAR", sonar_status="SUCCESS", **sonar_fields)
            log("SonarQube scan completed successfully.")

        update_state(trivy_status="RUNNING")
        stage("TRIVY", trivy_status="RUNNING")

        trivy_result = _run_trivy_scan(repo_path=repo_path, log_fn=log) or {}
        trivy_fields = _normalize_trivy_result(trivy_result)
        update_state(**trivy_fields)

        if trivy_result.get("skipped"):
            update_state(trivy_status="SKIPPED")
            stage("TRIVY", trivy_status="SKIPPED", **trivy_fields)
            log(
                "WARNING: Trivy scan skipped. "
                "Continuing because build and tests passed."
            )
            log(
                "Trivy issue: "
                + str(trivy_result.get("failure_reason") or "Unknown Trivy skip reason")
            )

        elif not trivy_result.get("success"):
            update_state(trivy_status="FAILED")
            stage("TRIVY", trivy_status="FAILED", **trivy_fields)
            log(
                "WARNING: Trivy scan failed. "
                "Continuing because build and tests passed."
            )
            log(
                "Trivy issue: "
                + str(
                    trivy_result.get("error")
                    or trivy_result.get("failure_reason")
                    or "Unknown Trivy issue"
                )
            )

        else:
            update_state(trivy_status="SUCCESS")
            stage("TRIVY", trivy_status="SUCCESS", **trivy_fields)
            log(
                "Trivy scan completed successfully. "
                f"Total vulnerabilities: {state['trivy_total']} "
                f"(critical={state['trivy_critical']}, "
                f"high={state['trivy_high']}, "
                f"medium={state['trivy_medium']}, "
                f"low={state['trivy_low']}, "
                f"unknown={state['trivy_unknown']})."
            )

        return finalize(True, failure_reason=None)

    finally:
        if cleanup:
            shutil.rmtree(temp_dir, ignore_errors=True)