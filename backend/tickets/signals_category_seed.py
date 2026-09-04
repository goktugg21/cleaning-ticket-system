"""W13 — a new company starts with the owner's seven categories.

The migration seeds every company that existed when it ran. This seeds
the ones created afterwards, so "which categories do I have" has the
same answer on day one as on day one thousand and no operator has to
find a "load the standard list" button before they can file a melding.

## Why a signal and not a button

The five sibling catalogs are a company's own vocabulary — the trades it
distinguishes, the hour types it pays — so they start empty and an
operator fills them. This one is not: Verzoek / Extra / Compliment /
Melden / Storing / Ongegrond / Klacht is the product's answer to "what
kinds of melding are there", replacing an enum that every company had
whether it wanted it or not. Starting empty would be a regression from
the enum it replaces, and a company with no categories would have a
create form with no classification on it at all.

It stays a CATALOG rather than an enum because the point is that a
company can then rename, re-order, archive or extend it — which is what
it could never do before.

## get_or_create, not create

Idempotent on the (company, slug) unique constraint, so a company
created inside a test that also runs the migration, or a fixture loaded
twice, does not blow up on a duplicate. `created` is not checked because
"it was already there" is a perfectly good outcome.
"""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="companies.Company", dispatch_uid="w13_seed_ticket_categories")
def seed_ticket_categories(sender, instance, created, **kwargs):
    if not created:
        return

    from .category_seed import seed_rows
    from .models import TicketCategory

    for row in seed_rows():
        TicketCategory.objects.get_or_create(
            company=instance,
            slug=row["slug"],
            defaults={k: v for k, v in row.items() if k != "slug"},
        )
