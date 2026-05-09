"""
Sprint 10 — tests for the `check_no_demo_accounts` management command.

The command is the last manual gate before pilot launch
(docs/pilot-launch-checklist.md). It must:
  - exit 0 with an "OK" stdout line when no demo accounts exist;
  - exit 1 with a "FAIL" stderr line listing the offending emails
    when any demo account exists, including soft-deleted ones.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.models import User, UserRole


class CheckNoDemoAccountsTests(TestCase):
    def test_clean_database_passes(self):
        out = StringIO()
        # No demo users created — must exit 0.
        call_command("check_no_demo_accounts", stdout=out, stderr=StringIO())
        self.assertIn("[OK] no demo accounts found", out.getvalue())

    def test_demo_super_account_fails(self):
        User.objects.create_user(
            email="demo-super@example.com",
            password="Demo12345!",
            role=UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        err = StringIO()
        with self.assertRaises(SystemExit) as cm:
            call_command(
                "check_no_demo_accounts",
                stdout=StringIO(),
                stderr=err,
            )
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("demo accounts present", err.getvalue())
        self.assertIn("demo-super@example.com", err.getvalue())

    def test_each_demo_role_fails(self):
        # Independent assertions — each demo email category should
        # individually trigger the guard. We do this in one test to
        # keep the suite fast (each TestCase wraps a transaction; the
        # cost of four separate cases is wasted setUp).
        emails = [
            ("demo-super@example.com",          UserRole.SUPER_ADMIN),
            ("demo-company-admin@example.com",  UserRole.COMPANY_ADMIN),
            ("demo-manager@example.com",        UserRole.BUILDING_MANAGER),
            ("demo-customer@example.com",       UserRole.CUSTOMER_USER),
        ]
        for email, role in emails:
            User.objects.create_user(
                email=email,
                password="Demo12345!",
                role=role,
            )

        err = StringIO()
        with self.assertRaises(SystemExit) as cm:
            call_command(
                "check_no_demo_accounts",
                stdout=StringIO(),
                stderr=err,
            )
        self.assertEqual(cm.exception.code, 1)
        # All four addresses present in the error output.
        for email, _ in emails:
            self.assertIn(email, err.getvalue())

    def test_soft_deleted_demo_account_still_fails(self):
        # A soft-deleted demo account is still a credential record
        # whose reactivation could ship the public domain into the
        # demo password. The guard must reject it.
        from django.utils import timezone

        u = User.objects.create_user(
            email="demo-super@example.com",
            password="Demo12345!",
            role=UserRole.SUPER_ADMIN,
        )
        u.is_active = False
        u.deleted_at = timezone.now()
        u.save(update_fields=["is_active", "deleted_at"])

        err = StringIO()
        with self.assertRaises(SystemExit) as cm:
            call_command(
                "check_no_demo_accounts",
                stdout=StringIO(),
                stderr=err,
            )
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("demo-super@example.com", err.getvalue())

    def test_non_demo_account_does_not_trigger(self):
        # A real super-admin (not at example.com) must not trigger
        # the guard. The check is by exact email match, not by role.
        User.objects.create_user(
            email="real-admin@cleaning.acme-pilot.test",
            password="ARealStrongPassword#9876",
            role=UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        out = StringIO()
        call_command("check_no_demo_accounts", stdout=out, stderr=StringIO())
        self.assertIn("[OK] no demo accounts found", out.getvalue())

    def test_sprint16_seed_demo_data_account_fails(self):
        # Sprint 16's seed_demo_data writes accounts under the
        # @cleanops.demo TLD. The guard rejects them via the
        # explicit list AND via the domain-suffix safety net.
        User.objects.create_user(
            email="amanda@cleanops.demo",
            password="Demo12345!",
            role=UserRole.CUSTOMER_USER,
        )
        err = StringIO()
        with self.assertRaises(SystemExit) as cm:
            call_command(
                "check_no_demo_accounts",
                stdout=StringIO(),
                stderr=err,
            )
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("amanda@cleanops.demo", err.getvalue())

    def test_unlisted_cleanops_demo_email_still_fails(self):
        # Defence in depth: even if a future demo seed adds a new
        # persona under @cleanops.demo that isn't yet in the
        # explicit DEMO_EMAILS list, the suffix guard catches it.
        User.objects.create_user(
            email="future-tester@cleanops.demo",
            password="Demo12345!",
            role=UserRole.CUSTOMER_USER,
        )
        err = StringIO()
        with self.assertRaises(SystemExit) as cm:
            call_command(
                "check_no_demo_accounts",
                stdout=StringIO(),
                stderr=err,
            )
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("future-tester@cleanops.demo", err.getvalue())
