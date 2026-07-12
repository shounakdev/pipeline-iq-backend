from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from app.database import SessionLocal
from app.reliability.prometheus_client import (
    PrometheusClientError,
    PrometheusNoDataError,
)
from app.reliability.slo_engine import (
    evaluate_slo,
    get_enabled_slo_definitions,
)


logger = logging.getLogger(__name__)


def _enum_value(value: Any) -> Any:
    """
    Convert Enum values into readable log values.
    """
    return getattr(value, "value", value)


@shared_task(
    name="app.reliability.tasks.evaluate_all_slos",
)
def evaluate_all_slos() -> dict[str, int]:
    """
    Evaluate every enabled SLO definition.

    Each SLO is handled independently so one Prometheus or database
    failure does not prevent the remaining SLOs from being evaluated.
    """

    db = SessionLocal()

    summary = {
        "enabled": 0,
        "evaluated": 0,
        "breached": 0,
        "alerts_created": 0,
        "failed": 0,
    }

    try:
        slo_definitions = get_enabled_slo_definitions(db)

        summary["enabled"] = len(slo_definitions)

        logger.info(
            "Evaluating SLOs... enabled=%s",
            len(slo_definitions),
        )

        for slo_definition in slo_definitions:
            try:
                result = evaluate_slo(
                    db=db,
                    slo_definition=slo_definition,
                )

            except (
                PrometheusNoDataError,
                PrometheusClientError,
            ) as exc:
                db.rollback()
                summary["failed"] += 1

                logger.warning(
                    "SLO evaluation skipped "
                    "slo_definition_id=%s "
                    "service_id=%s "
                    "metric_type=%s "
                    "reason=%s",
                    slo_definition.id,
                    slo_definition.service_id,
                    _enum_value(slo_definition.metric_type),
                    str(exc),
                )

                continue

            except Exception:
                db.rollback()
                summary["failed"] += 1

                logger.exception(
                    "SLO evaluation failed "
                    "slo_definition_id=%s "
                    "service_id=%s "
                    "metric_type=%s",
                    slo_definition.id,
                    slo_definition.service_id,
                    _enum_value(slo_definition.metric_type),
                )

                continue

            summary["evaluated"] += 1

            if result["is_breached"]:
                summary["breached"] += 1

            if result.get("alert_created", False):
                summary["alerts_created"] += 1

            logger.info(
                "%s %s measured=%.3f "
                "target=%.3f breached=%s",
                result["service_name"],
                _enum_value(result["metric_type"]),
                result["measured_value"],
                result["target_value"],
                result["is_breached"],
            )

            if result.get("alert_created", False):
                logger.warning(
                    "Reliability alert created "
                    "alert_id=%s "
                    "alert_type=%s "
                    "service=%s",
                    result.get("reliability_alert_id"),
                    _enum_value(
                        result.get("reliability_alert_type")
                    ),
                    result["service_name"],
                )

        logger.info(
            "SLO evaluation completed "
            "enabled=%s evaluated=%s breached=%s "
            "alerts_created=%s failed=%s",
            summary["enabled"],
            summary["evaluated"],
            summary["breached"],
            summary["alerts_created"],
            summary["failed"],
        )

        return summary

    finally:
        db.close()