from django.contrib import admin

from .models import WebhookDelivery, WebhookEndpoint, WebhookEvent


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ["url", "organization", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["url", "organization__name"]
    exclude = ["secret"]


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["id", "type", "organization", "created_at"]
    list_filter = ["type"]


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ["id", "event", "endpoint", "status", "attempts", "response_status"]
    list_filter = ["status"]
