def calculate_release_risk(*args, **kwargs) -> dict:
    """
    Supports both:
    calculate_release_risk(payload_dict)
    calculate_release_risk(build_status=..., trivy_status=...)
    """

    if args and isinstance(args[0], dict):
        payload = args[0]
    else:
        payload = kwargs

    build_status = payload.get("build_status")
    test_status = payload.get("test_status")
    sonar_status = payload.get("sonar_status")
    trivy_status = payload.get("trivy_status")

    trivy_critical = int(payload.get("trivy_critical") or 0)
    trivy_high = int(payload.get("trivy_high") or 0)
    trivy_medium = int(payload.get("trivy_medium") or 0)

    vulnerabilities = int(payload.get("vulnerabilities") or 0)
    bugs = int(payload.get("bugs") or 0)

    coverage = payload.get("coverage")
    try:
        coverage = float(coverage) if coverage is not None else None
    except Exception:
        coverage = None

    score = 0
    recommendations = []

    if build_status == "FAILED":
        score += 30
        recommendations.append("Fix the build failure before release.")

    if test_status == "FAILED":
        score += 25
        recommendations.append("Fix failing tests before release.")

    if sonar_status == "FAILED":
        score += 15
        recommendations.append("Review SonarQube quality gate issues.")

    if trivy_status in {"FAILED", "SKIPPED"}:
        score += 10
        recommendations.append("Ensure Trivy security scan runs successfully.")

    if trivy_critical > 0:
        score += min(40, trivy_critical * 20)
        recommendations.append("Fix critical Trivy vulnerabilities immediately.")

    if trivy_high > 0:
        score += min(30, trivy_high * 10)
        recommendations.append("Fix high severity Trivy vulnerabilities before release.")

    if trivy_medium > 0:
        score += min(15, trivy_medium * 3)
        recommendations.append("Review medium severity Trivy vulnerabilities.")

    if vulnerabilities > 0:
        score += min(20, vulnerabilities * 5)
        recommendations.append("Resolve reported dependency or code vulnerabilities.")

    if bugs > 0:
        score += min(15, bugs * 3)
        recommendations.append("Fix reported bugs from static analysis.")

    if coverage is not None and coverage < 50:
        score += 10
        recommendations.append("Improve test coverage for critical paths.")

    score = min(score, 100)

    if score >= 80:
        level = "CRITICAL"
    elif score >= 60:
        level = "HIGH"
    elif score >= 35:
        level = "MEDIUM"
    else:
        level = "LOW"

    summary = (
        f"Release risk is {level} with score {score}/100. "
        f"Build={build_status}, Tests={test_status}, Sonar={sonar_status}, "
        f"Trivy={trivy_status}, Trivy critical/high={trivy_critical}/{trivy_high}."
    )

    if not recommendations:
        recommendations = [
            "Release risk is low. Continue monitoring build, test, SonarQube, and Trivy results."
        ]

    return {
        "risk_score": score,
        "risk_level": level,
        "risk_summary": summary,
        "recommendations": recommendations,
    }
    

def _get_run_value(run, key, default=None):
    if run is None:
        return default

    if isinstance(run, dict):
        return run.get(key, default)

    return getattr(run, key, default)


def calculate_risk_score(run):
    score = 0
    recommendations = []

    build_status = _get_run_value(run, "build_status", "UNKNOWN")
    test_status = _get_run_value(run, "test_status", "UNKNOWN")
    quality_gate = _get_run_value(run, "quality_gate", "UNKNOWN")

    coverage = _get_run_value(run, "coverage", 0) or 0
    bugs = _get_run_value(run, "bugs", 0) or 0
    vulnerabilities = _get_run_value(run, "vulnerabilities", 0) or 0
    code_smells = _get_run_value(run, "code_smells", 0) or 0

    trivy_critical = _get_run_value(run, "trivy_critical", 0) or 0
    trivy_high = _get_run_value(run, "trivy_high", 0) or 0
    trivy_medium = _get_run_value(run, "trivy_medium", 0) or 0

    if build_status == "FAILED":
        score += 25
        recommendations.append("Fix build failures before release.")

    if test_status == "FAILED":
        score += 25
        recommendations.append("Fix failing tests before release.")

    if quality_gate in ["ERROR", "FAILED"]:
        score += 20
        recommendations.append("Resolve Sonar quality gate failure.")

    if coverage < 60:
        score += 15
        recommendations.append("Increase test coverage above 60%.")
    elif coverage < 75:
        score += 8
        recommendations.append("Improve test coverage before release.")

    if bugs:
        score += min(15, bugs * 3)
        recommendations.append("Review and fix Sonar bugs.")

    if vulnerabilities:
        score += min(20, vulnerabilities * 5)
        recommendations.append("Resolve Sonar vulnerabilities.")

    if code_smells and code_smells > 50:
        score += 5
        recommendations.append("Reduce code smells.")

    if trivy_critical:
        score += min(40, trivy_critical * 10)
        recommendations.append("Fix critical Trivy vulnerabilities immediately.")

    if trivy_high:
        score += min(25, trivy_high * 4)
        recommendations.append("Fix high severity Trivy vulnerabilities.")

    if trivy_medium:
        score += min(10, trivy_medium)
        recommendations.append("Review medium severity Trivy vulnerabilities.")

    score = min(score, 100)

    if score >= 75:
        level = "CRITICAL"
    elif score >= 50:
        level = "HIGH"
    elif score >= 25:
        level = "MEDIUM"
    else:
        level = "LOW"

    if level == "LOW":
        summary = "Release risk is low. Build, test, quality, and security signals look acceptable."
    elif level == "MEDIUM":
        summary = "Release risk is moderate. Review the highlighted issues before release."
    elif level == "HIGH":
        summary = "Release risk is high. Important build, quality, or security issues should be fixed before release."
    else:
        summary = "Release risk is critical. Do not release until the major issues are resolved."

    if not recommendations:
        recommendations = ["No major release blockers detected."]

    return score, level, summary, recommendations