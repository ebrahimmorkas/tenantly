from rest_framework import serializers

from apps.billing.serializers import InvoiceItemSerializer

from .models import Invoice


class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, read_only=True)
    amount_due = serializers.IntegerField(read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "number",
            "status",
            "currency",
            "subtotal",
            "total",
            "amount_paid",
            "amount_due",
            "period_start",
            "period_end",
            "issued_at",
            "due_at",
            "paid_at",
            "items",
        ]


class UpcomingLineSerializer(serializers.Serializer):
    kind = serializers.CharField()
    description = serializers.CharField()
    amount = serializers.IntegerField()


class UpcomingInvoiceSerializer(serializers.Serializer):
    currency = serializers.CharField()
    billing_date = serializers.DateTimeField()
    lines = UpcomingLineSerializer(many=True)
    total = serializers.IntegerField()
