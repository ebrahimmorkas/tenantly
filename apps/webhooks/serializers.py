from rest_framework import serializers

from .models import EventType, WebhookDelivery, WebhookEndpoint
from .urlsafety import UnsafeURL, check_url


class WebhookEndpointSerializer(serializers.ModelSerializer):
    events = serializers.ListField(
        child=serializers.ChoiceField(choices=EventType.choices), required=False
    )

    class Meta:
        model = WebhookEndpoint
        fields = ["id", "url", "description", "events", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_url(self, url):
        try:
            check_url(url)
        except UnsafeURL as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return url

    def validate_events(self, events):
        return sorted(set(events))


class WebhookEndpointWithSecretSerializer(WebhookEndpointSerializer):
    secret = serializers.CharField(read_only=True)

    class Meta(WebhookEndpointSerializer.Meta):
        fields = [*WebhookEndpointSerializer.Meta.fields, "secret"]


class WebhookDeliverySerializer(serializers.ModelSerializer):
    event_id = serializers.SerializerMethodField()
    event_type = serializers.CharField(source="event.type")

    class Meta:
        model = WebhookDelivery
        fields = [
            "id",
            "event_id",
            "event_type",
            "status",
            "attempts",
            "response_status",
            "last_error",
            "next_attempt_at",
            "delivered_at",
            "created_at",
        ]

    def get_event_id(self, delivery) -> str:
        return f"evt_{delivery.event_id}"
