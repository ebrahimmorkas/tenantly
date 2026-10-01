from django.db import transaction
from rest_framework import mixins, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import Membership, Organization, Role
from .serializers import MembershipSerializer, MembershipUpdateSerializer, OrganizationSerializer
from .tenancy import OrganizationScopedMixin, ReadAnyWriteRole


class OrganizationViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Organizations the current user belongs to. The creator becomes the owner."""

    serializer_class = OrganizationSerializer
    lookup_field = "slug"
    lookup_url_kwarg = "org_slug"

    def get_queryset(self):
        return Organization.objects.filter(members=self.request.user).prefetch_related(
            "memberships"
        )

    @transaction.atomic
    def perform_create(self, serializer):
        org = serializer.save()
        Membership.objects.create(organization=org, user=self.request.user, role=Role.OWNER)

    def perform_update(self, serializer):
        membership = serializer.instance.memberships.get(user=self.request.user)
        if not membership.has_role(Role.ADMIN):
            raise PermissionDenied("Only admins can update the organization.")
        serializer.save()


class MembershipViewSet(OrganizationScopedMixin, viewsets.ModelViewSet):
    """Members of an organization. Admins manage members; everyone can list them."""

    permission_classes = [ReadAnyWriteRole.at_least(Role.ADMIN)]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        return self.scope(Membership.objects.select_related("user"))

    def get_serializer_class(self):
        return (
            MembershipUpdateSerializer if self.action == "partial_update" else MembershipSerializer
        )

    def perform_update(self, serializer):
        self._guard_last_owner(serializer.instance, new_role=serializer.validated_data.get("role"))
        if serializer.instance.role == Role.OWNER and self.membership.role != Role.OWNER:
            raise ValidationError({"role": "Only owners can change another owner's role."})
        serializer.save()

    def perform_destroy(self, instance):
        self._guard_last_owner(instance, new_role=None)
        if instance.role == Role.OWNER and self.membership.role != Role.OWNER:
            raise ValidationError("Only owners can remove another owner.")
        instance.delete()

    def _guard_last_owner(self, membership, new_role):
        if membership.role != Role.OWNER or new_role == Role.OWNER:
            return
        owners = self.scope(Membership.objects.filter(role=Role.OWNER)).count()
        if owners <= 1:
            raise ValidationError("An organization must keep at least one owner.")
