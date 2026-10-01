import pytest
from rest_framework.test import APIClient

from apps.organizations.models import Role
from apps.organizations.tests.factories import MembershipFactory, OrganizationFactory


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def org(db):
    return OrganizationFactory(name="Acme Inc")


@pytest.fixture
def member_client(org):
    """Return a factory: member_client(role) -> authenticated APIClient for that role."""

    def make(role=Role.OWNER):
        membership = MembershipFactory(organization=org, role=role)
        client = APIClient()
        client.force_authenticate(membership.user)
        client.membership = membership
        return client

    return make
