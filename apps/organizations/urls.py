from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.apikeys.views import APIKeyViewSet
from apps.billing.views import PlanViewSet, SubscriptionViewSet

from .views import MembershipViewSet, OrganizationViewSet

router = DefaultRouter()
router.register("orgs", OrganizationViewSet, basename="org")
router.register("plans", PlanViewSet, basename="plan")

# Tenant-scoped resources live under /orgs/<org_slug>/...; other apps add theirs here.
tenant_router = DefaultRouter()
tenant_router.register("members", MembershipViewSet, basename="member")
tenant_router.register("api-keys", APIKeyViewSet, basename="api-key")
tenant_router.register("subscription", SubscriptionViewSet, basename="subscription")

urlpatterns = [
    *router.urls,
    path("orgs/<slug:org_slug>/", include(tenant_router.urls)),
]
