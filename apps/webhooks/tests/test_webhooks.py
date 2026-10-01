import json
from datetime import timedelta

import httpx
import pytest
from django.urls import reverse
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.tests.factories import PlanFactory
from apps.invoicing.services import create_invoice
from apps.organizations.models import Role
from apps.payments import services as payments
from apps.webhooks import services, urlsafety
from apps.webhooks.models import WebhookDelivery, WebhookEndpoint, WebhookEvent
from apps.webhooks.signing import HEADER, sign, verify
from apps.webhooks.urlsafety import UnsafeURL, check_url

pytestmark = pytest.mark.django_db

PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    table = {"hooks.example.com": [PUBLIC_IP], "internal.example.com": ["10.0.0.5"]}
    monkeypatch.setattr(urlsafety, "_resolve", lambda host: table.get(host, [host]))


@pytest.fixture
def receiver(monkeypatch):
    """Capture outgoing requests; ``receiver.status`` sets the response code."""

    class Receiver:
        status = 200
        requests: list[httpx.Request] = []

    def handler(request):
        Receiver.requests.append(request)
        return httpx.Response(Receiver.status)

    Receiver.requests = []
    monkeypatch.setattr(
        services, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    return Receiver


@pytest.fixture
def endpoint(org):
    return WebhookEndpoint.objects.create(organization=org, url="https://hooks.example.com/in")


# --- signing ------------------------------------------------------------------------------


def test_signature_roundtrip():
    header = sign("whsec_test", b'{"a":1}', timestamp=1_700_000_000)

    assert verify("whsec_test", b'{"a":1}', header, now=1_700_000_010)
    assert not verify("whsec_other", b'{"a":1}', header, now=1_700_000_010)
    assert not verify("whsec_test", b'{"a":2}', header, now=1_700_000_010)


def test_signature_rejects_replays_and_garbage():
    header = sign("s", b"{}", timestamp=1_700_000_000)

    assert not verify("s", b"{}", header, now=1_700_000_000 + 301)
    assert not verify("s", b"{}", "nonsense")


# --- SSRF protection --------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/in",  # plain http
        "https://127.0.0.1/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://internal.example.com/hook",  # resolves to 10.0.0.5
        "https://[::1]/hook",
    ],
)
def test_unsafe_urls_are_rejected(url, settings):
    settings.TENANTLY_WEBHOOK_ALLOW_HTTP = False

    with pytest.raises(UnsafeURL):
        check_url(url)


def test_public_https_url_is_allowed():
    check_url("https://hooks.example.com/in")


# --- delivery ---------------------------------------------------------------------------


def test_publish_creates_deliveries_for_subscribed_endpoints(org, endpoint, receiver):
    WebhookEndpoint.objects.create(
        organization=org, url="https://hooks.example.com/paid", events=["invoice.paid"]
    )

    event = services.publish(org, "invoice.created", {"number": "X-1"})

    assert list(event.deliveries.values_list("endpoint", flat=True)) == [endpoint.pk]


def test_delivery_is_signed_and_marked_succeeded(
    org, endpoint, receiver, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        services.publish(org, "invoice.created", {"number": "X-1"})

    request = receiver.requests[0]
    body = json.loads(request.content)
    assert body["type"] == "invoice.created"
    assert body["data"] == {"number": "X-1"}
    assert verify(endpoint.secret, request.content, request.headers[HEADER])
    assert WebhookDelivery.objects.get().status == WebhookDelivery.Status.SUCCEEDED


def test_failed_delivery_is_retried_with_backoff(org, endpoint, receiver):
    receiver.status = 500
    event = WebhookEvent.objects.create(organization=org, type="ping", payload={})
    delivery = WebhookDelivery.objects.create(event=event, endpoint=endpoint)
    now = timezone.now()

    services.deliver(delivery.pk, now=now)
    delivery.refresh_from_db()
    assert (delivery.status, delivery.attempts, delivery.last_error) == ("pending", 1, "HTTP 500")
    assert delivery.next_attempt_at == now + timedelta(minutes=1)

    receiver.status = 204
    assert services.retry_due_deliveries(now=now + timedelta(minutes=2)) == 1
    delivery.refresh_from_db()
    assert delivery.status == WebhookDelivery.Status.SUCCEEDED


def test_delivery_gives_up_after_max_attempts(org, endpoint, receiver):
    receiver.status = 503
    event = WebhookEvent.objects.create(organization=org, type="ping", payload={})
    delivery = WebhookDelivery.objects.create(event=event, endpoint=endpoint)

    for _ in range(services.MAX_ATTEMPTS):
        services.deliver(delivery.pk)

    delivery.refresh_from_db()
    assert delivery.status == WebhookDelivery.Status.FAILED
    assert delivery.attempts == services.MAX_ATTEMPTS


def test_delivery_to_url_that_now_resolves_privately_fails(org, endpoint, receiver, monkeypatch):
    monkeypatch.setattr(urlsafety, "_resolve", lambda host: ["192.168.1.10"])
    event = WebhookEvent.objects.create(organization=org, type="ping", payload={})
    delivery = WebhookDelivery.objects.create(event=event, endpoint=endpoint)

    services.deliver(delivery.pk)

    assert receiver.requests == []
    delivery.refresh_from_db()
    assert "private" in delivery.last_error


def test_billing_events_flow_to_webhooks(
    org, endpoint, receiver, django_capture_on_commit_callbacks
):
    payments.set_payment_method(org, "pm_card_visa")
    billing.subscribe(organization=org, plan=PlanFactory(code="pro", amount=4900))

    with django_capture_on_commit_callbacks(execute=True):
        create_invoice(org)

    types = [json.loads(r.content)["type"] for r in receiver.requests]
    assert types == ["invoice.created", "invoice.paid"]


# --- API ----------------------------------------------------------------------------------


def test_create_endpoint_returns_secret_once(member_client, org):
    client = member_client(Role.ADMIN)
    url = reverse("webhook-list", kwargs={"org_slug": org.slug})

    created = client.post(url, {"url": "https://hooks.example.com/in"}, format="json")
    listed = client.get(url).json()["results"][0]

    assert created.status_code == 201
    assert created.json()["secret"].startswith("whsec_")
    assert "secret" not in listed


def test_api_rejects_unsafe_url(member_client, org):
    response = member_client(Role.ADMIN).post(
        reverse("webhook-list", kwargs={"org_slug": org.slug}),
        {"url": "https://169.254.169.254/"},
        format="json",
    )

    assert response.status_code == 400


def test_rotate_secret_and_test_ping(member_client, org, endpoint, receiver):
    client = member_client(Role.ADMIN)
    kwargs = {"org_slug": org.slug, "pk": endpoint.pk}

    rotated = client.post(reverse("webhook-rotate-secret", kwargs=kwargs)).json()["secret"]
    ping = client.post(reverse("webhook-test", kwargs=kwargs))
    deliveries = client.get(reverse("webhook-deliveries", kwargs=kwargs)).json()["results"]

    assert rotated != endpoint.secret
    assert ping.status_code == 202
    assert ping.json()["status"] == "succeeded"
    assert verify(rotated, receiver.requests[0].content, receiver.requests[0].headers[HEADER])
    assert deliveries[0]["event_type"] == "ping"


def test_members_cannot_manage_webhooks(member_client, org):
    url = reverse("webhook-list", kwargs={"org_slug": org.slug})

    assert member_client(Role.BILLING).get(url).status_code == 403
