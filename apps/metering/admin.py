from django.contrib import admin

from .models import UsageRecord


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ["organization", "metric", "quantity", "timestamp", "idempotency_key"]
    list_filter = ["metric"]
    search_fields = ["organization__name", "idempotency_key"]
    date_hierarchy = "timestamp"
