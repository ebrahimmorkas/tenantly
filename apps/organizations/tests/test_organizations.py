import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.tests.factories import UserFactory
from apps.organizations.models import Membership, Role
from apps.organizations.tests.factories import MembershipFactory, OrganizationFactory

pytestmark = pytest.mark.django_db


def members_url(org):
    return reverse("member-list", kwargs={"org_slug": org.slug})


def member_url(org, membership):
    return reverse("member-detail", kwargs={"org_slug": org.slug, "pk": membership.pk})


def test_creator_becomes_owner():
    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        reverse("org-list"), {"name": "Globex Corp", "billing_email": "ap@globex.io"}, format="json"
    )

    assert response.status_code == 201
    assert response.json()["slug"] == "globex-corp"
    assert Membership.objects.get(user=user).role == Role.OWNER


def test_list_only_my_organizations(member_client, org):
    client = member_client(Role.MEMBER)
    OrganizationFactory(name="Someone else")

    response = client.get(reverse("org-list"))

    assert [o["slug"] for o in response.json()["results"]] == [org.slug]
    assert response.json()["results"][0]["role"] == "member"


def test_non_members_get_404_not_403(org):
    outsider = APIClient()
    outsider.force_authenticate(UserFactory())

    assert outsider.get(members_url(org)).status_code == 404
    assert outsider.get(reverse("org-detail", kwargs={"org_slug": org.slug})).status_code == 404


def test_anonymous_gets_401(org, api_client):
    assert api_client.get(members_url(org)).status_code == 401


def test_only_admins_update_organization(member_client, org):
    url = reverse("org-detail", kwargs={"org_slug": org.slug})

    assert member_client(Role.BILLING).patch(url, {"name": "X"}, format="json").status_code == 403
    assert member_client(Role.ADMIN).patch(url, {"name": "X"}, format="json").status_code == 200


def test_members_can_list_but_not_add(member_client, org):
    client = member_client(Role.MEMBER)
    UserFactory(email="new@acme.io")

    assert client.get(members_url(org)).status_code == 200
    response = client.post(members_url(org), {"email": "new@acme.io"}, format="json")
    assert response.status_code == 403


def test_admin_adds_member_by_email(member_client, org):
    client = member_client(Role.ADMIN)
    new_user = UserFactory(email="new@acme.io")

    response = client.post(
        members_url(org), {"email": "NEW@acme.io", "role": "billing"}, format="json"
    )

    assert response.status_code == 201
    assert Membership.objects.get(user=new_user, organization=org).role == Role.BILLING


def test_add_member_validation(member_client, org):
    client = member_client(Role.ADMIN)
    existing = MembershipFactory(organization=org)

    unknown = client.post(members_url(org), {"email": "ghost@acme.io"}, format="json")
    duplicate = client.post(members_url(org), {"email": existing.user.email}, format="json")

    assert unknown.status_code == 400
    assert duplicate.status_code == 400


def test_only_owner_can_grant_owner(member_client, org):
    UserFactory(email="new@acme.io")

    response = member_client(Role.ADMIN).post(
        members_url(org), {"email": "new@acme.io", "role": "owner"}, format="json"
    )

    assert response.status_code == 400


def test_cannot_remove_or_demote_last_owner(member_client, org):
    client = member_client(Role.OWNER)
    owner = client.membership

    demote = client.patch(member_url(org, owner), {"role": "admin"}, format="json")
    remove = client.delete(member_url(org, owner))

    assert demote.status_code == 400
    assert remove.status_code == 400


def test_owner_can_leave_when_another_owner_exists(member_client, org):
    client = member_client(Role.OWNER)
    MembershipFactory(organization=org, role=Role.OWNER)

    assert client.delete(member_url(org, client.membership)).status_code == 204


def test_admin_cannot_remove_owner(member_client, org):
    owner = MembershipFactory(organization=org, role=Role.OWNER)
    MembershipFactory(organization=org, role=Role.OWNER)

    response = member_client(Role.ADMIN).delete(member_url(org, owner))

    assert response.status_code == 400


def test_memberships_from_other_orgs_are_invisible(member_client, org):
    foreign = MembershipFactory()

    response = member_client(Role.OWNER).delete(member_url(org, foreign))

    assert response.status_code == 404
