from django.contrib import admin

from .models import Membership, Organization


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "billing_email", "currency", "created_at"]
    search_fields = ["name", "slug", "billing_email"]
    inlines = [MembershipInline]
