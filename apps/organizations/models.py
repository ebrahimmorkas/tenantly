from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.core.models import TimeStampedModel


class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    BILLING = "billing", "Billing manager"
    MEMBER = "member", "Member"


# Higher number = more privileges. Each role includes everything below it.
ROLE_RANK = {Role.MEMBER: 0, Role.BILLING: 1, Role.ADMIN: 2, Role.OWNER: 3}


class Organization(TimeStampedModel):
    """A tenant. Every billable resource belongs to exactly one organization."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60, unique=True)
    billing_email = models.EmailField()
    currency = models.CharField(max_length=3, default="usd")
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="Membership", related_name="organizations"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:50] or "org"
            slug, n = base, 2
            while Organization.objects.filter(slug=slug).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)


class Membership(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)

    class Meta:
        ordering = ["organization", "user"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="unique_membership"),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization} ({self.role})"

    def has_role(self, minimum: str) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[minimum]
