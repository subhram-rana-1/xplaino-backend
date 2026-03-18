"""Celery application configuration for background task processing."""

from celery import Celery
from app.config import settings

celery_app = Celery(
    "caten",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.services.pdf_preprocess_task"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_routes={
        "app.services.pdf_preprocess_task.preprocess_pdf": {"queue": "pdf_preprocess"},
    },
    task_default_queue="default",
)
