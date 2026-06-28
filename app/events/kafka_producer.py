import json
import os
from functools import lru_cache
from typing import Any, Dict

from confluent_kafka import Producer


KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS",
    "platformiq-kafka:9092",
)

KAFKA_CLIENT_ID = os.getenv(
    "KAFKA_CLIENT_ID",
    "platformiq-backend",
)


@lru_cache(maxsize=1)
def get_kafka_producer() -> Producer:
    return Producer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
            "client.id": KAFKA_CLIENT_ID,
            "acks": "all",
            "enable.idempotence": True,
        }
    )


def publish_event_to_kafka(topic: str, envelope: Dict[str, Any]) -> None:
    producer = get_kafka_producer()
    delivery_errors = []

    def delivery_callback(error, message):
        if error is not None:
            delivery_errors.append(str(error))

    key = envelope.get("correlation_id") or envelope.get("event_id")

    producer.produce(
        topic=topic,
        key=str(key).encode("utf-8"),
        value=json.dumps(envelope, default=str).encode("utf-8"),
        callback=delivery_callback,
    )

    producer.flush(timeout=10)

    if delivery_errors:
        raise RuntimeError("; ".join(delivery_errors))
