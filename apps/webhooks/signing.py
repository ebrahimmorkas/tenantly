"""Webhook signatures (same scheme as Stripe).

Header: ``Tenantly-Signature: t=<unix timestamp>,v1=<hex HMAC-SHA256>``, where the
HMAC is computed over ``"<timestamp>.<raw body>"`` with the endpoint secret.
Including the timestamp lets receivers reject replayed requests.
"""

import hashlib
import hmac
import time

HEADER = "Tenantly-Signature"
DEFAULT_TOLERANCE_SECONDS = 300


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    timestamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v1={digest.hexdigest()}"


def verify(
    secret: str,
    body: bytes,
    header: str,
    *,
    tolerance: int = DEFAULT_TOLERANCE_SECONDS,
    now: int | None = None,
) -> bool:
    """Reference implementation for webhook consumers."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
        signature = parts["v1"]
    except (KeyError, ValueError):
        return False
    now = int(time.time()) if now is None else now
    if abs(now - timestamp) > tolerance:
        return False
    expected = sign(secret, body, timestamp).split("v1=", 1)[1]
    return hmac.compare_digest(expected, signature)
