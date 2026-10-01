from django.core.management.base import BaseCommand

from apps.invoicing.services import run_billing_cycle


class Command(BaseCommand):
    help = "Renew due subscriptions and issue invoices (cron alternative to Celery beat)."

    def handle(self, *args, **options):
        count = run_billing_cycle()
        self.stdout.write(self.style.SUCCESS(f"Issued {count} invoice(s)."))
