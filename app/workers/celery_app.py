from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "shongkhep",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.ingest_news_sources": {"queue": "ingestion"},
    },
    beat_schedule={
        "scheduled-ingestion": {
            "task": "app.workers.tasks.ingest_news_sources",
            "schedule": settings.feed_sync_interval_minutes * 60,
        }
    },
)
