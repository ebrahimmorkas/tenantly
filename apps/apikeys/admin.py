from django.contrib import admin

from .models import APIKey


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "prefix", "created_at", "last_used_at", "revoked_at"]
    list_filter = ["revoked_at"]
    search_fields = ["name", "prefix", "organization__name"]
    readonly_fields = ["prefix", "hashed_key", "created_at", "last_used_at"]
