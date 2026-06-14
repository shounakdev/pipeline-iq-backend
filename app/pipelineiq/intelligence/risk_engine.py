from app.pipelineiq.risk.release_risk import calculate_release_risk


def calculate_risk_score(pipeline):
    return calculate_release_risk(
        build_status=getattr(pipeline, "build_status", None),
        test_status=getattr(pipeline, "test_status", None),
        sonar_status=getattr(pipeline, "sonar_status", None),
        trivy_status=getattr(pipeline, "trivy_status", None),
        trivy_critical=getattr(pipeline, "trivy_critical", 0) or 0,
        trivy_high=getattr(pipeline, "trivy_high", 0) or 0,
        trivy_medium=getattr(pipeline, "trivy_medium", 0) or 0,
        vulnerabilities=getattr(pipeline, "vulnerabilities", None),
        bugs=getattr(pipeline, "bugs", None),
        coverage=getattr(pipeline, "coverage", None),
    )
