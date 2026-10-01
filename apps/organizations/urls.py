from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.apikeys.views import APIKeyViewSet
from apps.billing.views import PlanViewSet, SubscriptionViewSet
from apps.invoicing.views import InvoiceViewSet
from apps.metering.views import UsageViewSet
from apps.payments.views import PaymentMethodViewSet, PaymentViewSet

from .views import MembershipViewSet, OrganizationViewSet

router = DefaultRouter()
router.register("orgs", OrganizationViewSet, basename="org")
router.register("plans", PlanViewSet, basename="plan")

# Tenant-scoped resources live under /orgs/<org_slug>/...; other apps add theirs here.
tenant_router = DefaultRouter()
tenant_router.register("members", MembershipViewSet, basename="member")
tenant_router.register("api-keys", APIKeyViewSet, basename="api-key")
tenant_router.register("subscription", SubscriptionViewSet, basename="subscription")
tenant_router.register("usage", UsageViewSet, basename="usage")
tenant_router.register("invoices", InvoiceViewSet, basename="invoice")
tenant_router.register("payment-method", PaymentMethodViewSet, basename="payment-method")
tenant_router.register("payments", PaymentViewSet, basename="payment")

urlpatterns = [
    *router.urls,
    path("orgs/<slug:org_slug>/", include(tenant_router.urls)),
]
