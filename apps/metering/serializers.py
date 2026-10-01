from rest_framework import serializers

from .models import DEFAULT_METRIC, UsageRecord


class UsageRecordSerializer(serializers.ModelSerializer):
    metric = serializers.RegexField(r"^[a-z][a-z0-9_]{0,39}$", default=DEFAULT_METRIC)
    timestamp = serializers.DateTimeField(required=False)

    class Meta:
        model = UsageRecord
        fields = ["id", "metric", "quantity", "timestamp", "idempotency_key", "created_at"]
        read_only_fields = ["id", "created_at"]
        # Uniqueness is enforced by the service so retries return the original record.
        validators = []


class UsageSummarySerializer(serializers.Serializer):
    metric = serializers.CharField()
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()
    used = serializers.IntegerField()
    included = serializers.IntegerField()
    overage_units = serializers.IntegerField()
    projected_overage_amount = serializers.IntegerField()
    currency = serializers.CharField()
