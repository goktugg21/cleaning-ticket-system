from django.apps import AppConfig


class CustomersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'customers'

    def ready(self):
        # Sprint 27C — register the auto-create-policy receiver. Pure
        # import side-effect; the @receiver decorator wires the
        # post_save handler on Customer.
        from . import signals  # noqa: F401
