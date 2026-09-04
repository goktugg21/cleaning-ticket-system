"""W-LATE addendum 2 — the severity on the notification itself."""
from __future__ import annotations

from rest_framework.test import APITestCase

from notifications.models import (
    LATE_ESCALATION_INAPP_TYPES,
    Notification,
    NotificationEventType,
    NotificationPreference,
    NotificationSeverity,
    NotificationType,
)
from notifications.services import emit_escalation_inapp, emit_sla_warning_inapp
from test_utils import TenantFixtureMixin


class SeverityOnTheRowTests(TenantFixtureMixin, APITestCase):
    def test_the_feed_carries_the_severity(self):
        Notification.objects.create(
            recipient=self.manager,
            event_type=NotificationType.TICKET_LATE_L2_MANAGERS,
            ticket=self.ticket,
            summary="Zonwering — TCK: deadline 20 aug is 6 dagen overschreden",
            severity=NotificationSeverity.L2,
        )
        self.authenticate(self.manager)
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, 200, response.data)
        [row] = response.data["results"]
        self.assertEqual(row["severity"], "L2")
        self.assertEqual(row["event_type"], "TICKET_LATE_L2_MANAGERS")
        self.assertEqual(row["ticket"], self.ticket.id)

    def test_activity_rows_are_info_by_default(self):
        row = Notification.objects.create(
            recipient=self.manager,
            event_type=NotificationType.TICKET_MESSAGE,
            ticket=self.ticket,
            summary="hello",
        )
        self.assertEqual(row.severity, NotificationSeverity.INFO)

    def test_a_time_driven_warning_is_l1_unless_told_otherwise(self):
        [row] = emit_sla_warning_inapp(
            event_type=NotificationType.SLA_WORK_NOT_STARTED,
            recipients=[self.manager],
            summary="x",
            ticket=self.ticket,
        )
        self.assertEqual(
            Notification.objects.get(pk=row.pk).severity, NotificationSeverity.L1
        )

    def test_an_escalation_carries_its_rung_and_speaks_per_reader(self):
        self.company_admin.language = "en"
        self.company_admin.save(update_fields=["language"])
        rows = emit_escalation_inapp(
            event_type=NotificationType.TICKET_LATE_L3_NEVER_DONE,
            recipients=[self.manager, self.company_admin],
            summary_for=lambda user: "EN" if user.language == "en" else "NL",
            severity=NotificationSeverity.L3,
            ticket=self.ticket,
        )
        by_user = {r.recipient_id: r for r in Notification.objects.filter(pk__in=[r.pk for r in rows])}
        self.assertEqual(by_user[self.manager.id].summary, "NL")
        self.assertEqual(by_user[self.company_admin.id].summary, "EN")
        self.assertEqual(by_user[self.manager.id].severity, NotificationSeverity.L3)
        self.assertFalse(by_user[self.manager.id].is_directed)
        self.assertIsNone(by_user[self.manager.id].actor_id)


class TheStepsAreNotMutableTests(TenantFixtureMixin, APITestCase):
    """A mute switch on a warning silences the one message whose whole
    purpose is to arrive unasked — the same invariant the SLA three
    already pin."""

    def test_no_escalation_type_is_user_mutable(self):
        mutable = set(NotificationPreference.USER_MUTABLE_EVENT_TYPES) | set(
            NotificationPreference.USER_MUTABLE_INAPP_EVENT_TYPES
        )
        for value in LATE_ESCALATION_INAPP_TYPES:
            self.assertNotIn(value, mutable, value)

    def test_the_two_enums_spell_the_steps_identically(self):
        for name in (
            "TICKET_LATE_L2_MANAGERS",
            "TICKET_LATE_L2_ESCALATED",
            "TICKET_LATE_L3_NEVER_DONE",
        ):
            self.assertEqual(
                getattr(NotificationEventType, name).value,
                getattr(NotificationType, name).value,
            )

    def test_the_never_done_rung_kept_its_stored_spelling(self):
        """W-PLANTRUTH §1c renamed the RUNG, not the DATA.

        Everything a reader sees says "never done" / "nooit uitgevoerd",
        and the Python attribute says so too. The stored value does not:
        changing a `TextChoices` value is a schema migration and a
        rewrite of every row already written under the old spelling, and
        this wave ships neither. So the value stays `..._L3_QUARANTINE`
        forever, and this test is the reason it looks inconsistent.
        """
        self.assertEqual(
            NotificationType.TICKET_LATE_L3_NEVER_DONE.value,
            "TICKET_LATE_L3_QUARANTINE",
        )
        self.assertEqual(
            NotificationEventType.TICKET_LATE_L3_NEVER_DONE.value,
            "TICKET_LATE_L3_QUARANTINE",
        )
