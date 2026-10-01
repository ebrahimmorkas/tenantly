from celery import shared_task

from .idempotency import purge_expired


@shared_task
def purge_idempotency_records() -> int:
    return purge_expired()
