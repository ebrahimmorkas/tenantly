from datetime import timedelta

import pytest
from django.urls import path, reverse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView

from apps.apikeys.authentication import APIKeyAuthentication, HasScope
from apps.apikeys.models import APIKey, hash_key
from apps.organizations.models import Role
from apps.organizations.tenancy import OrganizationScopedMixin
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def keys_url(org):
    return reverse("api-key-list", kwargs={"org_slug": org.slug})


# --- model ---------------------------------------------------------------------------


def test_generate_stores_only_a_hash(org):
    key, raw = APIKey.generate(organization=org, name="CI", scopes=["usage:write"])

    assert raw.startswith(f"tk_live_{key.prefix}_")
    assert key.hashed_key == hash_key(raw)
    assert raw not in str(APIKey.objects.values().get())


def test_from_raw(org):
    key, raw = APIKey.generate(organization=org, name="CI", scopes=[])

    assert APIKey.from_raw(raw) == key
    assert APIKey.from_raw(raw[:-1] + ("A" if raw[-1] != "A" else "B")) is None
    assert APIKey.from_raw("garbage") is None
    assert APIKey.from_raw(f"tk_live_{key.prefix}_") is None


def test_revoked_and_expired_keys_are_rejected(org):
    revoked, raw_revoked = APIKey.generate(organization=org, name="a", scopes=[])
    revoked.revoked_at = timezone.now()
    revoked.save()
    _, raw_expired = APIKey.generate(
        organization=org, name="b", scopes=[], expires_at=timezone.now() - timedelta(seconds=1)
    )

    assert APIKey.from_raw(raw_revoked) is None
    assert APIKey.from_raw(raw_expired) is None


# --- management API -------------------------------------------------------------------


def test_admin_creates_key_and_sees_plaintext_once(member_client, org):
    client = member_client(Role.ADMIN)

    created = client.post(
        keys_url(org), {"name": "Backend", "scopes": ["usage:write", "usage:write"]}, format="json"
    )
    listed = client.get(keys_url(org)).json()["results"][0]

    assert created.status_code == 201
    assert created.json()["key"].startswith("tk_live_")
    assert created.json()["scopes"] == ["usage:write"]
    assert "key" not in listed
    assert listed["display"].endswith("_••••")


def test_unknown_scope_rejected(member_client, org):
    response = member_client(Role.ADMIN).post(
        keys_url(org), {"name": "x", "scopes": ["root"]}, format="json"
    )

    assert response.status_code == 400


def test_billing_role_cannot_manage_keys(member_client, org):
    assert member_client(Role.BILLING).get(keys_url(org)).status_code == 403


def test_delete_revokes(member_client, org):
    key, raw = APIKey.generate(organization=org, name="x", scopes=[])
    client = member_client(Role.ADMIN)

    response = client.delete(reverse("api-key-detail", kwargs={"org_slug": org.slug, "pk": key.pk}))

    key.refresh_from_db()
    assert response.status_code == 204
    assert key.revoked_at is not None
    assert APIKey.from_raw(raw) is None


# --- authentication against a tenant-scoped endpoint --------------------------------


class Probe(OrganizationScopedMixin, APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [HasScope.of("usage:write")]

    def get(self, request, org_slug):
        return Response({"org": self.organization.slug})


urlpatterns = [path("orgs/<slug:org_slug>/probe/", Probe.as_view())]


@pytest.mark.urls(__name__)
class TestKeyAuthentication:
    def test_valid_key_with_scope(self, org):
        _, raw = APIKey.generate(organization=org, name="x", scopes=["usage:write"])
        client = APIClient()

        response = client.get(f"/orgs/{org.slug}/probe/", HTTP_AUTHORIZATION=f"Api-Key {raw}")

        assert response.status_code == 200
        assert response.json() == {"org": org.slug}
        assert APIKey.objects.get().last_used_at is not None

    def test_x_api_key_header(self, org):
        _, raw = APIKey.generate(organization=org, name="x", scopes=["usage:write"])

        response = APIClient().get(f"/orgs/{org.slug}/probe/", HTTP_X_API_KEY=raw)

        assert response.status_code == 200

    def test_missing_scope(self, org):
        _, raw = APIKey.generate(organization=org, name="x", scopes=["billing:read"])

        response = APIClient().get(f"/orgs/{org.slug}/probe/", HTTP_X_API_KEY=raw)

        assert response.status_code == 403

    def test_key_cannot_access_another_tenant(self, org):
        other = OrganizationFactory()
        _, raw = APIKey.generate(organization=org, name="x", scopes=["usage:write"])

        response = APIClient().get(f"/orgs/{other.slug}/probe/", HTTP_X_API_KEY=raw)

        assert response.status_code == 404

    def test_invalid_key(self, org):
        response = APIClient().get(f"/orgs/{org.slug}/probe/", HTTP_X_API_KEY="tk_live_nope_x")

        assert response.status_code == 401
