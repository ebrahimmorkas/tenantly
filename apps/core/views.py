import logging

from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class HealthCheckView(APIView):
    """Liveness/readiness probe used by Docker and load balancers."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = []

    @extend_schema(responses={200: dict, 503: dict})
    def get(self, request):
        checks = {"database": self._check_database(), "cache": self._check_cache()}
        healthy = all(checks.values())
        return Response(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status=200 if healthy else 503,
        )

    @staticmethod
    def _check_database() -> bool:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except Exception:
            logger.exception("Database health check failed")
            return False

    @staticmethod
    def _check_cache() -> bool:
        try:
            cache.set("healthcheck", "ok", timeout=5)
            return cache.get("healthcheck") == "ok"
        except Exception:
            logger.exception("Cache health check failed")
            return False
