"""Payment gateway abstraction.

The billing logic only talks to :class:`PaymentGateway`. The default
:class:`FakeGateway` makes the project runnable and testable without any
third-party account; a real provider (Stripe, Adyen, ...) can be plugged in by
pointing ``TENANTLY_PAYMENT_GATEWAY`` at another implementation.
"""

import secrets
from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string


@dataclass(frozen=True)
class ChargeResult:
    success: bool
    reference: str = ""
    failure_reason: str = ""


@dataclass(frozen=True)
class CardDetails:
    brand: str
    last4: str


class PaymentGateway:
    def describe(self, token: str) -> CardDetails:
        raise NotImplementedError

    def charge(
        self, *, token: str, amount: int, currency: str, idempotency_key: str
    ) -> ChargeResult:
        raise NotImplementedError


class FakeGateway(PaymentGateway):
    """Deterministic test gateway, modelled on Stripe's test tokens.

    * ``pm_card_visa`` / ``pm_card_mastercard`` always succeed
    * ``pm_card_declined`` is always declined
    * ``pm_card_insufficient_funds`` is declined for insufficient funds
    """

    CARDS = {
        "pm_card_visa": CardDetails("visa", "4242"),
        "pm_card_mastercard": CardDetails("mastercard", "4444"),
        "pm_card_declined": CardDetails("visa", "0002"),
        "pm_card_insufficient_funds": CardDetails("visa", "9995"),
    }
    FAILURES = {
        "pm_card_declined": "card_declined",
        "pm_card_insufficient_funds": "insufficient_funds",
    }

    def describe(self, token: str) -> CardDetails:
        if token not in self.CARDS:
            raise ValueError("Unknown payment method token.")
        return self.CARDS[token]

    def charge(
        self, *, token: str, amount: int, currency: str, idempotency_key: str
    ) -> ChargeResult:
        if token in self.FAILURES:
            return ChargeResult(success=False, failure_reason=self.FAILURES[token])
        return ChargeResult(success=True, reference=f"ch_{secrets.token_hex(8)}")


def get_gateway() -> PaymentGateway:
    return import_string(settings.TENANTLY_PAYMENT_GATEWAY)()
