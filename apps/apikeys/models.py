"""Organization API keys for server-to-server calls (e.g. reporting usage).

Keys look like ``tk_live_<prefix>_<secret>``. Only a SHA-256 hash of the full key
is stored; the plaintext is shown exactly once, at creation. The non-secret
``prefix`` is indexed so a key can be looked up without scanning the table, and
the hash is compared in constant time.
"""

import hashlib
import hmac
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.organizations.models import Organization


class Scope(models.TextChoices):
    USAGE_WRITE = "usage:write", "Report usage"
    BILLING_READ = "billing:read", "Read subscriptions and invoices"


KEY_PREFIX = "tk_live_"


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


class APIKeyQuerySet(models.QuerySet):
    def active(self):
        now = timezone.now()
        return self.filter(revoked_at__isnull=True).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )


class APIKey(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="api_keys"
    )
    name = models.CharField(max_length=80)
    prefix = models.CharField(max_length=12, unique=True, editable=False)
    hashed_key = models.CharField(max_length=64, editable=False)
    scopes = models.JSONField(default=list)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    objects = APIKeyQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "API key"

    def __str__(self) -> str:
        return f"{self.name} ({KEY_PREFIX}{self.prefix}_…)"

    @classmethod
    def generate(cls, **fields) -> tuple["APIKey", str]:
        """Create a key and return ``(instance, plaintext)``. Plaintext is never stored."""
        prefix = secrets.token_hex(4)
        raw = f"{KEY_PREFIX}{prefix}_{secrets.token_urlsafe(32)}"
        key = cls.objects.create(prefix=prefix, hashed_key=hash_key(raw), **fields)
        return key, raw

    @classmethod
    def from_raw(cls, raw: str) -> "APIKey | None":
        if not raw.startswith(KEY_PREFIX):
            return None
        prefix, _, secret = raw[len(KEY_PREFIX) :].partition("_")
        if not prefix or not secret:
            return None
        key = cls.objects.active().select_related("organization").filter(prefix=prefix).first()
        if key is None or not hmac.compare_digest(key.hashed_key, hash_key(raw)):
            return None
        return key

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()

    def touch(self) -> None:
        """Record usage, at most once a minute to avoid a write on every request."""
        now = timezone.now()
        if self.last_used_at is None or (now - self.last_used_at).total_seconds() > 60:
            APIKey.objects.filter(pk=self.pk).update(last_used_at=now)
            self.last_used_at = now
