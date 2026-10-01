from django.apps import AppConfig


class InvoicingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.invoicing"

    def ready(self) -> None:
        from . import receivers  # noqa: F401
