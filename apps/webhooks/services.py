"""Publishing events and delivering them to tenant endpoints."""

from __future__ import annotations

import json
import logging
from datetime import timedelta

import httpx
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from .models import WebhookDelivery, WebhookEndpoint, WebhookEvent
from .signing import HEADER, sign
from .urlsafety import UnsafeURL, check_url

logger = logging.getLogger(__name__)

# Delay before attempt n+1 after a failure (attempt 1 is immediate).
RETRY_DELAYS = [
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=12),
]
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
TIMEOUT_SECONDS = 5.0


def http_client() -> httpx.Client:
    """Factory so tests can swap in ``httpx.MockTransport``."""
    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)


@transaction.atomic
def publish(organization, event_type: str, data: dict) -> WebhookEvent | None:
    endpoints = [
        endpoint
        for endpoint in WebhookEndpoint.objects.filter(organization=organization, is_active=True)
        if endpoint.wants(event_type)
    ]
    if not endpoints:
        return None
    # Normalise datetimes/decimals to JSON-safe values before storing the payload.
    payload = json.loads(json.dumps(data, cls=DjangoJSONEncoder))
    event = WebhookEvent.objects.create(organization=organization, type=event_type, payload=payload)
    deliveries = WebhookDelivery.objects.bulk_create(
        [WebhookDelivery(event=event, endpoint=endpoint) for endpoint in endpoints]
    )
    from .tasks import deliver_webhook  # avoid import cycle

    for delivery in deliveries:
        transaction.on_commit(lambda pk=delivery.pk: deliver_webhook.delay(pk))
    return event


def envelope(event: WebhookEvent) -> bytes:
    body = {
        "id": f"evt_{event.pk}",
        "type": event.type,
        "created": int(event.created_at.timestamp()),
        "organization": event.organization.slug,
        "data": event.payload,
    }
    return json.dumps(body, cls=DjangoJSONEncoder, separators=(",", ":")).encode()


def deliver(delivery_id: int, now=None) -> WebhookDelivery:
    now = now or timezone.now()
    delivery = WebhookDelivery.objects.select_related("event__organization", "endpoint").get(
        pk=delivery_id
    )
    if delivery.status != WebhookDelivery.Status.PENDING:
        return delivery

    endpoint = delivery.endpoint
    body = envelope(delivery.event)
    delivery.attempts += 1
    try:
        check_url(endpoint.url)
        with http_client() as client:
            response = client.post(
                endpoint.url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Tenantly-Webhooks/1.0",
                    HEADER: sign(endpoint.secret, body),
                },
            )
        delivery.response_status = response.status_code
        ok = 200 <= response.status_code < 300
        delivery.last_error = "" if ok else f"HTTP {response.status_code}"
    except (httpx.HTTPError, UnsafeURL) as exc:
        ok = False
        delivery.last_error = str(exc)[:255] or exc.__class__.__name__

    if ok:
        delivery.status = WebhookDelivery.Status.SUCCEEDED
        delivery.delivered_at = now
        delivery.next_attempt_at = None
    elif delivery.attempts >= MAX_ATTEMPTS:
        delivery.status = WebhookDelivery.Status.FAILED
        delivery.next_attempt_at = None
        logger.warning(
            "Webhook delivery %s failed permanently: %s", delivery.pk, delivery.last_error
        )
    else:
        delivery.next_attempt_at = now + RETRY_DELAYS[delivery.attempts - 1]
    delivery.save()
    return delivery


def retry_due_deliveries(now=None) -> int:
    now = now or timezone.now()
    due = WebhookDelivery.objects.filter(
        status=WebhookDelivery.Status.PENDING, next_attempt_at__lte=now
    ).values_list("pk", flat=True)
    for pk in due:
        deliver(pk, now=now)
    return len(due)
