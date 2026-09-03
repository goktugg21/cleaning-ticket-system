"""P-16 Part D — the notification copy catalogue (§D.13.3).

Four pins:

1. EVERY catalogue kind renders in BOTH languages — a key with a Dutch
   half and no English half (or the reverse) fails here, not in a
   customer's inbox. This is where the fifteen per-site copy tests'
   completeness duty now lives; the per-site tests keep pinning the
   Dutch bytes.
2. The status label maps (nl AND en) cover every TicketStatus and are
   byte-identical to the frontend bundles where the repo is checked out
   whole (the Sprint 184 technique, extended to English).
3. ONE event, two languages: a Dutch recipient and an English recipient
   of the same event each get their own language in the MAIL (rendered
   at send, stored verbatim), and the BELL re-renders per viewer at
   read time — the Dutch recipient who switches to English sees their
   old row switch too. The API resolves it; the SPA composes nothing.
4. Old rows keep printing their stored text: a row without a
   `template_key` is served exactly as stored, and the warning `title`
   the frontend used to translate client-side arrives resolved.
"""
import json
from pathlib import Path

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from notifications import copy as notification_copy
from notifications.copy import CATALOGUE, render_email, render_summary, title_for_event
from notifications.models import (
    Notification,
    NotificationLog,
    NotificationType,
)
from notifications.services import (
    emit_sla_warning_inapp,
    send_ticket_status_changed_email,
)
from notifications.status_labels import (
    TICKET_STATUS_LABEL_EN,
    TICKET_STATUS_LABEL_NL,
    ticket_status_label,
)
from test_utils import TenantFixtureMixin
from tickets.models import TicketStatus

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EN_COMMON = _REPO_ROOT / "frontend" / "src" / "i18n" / "en" / "common.json"

LIST_URL = "/api/notifications/"

#: Representative params: one superset every template can format from.
#: Values are realistic so a rendered sentence is a real sentence.
_SAMPLE_PARAMS = {
    "ticket_no": "TCK-2026-000001",
    "ticket_title": "Lamp kapot in de hal",
    "status": str(TicketStatus.OPEN),
    "old_status": str(TicketStatus.OPEN),
    "new_status": str(TicketStatus.WAITING_CUSTOMER_APPROVAL),
    "priority": "NORMAL",
    "type": "REPORT",
    "company_name": "Company A",
    "building_name": "Building A",
    "customer_name": "Customer A",
    "room_label": "Hal",
    "assigned_to_email": "worker@example.com",
    "description": "De lamp doet het niet.",
    "actor_label": "admin@example.com",
    "approved": True,
    "with_billing_cutoff": True,
    "staff_label": "Ahmet",
    "window": "2026-09-04 08:00",
    "reason": "Sleutel ontbrak",
    "uid": "abc",
    "token": "tok",
    "reset_url": "https://example.com/reset",
    "inviter_label": "Admin A",
    "role": "BUILDING_MANAGER",
    "company_names": ["Company A"],
    "building_names": ["Building A"],
    "customer_names": ["Customer A"],
    "expires_label": "2026-09-10 12:00 CEST",
    "accept_url": "https://example.com/accept",
    "number": "2026-0001",
    "total": "121.00",
    "contact_name": "Jan",
    "count": 2,
    "rows": [
        {
            "ref": 7,
            "level": "customer",
            "amount": "100.00",
            "event_type": "SLA_WORK_NOT_STARTED",
            "when": "01-09 08:00",
            "subject": "[TCK-1] Nog niet gestart",
            "recipient": "admin@example.com",
        }
    ],
    "month": "2026-09",
    "groups": [
        {
            "customer_name": "Customer A",
            "rows": [
                {
                    "ref": "TCK-2026-000001",
                    "title": "Lamp kapot",
                    "building_name": "Building A",
                    "stage": "BLOCKED",
                    "age_days": 3,
                }
            ],
        }
    ],
    "cutoff_iso": "2026-09-20",
    "days_left": 3,
    "hours": 9,
    "planned_label": "04-09-2026 08:00",
    "planned_iso": "2026-09-04",
    "ew_title": "Zonwering reinigen",
    "ew_ref": "Meerwerk #12",
    "since_iso": "2026-08-27",
    "until_iso": "2026-09-03",
    "label": "TCK-2026-000001",
    "deadline_iso": "2026-08-20",
    "deadline_days_late": 6,
    "anchor_iso": "2026-08-20",
    "anchor_days": 30,
    "anchored_on_deadline": True,
    "part_title": "Ramen west",
    "author": "Tom",
    "text": "Graag morgen",
    "title": "Zonwering reinigen",
    "decider": "Tom Verbeek",
}


class CatalogueCompletenessTests(SimpleTestCase):
    def test_every_kind_renders_in_both_languages(self):
        for key, entry in CATALOGUE.items():
            has_email = "subject" in entry or "body" in entry
            for lang in ("nl", "en"):
                with self.subTest(key=key, lang=lang):
                    if has_email:
                        subject, body = render_email(key, _SAMPLE_PARAMS, lang)
                        self.assertTrue(
                            subject.strip(),
                            f"{key} renders an empty {lang} subject",
                        )
                        self.assertTrue(
                            body.strip(),
                            f"{key} renders an empty {lang} body",
                        )
                    if "summary" in entry:
                        summary = render_summary(key, _SAMPLE_PARAMS, lang)
                        self.assertTrue(
                            summary and summary.strip(),
                            f"{key} renders an empty {lang} summary",
                        )

    def test_an_email_kind_has_both_subject_and_body(self):
        for key, entry in CATALOGUE.items():
            with self.subTest(key=key):
                self.assertEqual(
                    "subject" in entry,
                    "body" in entry,
                    f"{key} has a subject without a body (or the reverse) "
                    "— an email kind carries both.",
                )

    def test_rendering_never_raises_on_missing_params(self):
        """An old row's params may predate a template's newest
        placeholder; the render degrades to blanks, never to a 500."""
        for key, entry in CATALOGUE.items():
            with self.subTest(key=key):
                if "summary" in entry:
                    render_summary(key, {}, "nl")
                    render_summary(key, {}, "en")
                if "subject" in entry:
                    render_email(key, {}, "nl")
                    render_email(key, {}, "en")

    def test_unknown_key_returns_none_for_summary(self):
        self.assertIsNone(render_summary("no_such_kind", {}, "nl"))

    def test_the_six_warning_titles_resolve_in_both_languages(self):
        for event_type in (
            "SLA_APPROVAL_CUTOFF_DUE",
            "SLA_MANAGER_REVIEW_OVERDUE",
            "SLA_WORK_NOT_STARTED",
            "TICKET_LATE_L2_MANAGERS",
            "TICKET_LATE_L2_ESCALATED",
            "TICKET_LATE_L3_QUARANTINE",
        ):
            for lang in ("nl", "en"):
                with self.subTest(event_type=event_type, lang=lang):
                    self.assertTrue(title_for_event(event_type, lang))
        self.assertIsNone(title_for_event("TICKET_MESSAGE", "nl"))


class EnglishStatusVocabularyTests(SimpleTestCase):
    """The Sprint 184 lockstep duty, extended to the English mirror."""

    def test_every_ticket_status_has_an_english_word(self):
        missing = [
            value
            for value in TicketStatus.values
            if TicketStatus(value) not in TICKET_STATUS_LABEL_EN
        ]
        self.assertEqual(
            missing,
            [],
            "notifications/status_labels.py has no English word for "
            f"{missing}. Add it there AND in frontend/src/i18n/en/"
            "common.json, or an English reader gets the raw code.",
        )

    def test_the_two_maps_cover_the_same_statuses(self):
        self.assertEqual(
            sorted(str(k) for k in TICKET_STATUS_LABEL_EN),
            sorted(str(k) for k in TICKET_STATUS_LABEL_NL),
        )

    def test_the_resolver_answers_both_languages(self):
        self.assertEqual(
            ticket_status_label(TicketStatus.APPROVED, "nl"), "Werk akkoord"
        )
        self.assertEqual(
            ticket_status_label(TicketStatus.APPROVED, "en"), "Work approved"
        )
        self.assertEqual(ticket_status_label("NOPE", "en"), "Unknown status")

    def test_the_english_words_match_the_screen_words(self):
        if not _EN_COMMON.exists():
            self.skipTest(
                f"{_EN_COMMON} is not on disk. The backend image is built "
                "from backend/ alone; this comparison runs where the whole "
                "repo is checked out."
            )
        from notifications.status_labels import STATUS_I18N_KEY

        bundle = json.loads(_EN_COMMON.read_text(encoding="utf-8"))
        for status, key in STATUS_I18N_KEY.items():
            with self.subTest(status=str(status), key=key):
                self.assertIn(key, bundle)
                self.assertEqual(
                    TICKET_STATUS_LABEL_EN[status],
                    bundle[key],
                    f"{key}: backend and en bundle disagree — edit the "
                    "bundle first, notifications/status_labels.py second.",
                )


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class OneEventTwoLanguagesTests(TenantFixtureMixin, APITestCase):
    """The §D.13.3 proof fixture: a Dutch recipient and an English
    recipient on ONE event — the mail lands in each inbox in its own
    language, and the bell re-renders per viewer at read time."""

    def setUp(self):
        super().setUp()
        # A second manager on the same building, reading English.
        from buildings.models import BuildingManagerAssignment

        self.en_manager = self.make_user(
            "manager-en@example.com",
            self.manager.role,
            language="en",
        )
        BuildingManagerAssignment.objects.create(
            user=self.en_manager, building=self.building
        )
        self.manager.language = "nl"
        self.manager.save(update_fields=["language"])

    def test_the_mail_lands_in_each_recipients_own_language(self):
        send_ticket_status_changed_email(
            self.ticket,
            old_status="OPEN",
            new_status="IN_PROGRESS",
            actor=self.customer_user,
        )
        nl_log = NotificationLog.objects.get(recipient_user=self.manager)
        en_log = NotificationLog.objects.get(recipient_user=self.en_manager)
        self.assertIn("Status gewijzigd", nl_log.subject)
        self.assertIn("In behandeling", nl_log.subject)
        self.assertIn("Status changed", en_log.subject)
        self.assertIn("In progress", en_log.subject)
        self.assertIn("De status van een ticket is gewijzigd.", nl_log.body)
        self.assertIn("The status of a ticket has changed.", en_log.body)
        # Both carry the same key and the same facts — the audit record
        # is the rendered text; the machine's copy is the params.
        self.assertEqual(nl_log.template_key, "ticket_status_changed")
        self.assertEqual(nl_log.template_key, en_log.template_key)
        self.assertEqual(nl_log.params, en_log.params)

    def test_the_bell_renders_at_read_time_in_the_viewers_language(self):
        rows = emit_sla_warning_inapp(
            event_type=NotificationType.SLA_MANAGER_REVIEW_OVERDUE,
            recipients=[self.manager, self.en_manager],
            template_key="sla_manager_review",
            params={
                "ticket_no": self.ticket.ticket_no,
                "ticket_title": self.ticket.title,
                "hours": 9,
            },
            ticket=self.ticket,
        )
        self.assertEqual(len(rows), 2)
        by_recipient = {row.recipient_id: row for row in rows}
        # The stored cache is each recipient's own language at emit time.
        self.assertIn("9 werkuren", by_recipient[self.manager.id].summary)
        self.assertIn(
            "9 working hours", by_recipient[self.en_manager.id].summary
        )

        # The Dutch recipient reads their feed: Dutch summary, Dutch title.
        self.authenticate(self.manager)
        [row] = self.client.get(LIST_URL).data["results"]
        self.assertIn("9 werkuren", row["summary"])
        self.assertEqual(row["title"], "Wacht te lang op controle")

        # The same person switches to English: the SAME row re-renders.
        self.manager.language = "en"
        self.manager.save(update_fields=["language"])
        [row] = self.client.get(LIST_URL).data["results"]
        self.assertIn("9 working hours", row["summary"])
        self.assertEqual(row["title"], "Waiting too long for review")

    def test_an_old_row_without_a_key_prints_its_stored_text(self):
        Notification.objects.create(
            recipient=self.manager,
            actor=None,
            event_type=NotificationType.SLA_WORK_NOT_STARTED,
            ticket=self.ticket,
            summary="Ticket A - 9 werkuren",
        )
        self.manager.language = "en"
        self.manager.save(update_fields=["language"])
        self.authenticate(self.manager)
        [row] = self.client.get(LIST_URL).data["results"]
        # No key: the stored text is served untouched, whatever the
        # viewer's language...
        self.assertEqual(row["summary"], "Ticket A - 9 werkuren")
        # ...while the TITLE still arrives resolved, because it keys on
        # the event type — legacy warning rows keep their headline too.
        self.assertEqual(row["title"], "Not started yet")

    def test_a_broken_params_payload_falls_back_to_the_cache(self):
        Notification.objects.create(
            recipient=self.manager,
            actor=None,
            event_type=NotificationType.SLA_WORK_NOT_STARTED,
            ticket=self.ticket,
            summary="de bewaarde tekst",
            template_key="no_such_kind",
            params={"whatever": 1},
        )
        self.authenticate(self.manager)
        [row] = self.client.get(LIST_URL).data["results"]
        self.assertEqual(row["summary"], "de bewaarde tekst")


class EmitPathKeysTests(TenantFixtureMixin, APITestCase):
    """Every rewired bell emit stamps its key + params on the row."""

    def test_the_message_emit_stamps_key_and_params(self):
        from notifications.services import emit_ticket_message_notifications
        from tickets.models import TicketMessage, TicketMessageType

        message = TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.customer_user,
            message="Graag morgen komen kijken",
            message_type=TicketMessageType.PUBLIC_REPLY,
        )
        rows = emit_ticket_message_notifications(message, actor=self.customer_user)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row.template_key, "ticket_message")
            self.assertEqual(
                row.params["text"], "Graag morgen komen kijken"
            )
            self.assertNotIn("id", row.params)
