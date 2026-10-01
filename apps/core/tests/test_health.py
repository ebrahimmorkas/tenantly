import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_check_reports_ok(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": True, "cache": True}}


@pytest.mark.django_db
def test_openapi_schema_is_served(client):
    response = client.get(reverse("schema"))

    assert response.status_code == 200
    assert b"Tenantly API" in response.content
