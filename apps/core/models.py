from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base model that tracks creation and modification times."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
