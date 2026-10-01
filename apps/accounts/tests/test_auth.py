import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests.factories import DEFAULT_PASSWORD, UserFactory

pytestmark = pytest.mark.django_db


def test_register_and_login(api_client):
    response = api_client.post(
        reverse("auth-register"),
        {"email": "Ops@Acme.io", "password": DEFAULT_PASSWORD, "full_name": "Ops"},
        format="json",
    )
    assert response.status_code == 201
    assert User.objects.get().email == "ops@acme.io"

    token = api_client.post(
        reverse("auth-token"), {"email": "ops@acme.io", "password": DEFAULT_PASSWORD}
    ).json()["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    assert api_client.get(reverse("auth-me")).json()["email"] == "ops@acme.io"


def test_duplicate_email_rejected(api_client):
    UserFactory(email="taken@acme.io")

    response = api_client.post(
        reverse("auth-register"),
        {"email": "TAKEN@acme.io", "password": DEFAULT_PASSWORD},
        format="json",
    )

    assert response.status_code == 400


def test_me_requires_auth(api_client):
    assert api_client.get(reverse("auth-me")).status_code == 401
