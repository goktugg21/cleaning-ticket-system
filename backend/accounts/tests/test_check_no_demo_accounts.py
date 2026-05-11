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

    def test_sprint21_company_b_demo_accounts_fail(self):
        # Sprint 21 added a second demo company (Bright Facilities) to
        # seed_demo_data. The three new accounts must each trip the
        # pilot guard. The Sprint 21 v1 names (admin-b/manager-b/
        # customer-b@cleanops.demo) and the Sprint 21 v2 names
        # (sophie-admin-bright/bram-manager-bright/lotte-customer-bright
        # @bright-facilities.demo) are both still rejected.
        for email, role in [
            ("admin-b@cleanops.demo", UserRole.COMPANY_ADMIN),
            ("manager-b@cleanops.demo", UserRole.BUILDING_MANAGER),
            ("customer-b@cleanops.demo", UserRole.CUSTOMER_USER),
            ("sophie-admin-bright@bright-facilities.demo", UserRole.COMPANY_ADMIN),
            ("bram-manager-bright@bright-facilities.demo", UserRole.BUILDING_MANAGER),
            ("lotte-customer-bright@bright-facilities.demo", UserRole.CUSTOMER_USER),
        ]:
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
        for email in (
            "admin-b@cleanops.demo",
            "manager-b@cleanops.demo",
            "customer-b@cleanops.demo",
            "sophie-admin-bright@bright-facilities.demo",
            "bram-manager-bright@bright-facilities.demo",
            "lotte-customer-bright@bright-facilities.demo",
        ):
            self.assertIn(email, err.getvalue())

    def test_sprint21_v2_canonical_accounts_fail(self):
        # Sprint 21 v2 renamed every persona. Each canonical email
        # (super admin + 7 Osius + 3 Bright) must individually trip
        # the pilot guard via the explicit list AND via the new
        # domain-suffix rules for @b-amsterdam.demo and
        # @bright-facilities.demo. We assert one persona from each
        # suffix family to keep the test fast.
        for email, role in [
            ("superadmin@cleanops.demo", UserRole.SUPER_ADMIN),
            ("ramazan-admin-osius@b-amsterdam.demo", UserRole.COMPANY_ADMIN),
            ("amanda-customer-b-amsterdam@b-amsterdam.demo", UserRole.CUSTOMER_USER),
            ("sophie-admin-bright@bright-facilities.demo", UserRole.COMPANY_ADMIN),
            ("lotte-customer-bright@bright-facilities.demo", UserRole.CUSTOMER_USER),
        ]:
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
        for email in (
            "superadmin@cleanops.demo",
            "ramazan-admin-osius@b-amsterdam.demo",
            "amanda-customer-b-amsterdam@b-amsterdam.demo",
            "sophie-admin-bright@bright-facilities.demo",
            "lotte-customer-bright@bright-facilities.demo",
        ):
            self.assertIn(email, err.getvalue())

    def test_unlisted_b_amsterdam_demo_email_still_fails(self):
        # Defence in depth for the new @b-amsterdam.demo TLD.
        User.objects.create_user(
            email="future-tester@b-amsterdam.demo",
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
        self.assertIn("future-tester@b-amsterdam.demo", err.getvalue())

    def test_unlisted_bright_facilities_demo_email_still_fails(self):
        # Defence in depth for the new @bright-facilities.demo TLD.
        User.objects.create_user(
            email="future-tester@bright-facilities.demo",
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
        self.assertIn("future-tester@bright-facilities.demo", err.getvalue())

    def test_sprint19_demo_up_script_accounts_fail(self):
        # Sprint 19's pilot-readiness gate extended DEMO_EMAILS to
        # also reject the four accounts that scripts/demo_up.sh and
        # scripts/prod_upload_download_test.sh seed with the
        # well-known passwords Admin12345! / Test12345!. Before this
        # entry, an operator who ran demo_up.sh against the pilot DB
        # by accident would still pass the launch gate.
        for email, role in [
            ("admin@example.com", UserRole.SUPER_ADMIN),
            ("companyadmin@example.com", UserRole.COMPANY_ADMIN),
            ("manager@example.com", UserRole.BUILDING_MANAGER),
            ("customer@example.com", UserRole.CUSTOMER_USER),
        ]:
            User.objects.create_user(
                email=email,
                password="Test12345!",
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
        for email in (
            "admin@example.com",
            "companyadmin@example.com",
            "manager@example.com",
            "customer@example.com",
        ):
            self.assertIn(email, err.getvalue())
