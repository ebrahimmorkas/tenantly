"""Tenant resolution and role-based permissions.

Every tenant-scoped endpoint lives under ``/api/v1/orgs/<org_slug>/``. The
:class:`OrganizationScopedMixin` resolves the organization from the URL and the
caller's membership *once per request*. Non-members get a 404 (not 403) so the
existence of other tenants is never revealed.

Querysets in tenant-scoped views must always be filtered by
``self.organization``; :meth:`OrganizationScopedMixin.scope` does that.
"""

from django.http import Http404
from rest_framework.permissions import BasePermission

from .models import ROLE_RANK, Membership, Organization, Role


class OrganizationScopedMixin:
    organization: Organization
    membership: Membership | None

    def check_permissions(self, request):
        # Runs after authentication and before permission classes, so the tenant
        # is known when role-based permissions are evaluated.
        if not request.user.is_authenticated and not _api_key_organization(request):
            self.permission_denied(request)  # -> 401 for unauthenticated callers
        self.organization, self.membership = resolve_tenant(request, self.kwargs["org_slug"])
        super().check_permissions(request)

    def scope(self, queryset):
        return queryset.filter(organization=self.organization)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["organization"] = getattr(self, "organization", None)
        return context


def _api_key_organization(request) -> Organization | None:
    """API-key credentials (``request.auth``) are bound to exactly one organization."""
    return getattr(request.auth, "organization", None)


def resolve_tenant(request, slug: str) -> tuple[Organization, Membership | None]:
    key_org = _api_key_organization(request)
    if key_org is not None:
        if key_org.slug != slug:
            raise Http404("Organization not found.")
        return key_org, None

    membership = (
        Membership.objects.select_related("organization")
        .filter(organization__slug=slug, user=request.user)
        .first()
        if request.user.is_authenticated
        else None
    )
    if membership is None:
        raise Http404("Organization not found.")
    return membership.organization, membership


class HasRole(BasePermission):
    """Require at least ``minimum`` role in the current organization.

    Use ``HasRole.at_least(Role.ADMIN)`` in ``permission_classes``.
    """

    minimum = Role.MEMBER
    message = "Your role in this organization does not allow this action."

    @classmethod
    def at_least(cls, role: str) -> type["HasRole"]:
        return type(f"HasRole_{role}", (cls,), {"minimum": role})

    def has_permission(self, request, view) -> bool:
        membership = getattr(view, "membership", None)
        if membership is None:
            return False
        return ROLE_RANK[membership.role] >= ROLE_RANK[self.minimum]


class ReadAnyWriteRole(HasRole):
    """Any member may read; writes need ``minimum`` role."""

    def has_permission(self, request, view) -> bool:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return getattr(view, "membership", None) is not None
        return super().has_permission(request, view)

    @classmethod
    def at_least(cls, role: str) -> type["ReadAnyWriteRole"]:
        return type(f"ReadAnyWriteRole_{role}", (cls,), {"minimum": role})
