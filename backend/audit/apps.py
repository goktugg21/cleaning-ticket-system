from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "audit"
    verbose_name = "Audit Log"

    def ready(self):
        # Importing audit.signals connects pre_save/post_save/post_delete
        # handlers for User, Company, Building, Customer. The handlers
        # short-circuit on AnyApp.AuditLog so we never recurse.
        from . import signals  # noqa: F401
