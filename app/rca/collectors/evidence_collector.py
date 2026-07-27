from sqlalchemy.orm import Session

from app.rca.collectors.incident_collector import collect_incident_evidence
from app.rca.collectors.deployment_collector import collect_deployment_evidence
from app.rca.collectors.pipeline_collector import collect_pipeline_evidence
from app.rca.collectors.slo_collector import collect_slo_evidence
from app.rca.collectors.derived_facts import build_derived_facts

from app.rca.collectors.telemetry.prometheus_collector import collect_prometheus_evidence
from app.rca.collectors.telemetry.loki_collector import collect_loki_evidence
from app.rca.collectors.telemetry.trace_collector import collect_trace_evidence
from app.rca.collectors.telemetry.kubernetes_collector import collect_kubernetes_evidence

from app.rca.evidence.bundle import build_evidence_bundle


def collect_native_evidence(db: Session, incident_id) -> dict:
    incident = collect_incident_evidence(db, incident_id)

    if incident.get("status") == "NO_DATA":
        raw_evidence = {
            "incident": incident,
            "deployment": {"status": "NO_DATA", "reason": "Incident not available"},
            "pipeline": {"status": "NO_DATA", "reason": "Incident not available"},
            "slo": {"status": "NO_DATA", "reason": "Incident not available"},
            "metrics": {"status": "NO_DATA", "reason": "Incident not available"},
            "logs": {"status": "NO_DATA", "reason": "Incident not available"},
            "traces": {"status": "NO_DATA", "reason": "Incident not available"},
            "kubernetes": {"status": "NO_DATA", "reason": "Incident not available"},
            "derived_facts": [],
            "collector_errors": [],
        }

        return build_evidence_bundle(raw_evidence)

    deployment = collect_deployment_evidence(db, incident)

    pipeline = collect_pipeline_evidence(
        db=db,
        pipeline_run_id=deployment.get("pipeline_run_id"),
    )

    slo = collect_slo_evidence(db, incident)

    metrics = collect_prometheus_evidence(db, incident)
    logs = collect_loki_evidence(db, incident)
    traces = collect_trace_evidence(db, incident)
    kubernetes = collect_kubernetes_evidence(db, incident)

    raw_evidence = {
        "incident": incident,
        "deployment": deployment,
        "pipeline": pipeline,
        "slo": slo,
        "metrics": metrics,
        "logs": logs,
        "traces": traces,
        "kubernetes": kubernetes,
        "derived_facts": build_derived_facts(
            incident=incident,
            deployment=deployment,
            #pipeline=pipeline,
            slo=slo,
        ),
        "collector_errors": [],
    }

    return build_evidence_bundle(raw_evidence)