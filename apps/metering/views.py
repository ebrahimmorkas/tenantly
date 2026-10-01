from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.apikeys.authentication import HasScope
from apps.apikeys.models import Scope
from apps.billing.models import Subscription
from apps.organizations.models import Role
from apps.organizations.tenancy import HasRole, OrganizationScopedMixin

from . import services
from .models import DEFAULT_METRIC, UsageRecord
from .serializers import UsageRecordSerializer, UsageSummarySerializer


class UsageViewSet(
    OrganizationScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Report and inspect metered usage.

    ``POST`` is meant for the tenant's backend using an API key with the
    ``usage:write`` scope (admins may also post). Retrying with the same
    ``idempotency_key`` returns ``200`` with the original record instead of
    counting twice.
    """

    serializer_class = UsageRecordSerializer
    filterset_fields = ["metric"]

    def get_permissions(self):
        if self.action == "create":
            return [(HasScope.of(Scope.USAGE_WRITE) | HasRole.at_least(Role.ADMIN))()]
        return [(HasScope.of(Scope.BILLING_READ) | HasRole.at_least(Role.MEMBER))()]

    def get_queryset(self):
        return self.scope(UsageRecord.objects.all())

    @extend_schema(responses={201: UsageRecordSerializer, 200: UsageRecordSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            record, created = services.record_usage(
                organization=self.organization, **serializer.validated_data
            )
        except services.UsageError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(
            UsageRecordSerializer(record).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(responses=UsageSummarySerializer)
    @action(detail=False, methods=["get"])
    def summary(self, request, org_slug):
        subscription = (
            self.scope(Subscription.objects.select_related("plan"))
            .exclude(status=Subscription.Status.CANCELED)
            .first()
        )
        if subscription is None:
            raise Http404("No active subscription.")
        plan = subscription.plan
        start, end = subscription.current_period_start, subscription.current_period_end
        used = services.usage_between(self.organization, start, end)
        blocks, amount = services.overage(plan, used)
        payload = {
            "metric": DEFAULT_METRIC,
            "period_start": start,
            "period_end": end,
            "used": used,
            "included": plan.included_units,
            "overage_units": max(used - plan.included_units, 0),
            "projected_overage_amount": amount,
            "currency": plan.currency,
        }
        return Response(UsageSummarySerializer(payload).data)
