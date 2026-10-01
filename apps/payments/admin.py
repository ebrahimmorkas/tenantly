from django.contrib import admin

from .models import Payment, PaymentMethod


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ["organization", "brand", "last4", "updated_at"]
    search_fields = ["organization__name"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "invoice",
        "amount",
        "currency",
        "status",
        "failure_reason",
        "attempt",
        "created_at",
    ]
    list_filter = ["status", "failure_reason"]
    search_fields = ["invoice__number", "gateway_reference"]
