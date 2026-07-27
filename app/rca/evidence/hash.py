import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


NON_DETERMINISTIC_FIELDS = {
    "collection_duration_ms",
    "collected_at",
    "generated_at",
    "updated_at",
    "created_at",
    "duration_ms",
}


def normalize_for_hash(value):
    if isinstance(value, dict):
        return {
            key: normalize_for_hash(value[key])
            for key in sorted(value)
            if key not in NON_DETERMINISTIC_FIELDS
        }

    if isinstance(value, list):
        return [normalize_for_hash(item) for item in value]

    if isinstance(value, datetime):
        return value.astimezone().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, UUID):
        return str(value)

    return value


def generate_evidence_hash(evidence_bundle: dict) -> str:
    normalized = normalize_for_hash(evidence_bundle)

    serialized = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()