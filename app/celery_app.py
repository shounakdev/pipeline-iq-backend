import os
import ssl

from celery import Celery
from dotenv import load_dotenv

from app.events.consumer import run_event_consumer_once
from app.events.outbox_publisher import run_outbox_publisher_once


load_dotenv()

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL")

if not CELERY_BROKER_URL:
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = os.getenv("REDIS_PORT", "6379")
    CELERY_BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"

celery_app = Celery(
    "pipeline_worker",
    broker=CELERY_BROKER_URL,
    backend="disabled://",
    include=["app.tasks"],  # registers execute_pipeline_task
)

celery_app.conf.update(
    task_ignore_result=True,
    result_backend="disabled://",
    broker_connection_retry_on_startup=True,
    task_routes={
        "app.tasks.execute_pipeline_task": {
            "queue": "pipeline_queue",
        },
        "events.publish_outbox_events": {
            "queue": "pipeline_queue",
        },
        "events.consume_kafka_events": {
            "queue": "pipeline_queue",
        },
    },
)

if CELERY_BROKER_URL.startswith("rediss://"):
    celery_app.conf.broker_use_ssl = {
        "ssl_cert_reqs": ssl.CERT_NONE,
    }


@celery_app.task(name="events.publish_outbox_events")
def publish_outbox_events_task():
    return run_outbox_publisher_once()


@celery_app.task(name="events.consume_kafka_events")
def consume_kafka_events_task():
    return run_event_consumer_once()


existing_beat_schedule = getattr(celery_app.conf, "beat_schedule", None) or {}

celery_app.conf.beat_schedule = {
    **existing_beat_schedule,
    "publish-outbox-events-every-10-seconds": {
        "task": "events.publish_outbox_events",
        "schedule": 10.0,
        "options": {"queue": "pipeline_queue"},
    },
    "consume-kafka-events-every-10-seconds": {
        "task": "events.consume_kafka_events",
        "schedule": 10.0,
        "options": {"queue": "pipeline_queue"},
    },
}