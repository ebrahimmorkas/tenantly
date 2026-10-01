"""``Idempotency-Key`` support for unsafe API requests.

Clients may send ``Idempotency-Key: <unique string>`` with any POST/PATCH/DELETE
to a tenant-scoped endpoint. The first request is processed normally and its
response stored. A retry with the same key:

* replays the stored response (header ``Idempotent-Replayed: true``),
* gets ``409`` if the original request is still being processed,
* gets ``422`` if the body/path differs (the key was reused for something else).

Keys are scoped to the caller (user or API key), so tenants cannot collide.
Server errors (5xx) are not stored, which lets the client retry safely.
"""

import hashlib
import json
from datetime import timedelta

from django.db import IntegrityError, models, transaction
from django.utils import timezone
from rest_framework import exceptions, status
from rest_framework.response import Response

HEADER = "HTTP_IDEMPOTENCY_KEY"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_KEY_LENGTH = 255
RETENTION = timedelta(hours=24)


class IdempotencyRecord(models.Model):
    scope = models.CharField(max_length=80)
    key = models.CharField(max_length=MAX_KEY_LENGTH)
    fingerprint = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField(null=True)
    response_body = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "core"
        constraints = [
            models.UniqueConstraint(fields=["scope", "key"], name="unique_idempotency_key"),
        ]

    def __str__(self) -> str:
        return f"{self.scope}:{self.key}"


class _Replay(Exception):
    def __init__(self, response: Response):
        self.response = response


class IdempotencyConflict(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "idempotency_in_progress"
    default_detail = "A request with this Idempotency-Key is still being processed."


class IdempotencyMismatch(exceptions.APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "idempotency_key_reused"
    default_detail = "This Idempotency-Key was already used for a different request."


def _scope(request) -> str | None:
    if getattr(request.auth, "prefix", None):  # API key
        return f"key:{request.auth.prefix}"
    if request.user.is_authenticated:
        return f"user:{request.user.pk}"
    return None


def _fingerprint(request) -> str:
    body = json.dumps(request.data, sort_keys=True, default=str)
    raw = f"{request.method} {request.path}\n{body}"
    return hashlib.sha256(raw.encode()).hexdigest()


class IdempotencyMixin:
    """Add to an APIView/ViewSet to honour the ``Idempotency-Key`` header."""

    _idempotency_record: IdempotencyRecord | None = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        key = request.META.get(HEADER)
        scope = _scope(request)
        if not key or request.method not in UNSAFE_METHODS or scope is None:
            return
        if len(key) > MAX_KEY_LENGTH:
            raise exceptions.ValidationError({"Idempotency-Key": "Key is too long."})

        fingerprint = _fingerprint(request)
        try:
            with transaction.atomic():
                self._idempotency_record = IdempotencyRecord.objects.create(
                    scope=scope, key=key, fingerprint=fingerprint
                )
                return
        except IntegrityError:
            existing = IdempotencyRecord.objects.get(scope=scope, key=key)

        if existing.fingerprint != fingerprint:
            raise IdempotencyMismatch()
        if existing.status_code is None:
            raise IdempotencyConflict()
        response = Response(existing.response_body, status=existing.status_code)
        response["Idempotent-Replayed"] = "true"
        raise _Replay(response)

    def handle_exception(self, exc):
        if isinstance(exc, _Replay):
            return exc.response
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        record = self._idempotency_record
        if record is not None:
            self._idempotency_record = None
            if response.status_code >= 500:
                record.delete()  # let the client retry
            else:
                record.status_code = response.status_code
                record.response_body = getattr(response, "data", None)
                record.save(update_fields=["status_code", "response_body"])
        return response


def purge_expired(now=None) -> int:
    cutoff = (now or timezone.now()) - RETENTION
    deleted, _ = IdempotencyRecord.objects.filter(created_at__lt=cutoff).delete()
    return deleted
