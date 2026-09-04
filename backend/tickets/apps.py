from django.apps import AppConfig


class TicketsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tickets'

    def ready(self):
        # W13 — a new company starts with the owner's seven categories.
        # Imported for its `post_save` receiver only; see the module for
        # why this catalog seeds itself and the five siblings do not.
        from . import signals_category_seed  # noqa: F401

        # W-N1 §2 — one chokepoint for "you were put on a part of this
        # ticket". Registered here rather than called from the four
        # create sites, because `sub_task` is also PATCH-writable and a
        # move onto a part creates no row at all. See the module.
        from . import signals_part_assignment  # noqa: F401
