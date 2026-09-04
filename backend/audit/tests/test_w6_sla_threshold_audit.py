"""
W6 §2 — AuditLog coverage for the per-company SLA warning thresholds.

W4-Q built `SlaWarningThreshold` and the admin screen that edits it, and
could not register the model in `audit/signals.py` because another chat
held that file for the sprint. This module is the test half of closing
that gap.

WHY THIS MODEL NEEDS AUDITING AT ALL. The row does not describe work; it
describes WHO gets warned and WHEN. Widening `cooldown_hours`, or pushing
`manager_review_business_hours` out, makes warnings arrive later or stop
arriving — and the symptom ("nobody told us the approval was overdue")
surfaces weeks after the edit that caused it. Without the diff below, the
only honest answer to "why did the warnings stop" is a guess. That is
what RBAC invariant H-10 is for: every permission / role / scope change
writes an AuditLog, and a threshold is the schedule on which a scope gets
told things.

All three arms are exercised because all three are reachable from the one
HTTP surface (`PUT` and `DELETE` on
`/api/sla/warning-thresholds/<company_id>/`):

  * the FIRST PUT is a CREATE — the company leaving the deployment
    defaults;
  * a later PUT is an UPDATE, and its `changes` payload is the point of
    the whole exercise;
  * DELETE resets the company to the deployment defaults, which is a
    silent behaviour change unless the row is written.

The DELETE arm is worth its own assertion for a Django-specific reason:
the view deletes through `filter(...).delete()`. A QuerySet `.delete()`
does fire `post_delete` per object (unlike `.update()`, which fires
nothing) — so this test also pins the fact that the view is not using the
signal-free path.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from audit.models import AuditAction, AuditLog
from companies.models import Company, CompanyUserMembership
from sla.models import SlaWarningThreshold


User = get_user_model()
PASSWORD = "StrongerTestPasswordW6!"
LABEL = "sla.SlaWarningThreshold"


class SlaWarningThresholdAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-w6-audit")
        cls.admin = User.objects.create_user(
            email="ca-w6-audit@example.com",
            password=PASSWORD,
            role="COMPANY_ADMIN",
            full_name="Company Admin",
        )
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )

    def api(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client

    def url(self):
        return f"/api/sla/warning-thresholds/{self.company.id}/"

    def logs(self, action=None):
        qs = AuditLog.objects.filter(target_model=LABEL)
        if action is not None:
            qs = qs.filter(action=action)
        return list(qs.order_by("id"))

    def test_first_put_writes_a_create_log_with_the_actor(self):
        response = self.api().put(
            self.url(), {"cooldown_hours": 24}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)

        row = SlaWarningThreshold.objects.get(company=self.company)
        created = self.logs(AuditAction.CREATE)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].target_id, row.id)
        # The actor is the whole point: an unattributable threshold
        # change is the gap this closes.
        self.assertEqual(created[0].actor_id, self.admin.id)

    def test_edit_writes_an_update_log_carrying_before_and_after(self):
        client = self.api()
        client.put(self.url(), {"cooldown_hours": 24}, format="json")
        response = client.put(
            self.url(), {"cooldown_hours": 72}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)

        updates = self.logs(AuditAction.UPDATE)
        self.assertEqual(len(updates), 1)
        changes = updates[0].changes
        self.assertIn("cooldown_hours", changes)
        # Both halves. "It changed" is not attributable; "24 to 72" is.
        self.assertEqual(changes["cooldown_hours"]["before"], 24)
        self.assertEqual(changes["cooldown_hours"]["after"], 72)
        self.assertEqual(updates[0].actor_id, self.admin.id)

    def test_update_diff_is_not_drowned_in_auto_now_noise(self):
        """`updated_at` changes on every save and must never be a change.

        The model carries `auto_now`, so without `diff.NOISY_FIELDS`
        every no-op save would log a timestamp diff and the real edits
        would be needles in it. Pinned here rather than assumed.
        """
        client = self.api()
        client.put(self.url(), {"cooldown_hours": 24}, format="json")
        client.put(
            self.url(),
            {"cooldown_hours": 24, "manager_review_business_hours": 8},
            format="json",
        )
        updates = self.logs(AuditAction.UPDATE)
        self.assertEqual(len(updates), 1)
        changes = updates[0].changes
        self.assertNotIn("updated_at", changes)
        # The field that really moved is there, and the one that did not
        # is not.
        self.assertEqual(changes["manager_review_business_hours"]["after"], 8)
        self.assertNotIn("cooldown_hours", changes)

    def test_reset_to_defaults_writes_a_delete_log(self):
        client = self.api()
        client.put(self.url(), {"cooldown_hours": 24}, format="json")
        row_id = SlaWarningThreshold.objects.get(company=self.company).id

        response = client.delete(self.url())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(
            SlaWarningThreshold.objects.filter(company=self.company).exists()
        )

        deleted = self.logs(AuditAction.DELETE)
        self.assertEqual(len(deleted), 1)
        self.assertEqual(deleted[0].target_id, row_id)
        self.assertEqual(deleted[0].actor_id, self.admin.id)
