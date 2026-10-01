from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.billing.views import BillingConflict
from apps.invoicing.models import Invoice
from apps.organizations.models import Role
from apps.organizations.tenancy import OrganizationScopedMixin, ReadAnyWriteRole

from . import services
from .models import Payment, PaymentMethod
from .serializers import PaymentMethodSerializer, PaymentSerializer


class PaymentMethodViewSet(OrganizationScopedMixin, viewsets.ViewSet):
    """The organization's default card (singleton). Billing managers can replace it."""

    permission_classes = [ReadAnyWriteRole.at_least(Role.BILLING)]

    @extend_schema(responses=PaymentMethodSerializer)
    def list(self, request, org_slug):
        method = PaymentMethod.objects.filter(organization=self.organization).first()
        if method is None:
            raise Http404("No payment method on file.")
        return Response(PaymentMethodSerializer(method).data)

    @extend_schema(request=PaymentMethodSerializer, responses={201: PaymentMethodSerializer})
    def create(self, request, org_slug):
        payload = PaymentMethodSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            method = services.set_payment_method(self.organization, payload.validated_data["token"])
        except services.PaymentError as exc:
            raise ValidationError({"token": str(exc)}) from exc
        return Response(PaymentMethodSerializer(method).data, status=status.HTTP_201_CREATED)


class PaymentViewSet(OrganizationScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Payment attempts, plus ``POST pay/<invoice number>/`` to retry an open invoice now."""

    serializer_class = PaymentSerializer
    permission_classes = [ReadAnyWriteRole.at_least(Role.BILLING)]
    filterset_fields = ["status"]

    def get_queryset(self):
        return Payment.objects.filter(invoice__organization=self.organization).select_related(
            "invoice"
        )

    @extend_schema(request=None, responses={200: PaymentSerializer})
    @action(detail=False, methods=["post"], url_path=r"pay/(?P<number>[A-Z0-9-]+)")
    def pay(self, request, org_slug, number):
        invoice = get_object_or_404(self.scope(Invoice.objects.all()), number=number)
        if invoice.status != Invoice.Status.OPEN:
            raise BillingConflict(f"Invoice is {invoice.status}.")
        try:
            payment = services.attempt_payment(invoice.pk)
        except services.PaymentError as exc:
            raise BillingConflict(str(exc)) from exc
        return Response(PaymentSerializer(payment).data)
