from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents"

    def ready(self):
        # Sprint 125 — register the auto-create-system-folders receiver.
        # Pure import side effect: connecting the post_save handler on
        # Customer (mirrors customers/apps.py's policy-signal wiring).
        from . import signals  # noqa: F401
