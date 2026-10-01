"""Consistent error envelope for every API response.

Every error is returned as::

    {"error": {"code": "validation_error", "message": "...", "details": {...}}}
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler


class DomainError(exceptions.APIException):
    """Raised by service-layer code when a business rule is violated."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"
    default_detail = "The request conflicts with the current state of the resource."


def api_exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(
            exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        )

    response = exception_handler(exc, context)
    if response is None:
        return None

    code = getattr(exc, "default_code", "error")
    if isinstance(exc, exceptions.APIException):
        codes = exc.get_codes()
        if isinstance(codes, str):
            code = codes

    detail = response.data
    message = detail.get("detail") if isinstance(detail, dict) else None
    payload = {
        "error": {
            "code": code if isinstance(code, str) else "error",
            "message": str(message) if message else _summary(response.status_code),
        }
    }
    if not message:
        payload["error"]["details"] = detail

    return Response(payload, status=response.status_code, headers=response.headers)


def _summary(status_code: int) -> str:
    if status_code == status.HTTP_400_BAD_REQUEST:
        return "Invalid input."
    return "Request failed."
