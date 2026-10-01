from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User
from apps.apikeys.models import APIKey, Scope
from apps.billing import services as billing
from apps.billing.models import Plan
from apps.invoicing.services import create_invoice
from apps.metering.services import record_usage
from apps.organizations.models import Membership, Organization, Role
from apps.payments.services import set_payment_method

DEMO_PASSWORD = "demo-pass-123"

PLANS = [
    # code, name, cents, trial days, included units, overage cents per 1,000 units
    ("starter", "Starter", 2900, 14, 10_000, 50),
    ("growth", "Growth", 9900, 0, 100_000, 40),
    ("scale", "Scale", 29900, 0, 1_000_000, 25),
]


class Command(BaseCommand):
    help = (
        "Create plans, a demo organization with a subscription, usage, an invoice and an API key."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        for order, (code, name, amount, trial, included, overage) in enumerate(PLANS):
            Plan.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "amount": amount,
                    "trial_days": trial,
                    "included_units": included,
                    "overage_unit_amount": overage,
                    "overage_unit_size": 1000,
                    "sort_order": order,
                    "features": ["API access", "Email support"]
                    + (["Priority support"] if code != "starter" else []),
                },
            )

        if Organization.objects.filter(slug="acme").exists():
            self.stdout.write("Demo organization already exists.")
            return

        owner = User.objects.create_user(
            email="owner@acme.dev", password=DEMO_PASSWORD, full_name="Avery Owner"
        )
        org = Organization.objects.create(
            name="Acme", slug="acme", billing_email="billing@acme.dev"
        )
        Membership.objects.create(organization=org, user=owner, role=Role.OWNER)

        set_payment_method(org, "pm_card_visa")
        billing.subscribe(organization=org, plan=Plan.objects.get(code="growth"))
        create_invoice(org)
        for n in range(5):
            record_usage(organization=org, quantity=4_500 * (n + 1), idempotency_key=f"seed-{n}")

        _, raw_key = APIKey.generate(
            organization=org,
            name="Demo backend",
            scopes=[Scope.USAGE_WRITE, Scope.BILLING_READ],
            created_by=owner,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Demo data ready.\n"
                f"  login:   owner@acme.dev / {DEMO_PASSWORD}  (POST /api/v1/auth/token/)\n"
                f"  org:     /api/v1/orgs/acme/\n"
                f"  API key: {raw_key}\n"
                "           (shown once; usage:write + billing:read)"
            )
        )
