from django.db import models

from .idempotency import IdempotencyRecord  # noqa: F401  (registers the model)


class TimeStampedModel(models.Model):
    """Abstract base model that tracks creation and modification times."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
