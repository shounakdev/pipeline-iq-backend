"""
Legacy compatibility adapter for the incident service.

New code should import incident operations from:

    app.incidents.service

This module remains temporarily available because older event handlers and
worker processes may still import incident functions from:

    app.incidents.incident_service

Do not add database queries, transaction management, timeline generation,
audit generation, or incident business rules to this module.
"""

from app.incidents.service import (
    create_or_update_incident_from_alert,
)


__all__ = [
    "create_or_update_incident_from_alert",
]
