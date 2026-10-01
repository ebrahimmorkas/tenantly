"""Invoice numbers must stay gapless and unique under concurrent invoicing.

Uses real threads and row locks, so it only runs on PostgreSQL (CI).
"""

import threading

import pytest
from django.db import connection, connections

from apps.billing.models import InvoiceItem
from apps.invoicing.models import Invoice
from apps.invoicing.services import next_invoice_number
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="requires PostgreSQL row-level locking"
)


@pytest.mark.django_db(transaction=True)
def test_concurrent_invoices_get_gapless_numbers():
    from django.db import transaction

    org = OrganizationFactory(name="Race")
    workers = 8
    barrier = threading.Barrier(workers)
    numbers: list[str] = []

    def issue():
        try:
            barrier.wait()
            with transaction.atomic():
                numbers.append(next_invoice_number(org))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=issue) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(numbers) == [f"RACE-{n:05d}" for n in range(1, workers + 1)]


@pytest.mark.django_db(transaction=True)
def test_concurrent_billing_never_invoices_an_item_twice():
    from apps.invoicing.services import create_invoice

    org = OrganizationFactory(name="Dup")
    for n in range(20):
        InvoiceItem.objects.create(
            organization=org,
            kind="usage",
            description=f"line {n}",
            unit_amount=100,
            amount=100,
            currency="usd",
        )
    barrier = threading.Barrier(4)

    def run():
        try:
            barrier.wait()
            create_invoice(org)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert Invoice.objects.count() == 1
    assert Invoice.objects.get().total == 2000
