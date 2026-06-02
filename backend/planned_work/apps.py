from django.apps import AppConfig


class PlannedWorkConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "planned_work"
    verbose_name = "Planned / Recurring Work"

    def ready(self):
        # Importing planned_work.signals connects the occurrence status
        # history / lifecycle signal handlers. Batch 1 ships a placeholder
        # module so this import succeeds; Batch 2 adds the handlers.
        from . import signals  # noqa: F401
