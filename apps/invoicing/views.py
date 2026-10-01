from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.apikeys.authentication import HasScope
from apps.apikeys.models import Scope
from apps.organizations.models import Role
from apps.organizations.tenancy import HasRole, OrganizationScopedMixin

from .models import Invoice
from .serializers import InvoiceSerializer, UpcomingInvoiceSerializer
from .services import upcoming_invoice


class InvoiceViewSet(OrganizationScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Invoices of the organization (members and ``billing:read`` API keys)."""

    serializer_class = InvoiceSerializer
    permission_classes = [HasRole.at_least(Role.MEMBER) | HasScope.of(Scope.BILLING_READ)]
    filterset_fields = ["status"]
    lookup_field = "number"

    def get_queryset(self):
        return self.scope(Invoice.objects.prefetch_related("items"))

    @extend_schema(responses=UpcomingInvoiceSerializer)
    @action(detail=False, methods=["get"])
    def upcoming(self, request, org_slug):
        preview = upcoming_invoice(self.organization)
        if preview is None:
            raise Http404("No active subscription.")
        return Response(UpcomingInvoiceSerializer(preview).data)
