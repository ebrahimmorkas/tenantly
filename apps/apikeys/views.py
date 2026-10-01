from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from apps.organizations.models import Role
from apps.organizations.tenancy import HasRole, OrganizationScopedMixin

from .models import APIKey
from .serializers import APIKeySerializer, CreatedAPIKeySerializer


class APIKeyViewSet(
    OrganizationScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Manage the organization's API keys (admins only). DELETE revokes a key."""

    serializer_class = APIKeySerializer
    permission_classes = [HasRole.at_least(Role.ADMIN)]

    def get_queryset(self):
        return self.scope(APIKey.objects.all())

    @extend_schema(responses={201: CreatedAPIKeySerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key, raw = APIKey.generate(
            organization=self.organization, created_by=request.user, **serializer.validated_data
        )
        key.key = raw
        return Response(CreatedAPIKeySerializer(key).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        if instance.revoked_at is None:
            instance.revoked_at = timezone.now()
            instance.save(update_fields=["revoked_at"])
