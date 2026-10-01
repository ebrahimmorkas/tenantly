from django.contrib import admin

from .models import InvoiceItem, Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "amount", "currency", "interval", "trial_days", "is_active"]
    list_filter = ["interval", "is_active", "currency"]
    search_fields = ["code", "name"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["organization", "plan", "status", "current_period_end", "cancel_at_period_end"]
    list_filter = ["status", "plan"]
    search_fields = ["organization__name", "organization__slug"]
    list_select_related = ["organization", "plan"]


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ["organization", "kind", "description", "amount", "currency", "created_at"]
    list_filter = ["kind"]
    search_fields = ["organization__name", "description"]
