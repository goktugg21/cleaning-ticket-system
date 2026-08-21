"""W-H §1/§2 — the ticket archive: one act, server-enforced, excluded by default.

The rules under test are the ones the browser must not be trusted with:
who may archive, that only finished work may be archived, that taking a
ticket back out needs a reason, and that the working list stops showing
archived rows without anybody asking it to.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from audit.models import AuditAction, AuditLog
from tickets.models import Ticket, TicketStatus
from test_utils import TenantFixtureMixin

LIST_URL = "/api/tickets/"
STATS_URL = "/api/tickets/stats/"


def archive_url(ticket_id):
    return f"/api/tickets/{ticket_id}/archive/"


def unarchive_url(ticket_id):
    return f"/api/tickets/{ticket_id}/unarchive/"


class ArchiveActionTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            title="Finished job",
            description="d",
            status=TicketStatus.CLOSED,
            created_by=self.company_admin,
        )

    def test_provider_admin_archives_and_the_row_records_who_and_when(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            archive_url(self.ticket.id), {"note": "Season closed"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.archived_at)
        self.assertEqual(self.ticket.archived_by, self.company_admin)
        self.assertEqual(self.ticket.archive_note, "Season closed")

    def test_the_note_is_optional(self):
        self.authenticate(self.company_admin)
        response = self.client.post(archive_url(self.ticket.id), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.archived_at)
        self.assertEqual(self.ticket.archive_note, "")

    def test_live_work_cannot_be_archived(self):
        """The whole point of the rule: filing live work away loses it."""
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status"])
        self.authenticate(self.company_admin)
        response = self.client.post(archive_url(self.ticket.id), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "archive_not_finished")
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.archived_at)

    def test_archiving_twice_is_refused(self):
        self.authenticate(self.company_admin)
        self.client.post(archive_url(self.ticket.id), {}, format="json")
        again = self.client.post(archive_url(self.ticket.id), {}, format="json")
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(again.data["code"], "already_archived")

    def test_staff_may_not_archive(self):
        staff = self.make_user("staff-wh@example.com", UserRole.STAFF)
        self.authenticate(staff)
        response = self.client.post(archive_url(self.ticket.id), {}, format="json")
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.archived_at)

    def test_customer_may_not_archive(self):
        self.authenticate(self.customer_user)
        response = self.client.post(archive_url(self.ticket.id), {}, format="json")
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.archived_at)


class UnarchiveTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            title="Filed away",
            description="d",
            status=TicketStatus.CLOSED,
            created_by=self.company_admin,
            archived_at=timezone.now(),
            archived_by=self.company_admin,
            archive_note="n",
        )

    def test_a_reason_is_required(self):
        self.authenticate(self.company_admin)
        response = self.client.post(unarchive_url(self.ticket.id), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "unarchive_reason_required")
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.archived_at)

    def test_a_blank_reason_is_not_a_reason(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            unarchive_url(self.ticket.id), {"reason": "   "}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "unarchive_reason_required")

    def test_with_a_reason_it_comes_back_and_the_reason_is_on_the_audit_row(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            unarchive_url(self.ticket.id),
            {"reason": "Customer disputes the invoice"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.archived_at)
        self.assertIsNone(self.ticket.archived_by)
        row = (
            AuditLog.objects.filter(
                target_model="tickets.Ticket",
                target_id=self.ticket.id,
                action=AuditAction.UPDATE,
            )
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.reason, "Customer disputes the invoice")
        self.assertIn("archived_at", row.changes)


class ArchiveAuditTests(TenantFixtureMixin, APITestCase):
    """CLAUDE.md: a new tracked field needs a test in the audit suite's
    shape. Ticket is NOT in the generic CRUD trio, so these three fields
    are the only Ticket columns that ever reach the AuditLog."""

    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            title="T",
            description="d",
            status=TicketStatus.CLOSED,
            created_by=self.company_admin,
        )

    def test_archiving_writes_one_audit_row_with_before_and_after(self):
        self.authenticate(self.company_admin)
        before = AuditLog.objects.filter(target_model="tickets.Ticket").count()
        self.client.post(archive_url(self.ticket.id), {"note": "x"}, format="json")
        rows = AuditLog.objects.filter(
            target_model="tickets.Ticket", target_id=self.ticket.id
        )
        self.assertEqual(rows.count() - before, 1)
        changes = rows.order_by("-id").first().changes
        self.assertIn("archived_at", changes)
        self.assertIsNone(changes["archived_at"]["before"])
        self.assertIsNotNone(changes["archived_at"]["after"])

    def test_an_ordinary_ticket_edit_still_writes_nothing(self):
        """The handler is archive-fields-only on purpose: Ticket's trail
        is TicketStatusHistory (H-11) and must not be doubled."""
        before = AuditLog.objects.filter(target_model="tickets.Ticket").count()
        self.ticket.title = "Renamed"
        self.ticket.save(update_fields=["title"])
        after = AuditLog.objects.filter(target_model="tickets.Ticket").count()
        self.assertEqual(before, after)


class ArchiveExcludedByDefaultTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        common = dict(
            company=self.company,
            building=self.building,
            customer=self.customer,
            description="d",
            created_by=self.company_admin,
        )
        self.live = Ticket.objects.create(
            title="Live", status=TicketStatus.OPEN, **common
        )
        self.filed = Ticket.objects.create(
            title="Filed",
            status=TicketStatus.CLOSED,
            archived_at=timezone.now(),
            archived_by=self.company_admin,
            **common,
        )

    def _titles(self, params=None):
        self.authenticate(self.company_admin)
        response = self.client.get(LIST_URL, params or {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {row["title"] for row in response.data["results"]}

    def test_the_working_list_does_not_load_the_archive(self):
        titles = self._titles()
        self.assertIn("Live", titles)
        self.assertNotIn("Filed", titles)

    def test_archived_true_shows_only_the_archive(self):
        titles = self._titles({"archived": "true"})
        self.assertEqual(titles, {"Filed"})

    def test_archived_false_is_the_default_said_out_loud(self):
        titles = self._titles({"archived": "false"})
        self.assertIn("Live", titles)
        self.assertNotIn("Filed", titles)

    def test_the_chips_count_the_rows_beneath_them(self):
        """A chip counting the archive above a list that hides it is the
        defect Sprint 180/183 fixed twice for other filters."""
        self.authenticate(self.company_admin)
        working = self.client.get(STATS_URL)
        archive = self.client.get(STATS_URL, {"archived": "true"})
        self.assertEqual(working.status_code, status.HTTP_200_OK)
        self.assertEqual(archive.status_code, status.HTTP_200_OK)
        self.assertNotEqual(working.data["total"], archive.data["total"])
        self.assertEqual(archive.data["total"], 1)


class PeriodFilterTests(TenantFixtureMixin, APITestCase):
    """W-H §3 — one period vocabulary, resolved to two dates by the
    client and applied to the ticket's own `created_at`."""

    def setUp(self):
        super().setUp()
        common = dict(
            company=self.company,
            building=self.building,
            customer=self.customer,
            description="d",
            created_by=self.company_admin,
            status=TicketStatus.OPEN,
        )
        self.old = Ticket.objects.create(title="Old", **common)
        Ticket.objects.filter(pk=self.old.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=400)
        )
        self.recent = Ticket.objects.create(title="Recent", **common)

    def _titles(self, params):
        self.authenticate(self.company_admin)
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {row["title"] for row in response.data["results"]}

    def test_date_from_drops_older_rows(self):
        cutoff = (timezone.now() - timezone.timedelta(days=30)).date().isoformat()
        titles = self._titles({"date_from": cutoff})
        self.assertIn("Recent", titles)
        self.assertNotIn("Old", titles)

    def test_date_to_is_inclusive_of_the_whole_last_day(self):
        """`created_at` is a datetime; a `lte` on the raw value would
        drop everything after midnight on the closing day."""
        today = timezone.now().date().isoformat()
        titles = self._titles({"date_to": today})
        self.assertIn("Recent", titles)

    def test_a_window_that_excludes_everything_returns_nothing(self):
        titles = self._titles(
            {"date_from": "2000-01-01", "date_to": "2000-12-31"}
        )
        self.assertEqual(titles, set())
