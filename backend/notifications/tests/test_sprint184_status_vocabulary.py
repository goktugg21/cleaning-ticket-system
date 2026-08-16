"""
Sprint 184 §1 — one status, one word, in email as well as on screen.

The customer sees a ticket status in two places without opening a
ticket: the notification email and the reports chart. Neither went
through the vocabulary the screens were fixed to use, so email said
"Goedgekeurd" where the app says "Werk akkoord", "Wacht op goedkeuring"
where the app says "Wacht op klant", and "Wacht op controle beheerder"
where the app says "Wacht op beheerder".

Two tests, because the failure had two halves:

  * `test_every_ticket_status_has_a_dutch_word` runs EVERYWHERE and
    catches the MISSING half. `CONVERTED_TO_EXTRA_WORK` was absent and
    the fallback printed the raw code, so a customer could be emailed
    the literal string `CONVERTED_TO_EXTRA_WORK`.
  * `test_the_email_words_match_the_screen_words` catches the DIVERGED
    half by reading the frontend bundle. It can only run where the whole
    repo is checked out — which is CI (`.github/workflows/test.yml` runs
    `manage.py test` from `backend/` after `actions/checkout`), and is
    NOT the case inside the backend container, whose image is built from
    `backend/` alone. It skips there, loudly, rather than passing
    vacuously.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.test import SimpleTestCase

from notifications.status_labels import (
    STATUS_I18N_KEY,
    TICKET_STATUS_LABEL_NL,
    UNKNOWN_STATUS_LABEL_NL,
    ticket_status_label_nl,
)
from tickets.models import TicketStatus

# backend/notifications/tests/ -> backend/notifications -> backend -> repo
_REPO_ROOT = Path(__file__).resolve().parents[3]
_NL_COMMON = _REPO_ROOT / "frontend" / "src" / "i18n" / "nl" / "common.json"


class TicketStatusVocabularyTests(SimpleTestCase):
    def test_every_ticket_status_has_a_dutch_word(self):
        """The half that let a raw enum reach a customer's inbox."""
        missing = [
            value
            for value in TicketStatus.values
            if TicketStatus(value) not in TICKET_STATUS_LABEL_NL
        ]
        self.assertEqual(
            missing,
            [],
            "notifications/status_labels.py has no Dutch word for "
            f"{missing}. Add it there AND in frontend/src/i18n/nl/"
            "common.json, or a customer will be emailed the raw code.",
        )

    def test_every_status_also_has_an_i18n_key(self):
        """The two maps are read together by the divergence test below;
        one of them growing alone would make that test silently skip a
        status rather than fail."""
        self.assertEqual(
            sorted(str(k) for k in TICKET_STATUS_LABEL_NL),
            sorted(str(k) for k in STATUS_I18N_KEY),
        )

    def test_no_status_renders_as_its_own_code(self):
        """A word that is just the enum member is not a word."""
        for value, label in TICKET_STATUS_LABEL_NL.items():
            with self.subTest(status=value):
                self.assertNotEqual(label, str(value))
                self.assertEqual(ticket_status_label_nl(value), label)

    def test_an_unknown_value_is_a_sentence_not_a_code(self):
        self.assertEqual(
            ticket_status_label_nl("NOT_A_STATUS"), UNKNOWN_STATUS_LABEL_NL
        )
        self.assertEqual(ticket_status_label_nl(None), UNKNOWN_STATUS_LABEL_NL)

    def test_the_email_words_match_the_screen_words(self):
        """The half that let three words drift.

        Byte-identical, not "close enough": the whole complaint is that
        one status must read ONE way, and a near-match is what the last
        three sprints kept finding.
        """
        if not _NL_COMMON.exists():
            self.skipTest(
                f"{_NL_COMMON} is not on disk. The backend image is built "
                "from backend/ alone, so this comparison runs in CI (whole "
                "repo checked out) and not inside the container."
            )
        bundle = json.loads(_NL_COMMON.read_text(encoding="utf-8"))
        for status, key in STATUS_I18N_KEY.items():
            with self.subTest(status=str(status), key=key):
                self.assertIn(
                    key,
                    bundle,
                    f"{key} is gone from the nl bundle; "
                    "notifications/status_labels.py still spells "
                    f"{status} with it.",
                )
                self.assertEqual(
                    TICKET_STATUS_LABEL_NL[status],
                    bundle[key],
                    "The email and the screen disagree about "
                    f"{status}. Screen says {bundle[key]!r}, email says "
                    f"{TICKET_STATUS_LABEL_NL[status]!r}. Edit the bundle "
                    "first, then notifications/status_labels.py.",
                )


class StatusLabelRenderingTests(SimpleTestCase):
    """The three words the owner named, pinned by value.

    Deliberately literal. The test above proves the two lists agree; this
    one proves WHAT they agree on, so a bulk edit that changed both sides
    to something wrong still fails.
    """

    def test_approved_says_the_work_was_accepted(self):
        self.assertEqual(
            ticket_status_label_nl(TicketStatus.APPROVED), "Werk akkoord"
        )

    def test_waiting_customer_approval_names_the_customer(self):
        self.assertEqual(
            ticket_status_label_nl(TicketStatus.WAITING_CUSTOMER_APPROVAL),
            "Wacht op klant",
        )

    def test_waiting_manager_review_names_the_manager(self):
        self.assertEqual(
            ticket_status_label_nl(TicketStatus.WAITING_MANAGER_REVIEW),
            "Wacht op beheerder",
        )

    def test_converted_to_extra_work_is_a_sentence(self):
        self.assertEqual(
            ticket_status_label_nl(TicketStatus.CONVERTED_TO_EXTRA_WORK),
            "Geconverteerd naar meerwerk",
        )
