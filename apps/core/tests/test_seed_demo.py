import pytest
from django.core.management import call_command

from apps.billing.models import Plan, Subscription
from apps.invoicing.models import Invoice


@pytest.mark.django_db
def test_seed_demo_is_idempotent(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):  # auto-charge runs on commit
        call_command("seed_demo")
    call_command("seed_demo")

    assert Plan.objects.count() == 3
    assert Subscription.objects.get().plan.code == "growth"
    assert Invoice.objects.get().status == Invoice.Status.PAID
