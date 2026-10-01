"""Domain events for invoices (sent after the transaction commits)."""

from django.dispatch import Signal

# kwargs: invoice
invoice_finalized = Signal()

# kwargs: invoice
invoice_paid = Signal()

# kwargs: invoice, attempt
invoice_payment_failed = Signal()
