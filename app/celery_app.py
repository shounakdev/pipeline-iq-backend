import os
import ssl
from celery import Celery
from dotenv import load_dotenv

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
    include=["app.tasks"],  # important: registers execute_pipeline_task
)

celery_app.conf.update(
    task_ignore_result=True,
    result_backend="disabled://",
    broker_connection_retry_on_startup=True,
    task_routes={
        "app.tasks.execute_pipeline_task": {
            "queue": "pipeline_queue"
        }
    },
)

if CELERY_BROKER_URL.startswith("rediss://"):
    celery_app.conf.broker_use_ssl = {
        "ssl_cert_reqs": ssl.CERT_NONE,
    }