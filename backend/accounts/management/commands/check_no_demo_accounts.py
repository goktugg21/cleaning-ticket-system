"""
Sprint 10 — pre-pilot guard: refuse to leave demo accounts in place
on a host headed for production.

The seed_demo / seed_demo_data commands (used for local walkthroughs
and the demo fixtures) create well-known accounts:

  Sprint 10 (seed_demo)
    demo-super@example.com
    demo-company-admin@example.com
    demo-manager@example.com
    demo-customer@example.com

  Sprint 16 (seed_demo_data)
    super@cleanops.demo
    admin@cleanops.demo
    gokhan@cleanops.demo
    murat@cleanops.demo
    isa@cleanops.demo
    tom@cleanops.demo
    iris@cleanops.demo
    amanda@cleanops.demo

All accounts share the password `Demo12345!`. Leaving any of them on
a public-facing host is a trivial admin compromise.

Sprint 16 broadens the check to also reject ANY user whose email
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


# Explicit list — kept in sync with seed_demo.py and seed_demo_data.py
# rather than imported, so a future refactor of either seed cannot
# accidentally erase the entries this guard refuses to allow on a
# pilot host.
DEMO_EMAILS = (
    # seed_demo (Sprint 10)
    "demo-super@example.com",
    "demo-company-admin@example.com",
    "demo-manager@example.com",
    "demo-customer@example.com",
    # seed_demo_data (Sprint 16)
    "super@cleanops.demo",
    "admin@cleanops.demo",
    "gokhan@cleanops.demo",
    "murat@cleanops.demo",
    "isa@cleanops.demo",
    "tom@cleanops.demo",
    "iris@cleanops.demo",
    "amanda@cleanops.demo",
    # Sprint 19 — demo_up.sh / prod_upload_download_test.sh seeds
    # these "@example.com" accounts with well-known demo passwords
    # (Admin12345!, Test12345!). They were never intended to land
    # on a real pilot host, but the guard previously missed them
    # because the local-demo seed script lives in scripts/, not in
    # a seed_demo* management command. Catching them here keeps
    # the readiness gate honest even if an operator runs the wrong
    # script against the pilot DB by accident.
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
            # SystemExit instead of self.exit() because BaseCommand
            # in Django 5 doesn't expose a public non-zero-exit hook;
            # the management runner converts SystemExit to the
            # process exit code.
            raise SystemExit(1)
        self.stdout.write("[OK] no demo accounts found.")
