"""
Sprint 10 / 16 / 19 / 21 — pre-pilot guard: refuse to leave demo
accounts in place on a host headed for production.

The seed_demo_data command (used for local walkthroughs and the demo
fixtures) creates well-known accounts in two demo companies. The
scripts/demo_up.sh helper additionally seeds a small set of
@example.com accounts as part of the local-HTTP smoke flow.

  Company A — Osius Demo  (seed_demo_data, Sprint 16):
    super@cleanops.demo
    admin@cleanops.demo
    gokhan@cleanops.demo
    murat@cleanops.demo
    isa@cleanops.demo
    tom@cleanops.demo
    iris@cleanops.demo
    amanda@cleanops.demo

  Company B — Bright Facilities  (seed_demo_data, Sprint 21):
    admin-b@cleanops.demo
    manager-b@cleanops.demo
    customer-b@cleanops.demo

  Sprint 10 — legacy seed_demo (removed in Sprint 21 but kept in this
  list as defense-in-depth in case a pilot DB was seeded with the old
  command earlier):
    demo-super@example.com
    demo-company-admin@example.com
    demo-manager@example.com
    demo-customer@example.com

  Sprint 19 — demo_up.sh local smoke seed:
    admin@example.com
    companyadmin@example.com
    manager@example.com
    customer@example.com

All `@cleanops.demo` accounts share the password `Demo12345!`. Leaving
any of them on a public-facing host is a trivial admin compromise.

Sprint 16 broadened the check to also reject ANY user whose email
ends with `@cleanops.demo`, so a future seed that adds new personas
under that suffix is caught even before this list is updated.

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
# the entries this guard refuses to allow on a pilot host. The
# `@cleanops.demo` suffix rule below is a defense-in-depth catch-all,
# but the explicit list ensures the message we print names the actual
# account so the operator can purge it deterministically.
DEMO_EMAILS = (
    # Company A — Osius Demo (Sprint 16, retained Sprint 21)
    "super@cleanops.demo",
    "admin@cleanops.demo",
    "gokhan@cleanops.demo",
    "murat@cleanops.demo",
    "isa@cleanops.demo",
    "tom@cleanops.demo",
    "iris@cleanops.demo",
    "amanda@cleanops.demo",
    # Company B — Bright Facilities (Sprint 21)
    "admin-b@cleanops.demo",
    "manager-b@cleanops.demo",
    "customer-b@cleanops.demo",
    # Legacy seed_demo (Sprint 10 — command removed in Sprint 21, but
    # any DB still carrying these emails from an earlier run should
    # still trip the guard).
    "demo-super@example.com",
    "demo-company-admin@example.com",
    "demo-manager@example.com",
    "demo-customer@example.com",
    # Sprint 19 — demo_up.sh / prod_upload_download_test.sh seed.
    # demo_up.sh has been migrated to call seed_demo_data in Sprint 21,
    # but the entries stay here in case an operator runs an older
    # snapshot of the script against a fresh pilot DB.
    "admin@example.com",
    "companyadmin@example.com",
    "manager@example.com",
    "customer@example.com",
)

# Suffix-level guard for any future demo account added under the
# cleanops.demo TLD. The TLD is deliberately a non-routable .demo
# domain so a real production user could never have it.
DEMO_DOMAIN_SUFFIX = "@cleanops.demo"


class Command(BaseCommand):
    help = "Refuse to launch if any seed_demo account exists. Exit 1 if found."

    def handle(self, *args, **options):
        User = get_user_model()
        # Match active AND soft-deleted rows — a demo account that was
        # soft-deleted but still in the table is still a credential
        # leak risk if reactivation is possible. Reactivation is
        # SUPER_ADMIN-only but that is policy, not absence.
        present = list(
            User.objects.filter(
                Q(email__in=DEMO_EMAILS)
                | Q(email__iendswith=DEMO_DOMAIN_SUFFIX)
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
