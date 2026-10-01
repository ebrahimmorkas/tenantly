from django.contrib import admin

from apps.billing.models import InvoiceItem

from .models import Invoice


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    can_delete = False
    readonly_fields = ["kind", "description", "quantity", "unit_amount", "amount", "currency"]
    exclude = ["organization", "subscription", "period_start", "period_end"]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["number", "organization", "status", "total", "currency", "issued_at", "due_at"]
    list_filter = ["status", "currency"]
    search_fields = ["number", "organization__name"]
    date_hierarchy = "issued_at"
    inlines = [InvoiceItemInline]
    readonly_fields = ["number", "subtotal", "total", "amount_paid", "issued_at"]
