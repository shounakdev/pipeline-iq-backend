"""Enums used by the incident response module."""

from enum import Enum


class IncidentStatus(str, Enum):
    DETECTED = "DETECTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    ACTION_RECOMMENDED = "ACTION_RECOMMENDED"
    REMEDIATING = "REMEDIATING"
    RESOLVED = "RESOLVED"
    FAILED_RECOVERY = "FAILED_RECOVERY"


class IncidentSeverity(str, Enum):
    SEV_1 = "SEV-1"
    SEV_2 = "SEV-2"
    SEV_3 = "SEV-3"