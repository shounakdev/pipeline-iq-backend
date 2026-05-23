import os
from dotenv import load_dotenv
from celery import Celery

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "cicd_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks"]
)

celery_app.conf.task_routes = {
    "app.tasks.execute_pipeline_task": {"queue": "pipeline_queue"}
}