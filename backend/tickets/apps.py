from django.apps import AppConfig


class TicketsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tickets'

    def ready(self):
        # W13 — a new company starts with the owner's seven categories.
        # Imported for its `post_save` receiver only; see the module for
        # why this catalog seeds itself and the five siblings do not.
        from . import signals_category_seed  # noqa: F401
