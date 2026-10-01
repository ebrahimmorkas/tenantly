from django.contrib.auth.models import AnonymousUser
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import authentication, exceptions
from rest_framework.permissions import BasePermission
from rest_framework.throttling import SimpleRateThrottle

from .models import APIKey


class APIKeyAuthentication(authentication.BaseAuthentication):
    """``Authorization: Api-Key tk_live_...`` (or ``X-API-Key`` header).

    On success ``request.user`` is anonymous and ``request.auth`` is the
    :class:`APIKey`, which carries the organization the request is bound to.
    """

    keyword = "Api-Key"

    def authenticate(self, request):
        raw = self._raw_key(request)
        if raw is None:
            return None
        key = APIKey.from_raw(raw)
        if key is None:
            raise exceptions.AuthenticationFailed("Invalid, expired or revoked API key.")
        key.touch()
        return AnonymousUser(), key

    def authenticate_header(self, request) -> str:
        return self.keyword

    def _raw_key(self, request) -> str | None:
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if header.startswith(f"{self.keyword} "):
            return header[len(self.keyword) + 1 :].strip()
        return request.META.get("HTTP_X_API_KEY") or None


class APIKeyScheme(OpenApiAuthenticationExtension):
    target_class = APIKeyAuthentication
    name = "ApiKeyAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": "X-API-Key"}


class HasScope(BasePermission):
    """Allow API-key requests carrying ``scope``; user requests are left to other checks."""

    scope = ""
    message = "This API key is missing the required scope."

    @classmethod
    def of(cls, scope: str) -> type["HasScope"]:
        return type(f"HasScope_{scope}", (cls,), {"scope": scope})

    def has_permission(self, request, view) -> bool:
        return isinstance(request.auth, APIKey) and request.auth.has_scope(self.scope)


class APIKeyRateThrottle(SimpleRateThrottle):
    """Per-key rate limit (stored in the cache, so shared across processes with Redis)."""

    scope = "api_key"

    def get_cache_key(self, request, view):
        if not isinstance(request.auth, APIKey):
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.auth.prefix}
