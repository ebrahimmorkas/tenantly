from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from apps.apikeys.authentication import HasScope
from apps.apikeys.models import Scope
from apps.invoicing.services import create_invoice
from apps.organizations.models import Role
from apps.organizations.tenancy import OrganizationScopedMixin, ReadAnyWriteRole

from . import services
from .models import Plan, Subscription
from .serializers import (
    CancelSerializer,
    PlanChangeSerializer,
    PlanChoiceSerializer,
    PlanSerializer,
    SubscriptionSerializer,
)


class BillingConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "billing_error"


class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    """Public plan catalog."""

    serializer_class = PlanSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "code"
    queryset = Plan.objects.filter(is_active=True)


class SubscriptionViewSet(OrganizationScopedMixin, viewsets.ViewSet):
    """The organization's current subscription (a singleton resource).

    Members and ``billing:read`` API keys can read it; billing managers and
    above can change it.
    """

    permission_classes = [ReadAnyWriteRole.at_least(Role.BILLING) | HasScope.of(Scope.BILLING_READ)]

    def check_permissions(self, request):
        super().check_permissions(request)
        # API keys are read-only for subscriptions.
        is_api_key = hasattr(request.auth, "scopes")
        if is_api_key and request.method not in permissions.SAFE_METHODS:
            self.permission_denied(request, message="API keys cannot modify subscriptions.")

    def current(self) -> Subscription:
        subscription = (
            self.scope(Subscription.objects.select_related("plan", "pending_plan"))
            .exclude(status=Subscription.Status.CANCELED)
            .first()
        )
        if subscription is None:
            raise Http404("No active subscription.")
        return subscription

    def _run(self, func, **kwargs):
        try:
            return func(**kwargs)
        except services.BillingError as exc:
            raise BillingConflict(str(exc)) from exc

    @extend_schema(responses=SubscriptionSerializer)
    def list(self, request, org_slug):
        return Response(SubscriptionSerializer(self.current()).data)

    @extend_schema(request=PlanChoiceSerializer, responses={201: SubscriptionSerializer})
    def create(self, request, org_slug):
        payload = PlanChoiceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        subscription = self._run(
            services.subscribe, organization=self.organization, plan=payload.validated_data["plan"]
        )
        create_invoice(self.organization, subscription=subscription)  # first period, in advance
        return Response(SubscriptionSerializer(subscription).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[OpenApiParameter("plan", str, required=True)],
        responses=PlanChangeSerializer,
    )
    @action(detail=False, methods=["get"], url_path="preview-change")
    def preview_change(self, request, org_slug):
        payload = PlanChoiceSerializer(data=request.query_params)
        payload.is_valid(raise_exception=True)
        subscription = self.current()
        mode, lines = self._run(
            services.preview_change,
            subscription=subscription,
            new_plan=payload.validated_data["plan"],
        )
        return Response(self._change_payload(mode, lines, subscription.plan.currency))

    @extend_schema(request=PlanChoiceSerializer, responses=PlanChangeSerializer)
    @action(detail=False, methods=["post"], url_path="change-plan")
    def change_plan(self, request, org_slug):
        payload = PlanChoiceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        subscription = self.current()
        mode, lines = self._run(
            services.change_plan,
            subscription=subscription,
            new_plan=payload.validated_data["plan"],
        )
        if lines:
            create_invoice(self.organization, subscription=subscription)  # bill proration now
        data = self._change_payload(mode, lines, subscription.plan.currency)
        data["subscription"] = SubscriptionSerializer(self.current()).data
        return Response(data)

    @extend_schema(request=CancelSerializer, responses=SubscriptionSerializer)
    @action(detail=False, methods=["post"])
    def cancel(self, request, org_slug):
        payload = CancelSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        subscription = self._run(
            services.cancel,
            subscription=self.current(),
            at_period_end=payload.validated_data["at_period_end"],
        )
        return Response(SubscriptionSerializer(subscription).data)

    @extend_schema(request=None, responses=SubscriptionSerializer)
    @action(detail=False, methods=["post"])
    def resume(self, request, org_slug):
        subscription = self._run(services.resume, subscription=self.current())
        return Response(SubscriptionSerializer(subscription).data)

    @staticmethod
    def _change_payload(mode, lines, currency) -> dict:
        return {
            "mode": mode,
            "lines": services.describe(lines, currency),
            "total": sum(line.amount for line in lines),
        }
