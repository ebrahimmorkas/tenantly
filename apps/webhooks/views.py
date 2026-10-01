from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.organizations.models import Role
from apps.organizations.tenancy import HasRole, OrganizationScopedMixin

from .models import EventType, WebhookDelivery, WebhookEndpoint, WebhookEvent, generate_secret
from .serializers import (
    WebhookDeliverySerializer,
    WebhookEndpointSerializer,
    WebhookEndpointWithSecretSerializer,
)
from .tasks import deliver_webhook


class WebhookEndpointViewSet(OrganizationScopedMixin, viewsets.ModelViewSet):
    """Webhook endpoints (admins). The signing secret is shown on create and on rotation."""

    serializer_class = WebhookEndpointSerializer
    permission_classes = [HasRole.at_least(Role.ADMIN)]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        return self.scope(WebhookEndpoint.objects.all())

    @extend_schema(responses={201: WebhookEndpointWithSecretSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        endpoint = serializer.save(organization=self.organization)
        return Response(
            WebhookEndpointWithSecretSerializer(endpoint).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=None, responses=WebhookEndpointWithSecretSerializer)
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request, org_slug, pk=None):
        endpoint = self.get_object()
        endpoint.secret = generate_secret()
        endpoint.save(update_fields=["secret", "updated_at"])
        return Response(WebhookEndpointWithSecretSerializer(endpoint).data)

    @extend_schema(request=None, responses={202: WebhookDeliverySerializer})
    @action(detail=True, methods=["post"])
    def test(self, request, org_slug, pk=None):
        """Send a ``ping`` event to this endpoint only."""
        endpoint = self.get_object()
        event = WebhookEvent.objects.create(
            organization=self.organization, type=EventType.PING, payload={"message": "pong"}
        )
        delivery = WebhookDelivery.objects.create(event=event, endpoint=endpoint)
        deliver_webhook.delay(delivery.pk)
        delivery.refresh_from_db()
        return Response(WebhookDeliverySerializer(delivery).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(responses=WebhookDeliverySerializer(many=True))
    @action(detail=True, methods=["get"])
    def deliveries(self, request, org_slug, pk=None):
        endpoint = self.get_object()
        page = self.paginate_queryset(endpoint.deliveries.select_related("event"))
        return self.get_paginated_response(WebhookDeliverySerializer(page, many=True).data)
