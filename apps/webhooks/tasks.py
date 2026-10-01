from celery import shared_task

from .services import deliver, retry_due_deliveries


@shared_task
def deliver_webhook(delivery_id: int) -> None:
    deliver(delivery_id)


@shared_task
def retry_webhook_deliveries() -> int:
    return retry_due_deliveries()
