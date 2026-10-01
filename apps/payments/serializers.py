from rest_framework import serializers

from .models import Payment, PaymentMethod


class PaymentMethodSerializer(serializers.ModelSerializer):
    token = serializers.CharField(write_only=True, help_text="Gateway token, e.g. pm_card_visa")

    class Meta:
        model = PaymentMethod
        fields = ["token", "brand", "last4", "updated_at"]
        read_only_fields = ["brand", "last4", "updated_at"]


class PaymentSerializer(serializers.ModelSerializer):
    invoice = serializers.SlugRelatedField(slug_field="number", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "invoice",
            "amount",
            "currency",
            "status",
            "failure_reason",
            "attempt",
            "created_at",
        ]
