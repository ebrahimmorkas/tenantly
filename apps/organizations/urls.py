from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import MembershipViewSet, OrganizationViewSet

router = DefaultRouter()
router.register("orgs", OrganizationViewSet, basename="org")

# Tenant-scoped resources live under /orgs/<org_slug>/...; other apps add theirs here.
tenant_router = DefaultRouter()
tenant_router.register("members", MembershipViewSet, basename="member")

urlpatterns = [
    *router.urls,
    path("orgs/<slug:org_slug>/", include(tenant_router.urls)),
]
