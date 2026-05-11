"""
Sprint 10 / 16 / 19 / 21 / 21-v2 — pre-pilot guard: refuse to leave
demo accounts in place on a host headed for production.

The seed_demo_data command (used for local walkthroughs and the demo
fixtures) creates well-known accounts in two demo companies. The
scripts/demo_up.sh helper additionally seeded a small set of
@example.com accounts as part of the local-HTTP smoke flow until
Sprint 21 migrated it to call seed_demo_data directly.

  Sprint 21 v2 canonical demo accounts (current):
    superadmin@cleanops.demo
    ramazan-admin-osius@b-amsterdam.demo
    gokhan-manager-osius@b-amsterdam.demo
    murat-manager-osius@b-amsterdam.demo
    isa-manager-osius@b-amsterdam.demo
    tom-customer-b-amsterdam@b-amsterdam.demo
    iris-customer-b-amsterdam@b-amsterdam.demo
    amanda-customer-b-amsterdam@b-amsterdam.demo
    sophie-admin-bright@bright-facilities.demo
    bram-manager-bright@bright-facilities.demo
    lotte-customer-bright@bright-facilities.demo

  Sprint 21 v1 (superseded by v2 but still rejected if present):
    super@cleanops.demo, admin@cleanops.demo,
    gokhan@cleanops.demo, murat@cleanops.demo,
    isa@cleanops.demo, tom@cleanops.demo,
    iris@cleanops.demo, amanda@cleanops.demo,
    admin-b@cleanops.demo, manager-b@cleanops.demo,
    customer-b@cleanops.demo
    plus the stray operator superadmin@osius.demo

  Sprint 10 — legacy seed_demo (removed in Sprint 21 but kept in
  this list as defense-in-depth):
    demo-super@example.com, demo-company-admin@example.com,
    demo-manager@example.com, demo-customer@example.com

  Sprint 19 — demo_up.sh local smoke seed:
    admin@example.com, companyadmin@example.com,
    manager@example.com, customer@example.com

  Sprint 14 — seed_b_amsterdam_demo (removed in Sprint 21):
    tom@b-amsterdam.com, iris@b-amsterdam.com,
    amanda@b-amsterdam.com, gokhan.kocak@osius.demo,
    murat.ugurlu@osius.demo, isa.ugurlu@osius.demo

All canonical demo accounts share the password `Demo12345!`. Leaving
any of them on a public-facing host is a trivial admin compromise.

Three non-routable demo TLDs are reserved for the seed personas, so
a real production user can never use them. We reject any email
whose domain ends with one of:

  @cleanops.demo
  @b-amsterdam.demo
  @bright-facilities.demo

This catches any future seed persona that lands under one of those
TLDs without needing a code change to this guard first.

Usage:
    docker compose -f docker-compose.prod.yml exec -T backend \\
        python manage.py check_no_demo_accounts

Exit codes:
    0 — no demo accounts present.
    1 — at least one demo account exists. Refuse to launch.

Operator runbook: this command is the last manual gate in
docs/pilot-launch-checklist.md before pilot go-live.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q


# Explicit list — kept in sync with seed_demo_data.py rather than
# imported, so a future refactor of the seed cannot accidentally erase
# the entries this guard refuses to allow on a pilot host. The domain
# suffix rules below are a defense-in-depth catch-all, but the
# explicit list ensures the message we print names the actual account
# so the operator can purge it deterministically.
DEMO_EMAILS = (
    # ---- Sprint 21 v2 canonical (current) ----
    "superadmin@cleanops.demo",
    "ramazan-admin-osius@b-amsterdam.demo",
    "gokhan-manager-osius@b-amsterdam.demo",
    "murat-manager-osius@b-amsterdam.demo",
    "isa-manager-osius@b-amsterdam.demo",
    "tom-customer-b-amsterdam@b-amsterdam.demo",
    "iris-customer-b-amsterdam@b-amsterdam.demo",
    "amanda-customer-b-amsterdam@b-amsterdam.demo",
    "sophie-admin-bright@bright-facilities.demo",
    "bram-manager-bright@bright-facilities.demo",
    "lotte-customer-bright@bright-facilities.demo",

    # ---- Sprint 21 v1 (superseded by v2 but still rejected) ----
    "super@cleanops.demo",
    "admin@cleanops.demo",
    "gokhan@cleanops.demo",
    "murat@cleanops.demo",
    "isa@cleanops.demo",
    "tom@cleanops.demo",
    "iris@cleanops.demo",
    "amanda@cleanops.demo",
    "admin-b@cleanops.demo",
    "manager-b@cleanops.demo",
    "customer-b@cleanops.demo",
    # Sprint 21 v2 prune: stray operator super-admin discovered on
    # the local demo DB. Not from any seed but still demo-flavoured.
    "superadmin@osius.demo",

    # ---- Sprint 10 legacy seed_demo (removed in Sprint 21) ----
    "demo-super@example.com",
    "demo-company-admin@example.com",
    "demo-manager@example.com",
    "demo-customer@example.com",

    # ---- Sprint 19 demo_up.sh / prod_upload_download_test.sh ----
    "admin@example.com",
    "companyadmin@example.com",
    "manager@example.com",
    "customer@example.com",

    # ---- Sprint 14 seed_b_amsterdam_demo (removed in Sprint 21) ----
    "tom@b-amsterdam.com",
    "iris@b-amsterdam.com",
    "amanda@b-amsterdam.com",
    "gokhan.kocak@osius.demo",
    "murat.ugurlu@osius.demo",
    "isa.ugurlu@osius.demo",
)

# Suffix-level guard for any demo account under the three reserved
# non-routable TLDs. Real production users cannot have any of these
# because the .demo TLD is not delegable, so a suffix match is safe
# even if a typo or a future variant slips past the explicit list.
DEMO_DOMAIN_SUFFIXES = (
    "@cleanops.demo",
    "@b-amsterdam.demo",
    "@bright-facilities.demo",
)


class Command(BaseCommand):
    help = "Refuse to launch if any seed_demo account exists. Exit 1 if found."

    def handle(self, *args, **options):
        User = get_user_model()
        # Match active AND soft-deleted rows — a demo account that was
        # soft-deleted but still in the table is still a credential
        # leak risk if reactivation is possible. Reactivation is
        # SUPER_ADMIN-only but that is policy, not absence.
        suffix_filter = Q()
        for suffix in DEMO_DOMAIN_SUFFIXES:
            suffix_filter |= Q(email__iendswith=suffix)
        present = list(
            User.objects.filter(
                Q(email__in=DEMO_EMAILS) | suffix_filter
            )
            .values_list("email", flat=True)
            .distinct()
        )
        if present:
            self.stderr.write(
                "[FAIL] demo accounts present on this host: " + ", ".join(sorted(present))
            )
            self.stderr.write(
                "Delete them before pilot launch — see docs/pilot-launch-checklist.md."
            )
            raise SystemExit(1)
        self.stdout.write("[OK] no demo accounts found.")
