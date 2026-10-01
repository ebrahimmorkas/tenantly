from django.utils import timezone
from rest_framework import serializers

from .models import KEY_PREFIX, APIKey, Scope


class APIKeySerializer(serializers.ModelSerializer):
    scopes = serializers.ListField(
        child=serializers.ChoiceField(choices=Scope.choices), allow_empty=False
    )
    display = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = APIKey
        fields = [
            "id",
            "name",
            "display",
            "scopes",
            "is_active",
            "created_at",
            "last_used_at",
            "expires_at",
            "revoked_at",
        ]
        read_only_fields = ["id", "created_at", "last_used_at", "revoked_at"]

    def get_display(self, key) -> str:
        return f"{KEY_PREFIX}{key.prefix}_••••"

    def validate_scopes(self, scopes):
        return sorted(set(scopes))

    def validate_expires_at(self, value):
        if value and value <= timezone.now():
            raise serializers.ValidationError("Must be in the future.")
        return value


class CreatedAPIKeySerializer(APIKeySerializer):
    key = serializers.CharField(read_only=True, help_text="Shown only once. Store it securely.")

    class Meta(APIKeySerializer.Meta):
        fields = [*APIKeySerializer.Meta.fields, "key"]
