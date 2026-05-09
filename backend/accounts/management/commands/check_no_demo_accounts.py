"""
Sprint 10 — pre-pilot guard: refuse to leave demo accounts in place
on a host headed for production.

The seed_demo command (used for local walkthroughs and the demo
fixture) creates four well-known accounts:

  demo-super@example.com
  demo-company-admin@example.com
  demo-manager@example.com
  demo-customer@example.com

All four share the password `Demo12345!` documented in
docs/demo-walkthrough.md. Leaving any of them on a public-facing
host is a trivial admin compromise.

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


# Hard-coded list — derived from accounts/management/commands/seed_demo.py.
# Kept in sync deliberately rather than imported, so a future refactor
# of seed_demo cannot accidentally erase the list of accounts this
# guard refuses to allow on a pilot host.
DEMO_EMAILS = (
    "demo-super@example.com",
    "demo-company-admin@example.com",
    "demo-manager@example.com",
    "demo-customer@example.com",
)


class Command(BaseCommand):
    help = "Refuse to launch if any seed_demo account exists. Exit 1 if found."

    def handle(self, *args, **options):
        User = get_user_model()
        # Match active AND soft-deleted rows — a demo account that was
        # soft-deleted but still in the table is still a credential
        # leak risk if reactivation is possible. Reactivation is
        # SUPER_ADMIN-only but that is policy, not absence.
        present = list(
            User.objects.filter(email__in=DEMO_EMAILS).values_list("email", flat=True)
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
