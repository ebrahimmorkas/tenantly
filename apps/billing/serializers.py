from rest_framework import serializers

from .models import InvoiceItem, Plan, Subscription
from .money import format_money


class PlanSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = [
            "code",
            "name",
            "description",
            "amount",
            "currency",
            "price",
            "interval",
            "trial_days",
            "included_units",
            "overage_unit_amount",
            "overage_unit_size",
            "features",
        ]

    def get_price(self, plan) -> str:
        return format_money(plan.amount, plan.currency)


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    pending_plan = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id",
            "status",
            "plan",
            "pending_plan",
            "current_period_start",
            "current_period_end",
            "trial_end",
            "cancel_at_period_end",
            "canceled_at",
            "created_at",
        ]


class PlanChoiceSerializer(serializers.Serializer):
    plan = serializers.SlugRelatedField(
        slug_field="code", queryset=Plan.objects.filter(is_active=True)
    )


class CancelSerializer(serializers.Serializer):
    at_period_end = serializers.BooleanField(default=True)


class ProrationLineSerializer(serializers.Serializer):
    description = serializers.CharField()
    amount = serializers.IntegerField()
    display = serializers.CharField()


class PlanChangeSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["immediate", "scheduled"])
    lines = ProrationLineSerializer(many=True)
    total = serializers.IntegerField()
    subscription = SubscriptionSerializer(required=False)


class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceItem
        fields = [
            "id",
            "kind",
            "description",
            "quantity",
            "unit_amount",
            "amount",
            "currency",
            "period_start",
            "period_end",
        ]
