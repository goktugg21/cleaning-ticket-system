"""
#109 Part D — SUPER_ADMIN per-company notification subscriptions
(in-app only) + the SA-only ?company= view-as feed mode.

Locked contracts:
  * subscribe -> the next emitted provider-management event of that
    company creates an SA-recipient Notification row (verified on TWO
    different emitters: EW requested + ticket message);
  * unsubscribe -> no new SA rows;
  * an UNSUBSCRIBED SA's own feed stays empty (historical default);
  * the subscription endpoints are SA-only (403 otherwise);
  * ?company= mode returns the company stream deduplicated per event
    and never mutates read state; for a non-SA caller the param is
    ignored (normal recipient-scoped feed);
  * the email path is untouched (no NotificationLog rows from the
    in-app emitters is pre-existing behavior; asserted indirectly by
    only ever calling the in-app emitters here).
"""
from rest_framework.test import APITestCase

from accounts.models import UserRole
from notifications.models import (
    Notification,
    NotificationType,
    SuperAdminCompanySubscription,
)
from notifications.services import (
    emit_extra_work_requested_notifications,
    emit_ticket_message_notifications,
)
from extra_work.models import ExtraWorkCategory, ExtraWorkRequest, ExtraWorkStatus
from test_utils import TenantFixtureMixin
from tickets.models import TicketMessage, TicketMessageType

LIST_URL = "/api/notifications/company-subscriptions/"


def _detail_url(company_id):
    return f"/api/notifications/company-subscriptions/{company_id}/"


class _SubscriptionFixture(TenantFixtureMixin, APITestCase):
    def _make_ew(self, **overrides):
        defaults = dict(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="SA-sub EW",
            description="d",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
        )
        defaults.update(overrides)
        return ExtraWorkRequest.objects.create(**defaults)

    def _sa_rows(self, event_type=None):
        qs = Notification.objects.filter(recipient=self.super_admin)
        if event_type:
            qs = qs.filter(event_type=event_type)
        return qs


class SubscriptionEndpointTests(_SubscriptionFixture):
    def test_non_sa_gets_403_on_all_endpoints(self):
        for user in (self.company_admin, self.manager, self.customer_user):
            self.authenticate(user)
            self.assertEqual(self.client.get(LIST_URL).status_code, 403)
            self.assertEqual(
                self.client.put(_detail_url(self.company.id)).status_code, 403
            )
            self.assertEqual(
                self.client.delete(
                    _detail_url(self.company.id)
                ).status_code,
                403,
            )

    def test_sa_subscribe_unsubscribe_roundtrip_idempotent(self):
        self.authenticate(self.super_admin)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.data["subscribed_company_ids"], [])

        for _ in range(2):  # idempotent PUT
            resp = self.client.put(_detail_url(self.company.id))
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.data["subscribed"])
        self.assertEqual(
            SuperAdminCompanySubscription.objects.filter(
                user=self.super_admin, company=self.company
            ).count(),
            1,
        )
        resp = self.client.get(LIST_URL)
        self.assertEqual(
            resp.data["subscribed_company_ids"], [self.company.id]
        )

        resp = self.client.delete(_detail_url(self.company.id))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["subscribed"])
        self.assertEqual(
            self.client.get(LIST_URL).data["subscribed_company_ids"], []
        )


class EmailOptInEndpointTests(_SubscriptionFixture):
    """Sprint 122 (Part C) — the SEPARATE per-company EMAIL opt-in
    (SuperAdminCompanySubscription.email_enabled), surfaced on the SAME
    endpoints as the in-app subscription above. Owner-decided: subscribing
    in-app must NOT silently enable email — defaults False and a bare
    re-subscribe never resets an existing True."""

    def test_bare_put_creates_subscription_with_email_disabled(self):
        self.authenticate(self.super_admin)
        resp = self.client.put(_detail_url(self.company.id))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["subscribed"])
        self.assertFalse(resp.data["email_enabled"])
        self.assertFalse(
            SuperAdminCompanySubscription.objects.get(
                user=self.super_admin, company=self.company
            ).email_enabled
        )

    def test_put_with_email_enabled_true_sets_it(self):
        self.authenticate(self.super_admin)
        resp = self.client.put(
            _detail_url(self.company.id),
            {"email_enabled": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["email_enabled"])
        self.assertTrue(
            SuperAdminCompanySubscription.objects.get(
                user=self.super_admin, company=self.company
            ).email_enabled
        )

    def test_bare_put_does_not_reset_existing_email_enabled(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company, email_enabled=True,
        )
        self.authenticate(self.super_admin)
        resp = self.client.put(_detail_url(self.company.id))  # no body
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["subscribed"])
        self.assertTrue(resp.data["email_enabled"])

    def test_put_can_disable_email_while_staying_subscribed(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company, email_enabled=True,
        )
        self.authenticate(self.super_admin)
        resp = self.client.put(
            _detail_url(self.company.id),
            {"email_enabled": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["subscribed"])
        self.assertFalse(resp.data["email_enabled"])

    def test_list_reports_email_enabled_company_ids_subset(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company, email_enabled=True,
        )
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.other_company, email_enabled=False,
        )
        self.authenticate(self.super_admin)
        resp = self.client.get(LIST_URL)
        self.assertEqual(
            set(resp.data["subscribed_company_ids"]),
            {self.company.id, self.other_company.id},
        )
        self.assertEqual(
            resp.data["email_enabled_company_ids"], [self.company.id]
        )

    def test_delete_clears_email_enabled_with_the_row(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company, email_enabled=True,
        )
        self.authenticate(self.super_admin)
        resp = self.client.delete(_detail_url(self.company.id))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["subscribed"])
        self.assertFalse(resp.data["email_enabled"])
        self.assertFalse(
            SuperAdminCompanySubscription.objects.filter(
                user=self.super_admin, company=self.company
            ).exists()
        )


class SubscriptionFanOutTests(_SubscriptionFixture):
    def test_unsubscribed_sa_default_feed_stays_empty(self):
        emit_extra_work_requested_notifications(
            self._make_ew(), actor=self.customer_user
        )
        message = TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.customer_user,
            message="hello provider",
            message_type=TicketMessageType.PUBLIC_REPLY,
        )
        emit_ticket_message_notifications(message, actor=self.customer_user)
        self.assertFalse(self._sa_rows().exists())
        self.authenticate(self.super_admin)
        resp = self.client.get("/api/notifications/")
        self.assertEqual(resp.data["count"], 0)

    def test_subscribed_sa_gets_ew_requested_rows(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company
        )
        emit_extra_work_requested_notifications(
            self._make_ew(), actor=self.customer_user
        )
        row = self._sa_rows(NotificationType.EXTRA_WORK_REQUESTED).get()
        self.assertIsNone(row.read_at)
        # Provider management still notified alongside.
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.company_admin,
                event_type=NotificationType.EXTRA_WORK_REQUESTED,
            ).exists()
        )

    def test_subscribed_sa_gets_ticket_message_rows(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company
        )
        message = TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.customer_user,
            message="hello provider",
            message_type=TicketMessageType.PUBLIC_REPLY,
        )
        emit_ticket_message_notifications(message, actor=self.customer_user)
        self.assertTrue(
            self._sa_rows(NotificationType.TICKET_MESSAGE).exists()
        )

    def test_customer_internal_tier_never_reaches_subscribed_sa(self):
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company
        )
        message = TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.customer_user,
            message="customer private note",
            message_type=TicketMessageType.CUSTOMER_INTERNAL,
        )
        emit_ticket_message_notifications(message, actor=self.customer_user)
        self.assertFalse(self._sa_rows().exists())

    def test_unsubscribe_stops_new_rows(self):
        sub = SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.company
        )
        emit_extra_work_requested_notifications(
            self._make_ew(), actor=self.customer_user
        )
        self.assertEqual(self._sa_rows().count(), 1)
        sub.delete()
        emit_extra_work_requested_notifications(
            self._make_ew(title="after unsub"), actor=self.customer_user
        )
        self.assertEqual(self._sa_rows().count(), 1)

    def test_cross_company_subscription_does_not_leak(self):
        # Subscribed to company B only -> a company A event emits no SA row.
        SuperAdminCompanySubscription.objects.create(
            user=self.super_admin, company=self.other_company
        )
        emit_extra_work_requested_notifications(
            self._make_ew(), actor=self.customer_user
        )
        self.assertFalse(self._sa_rows().exists())


class CompanyViewAsModeTests(_SubscriptionFixture):
    def _emit_one_event_with_two_recipients(self):
        # EW requested fans out to company_admin + manager (BM of the
        # building) — ONE event, TWO per-recipient rows.
        emit_extra_work_requested_notifications(
            self._make_ew(), actor=self.customer_user
        )

    def test_company_mode_dedupes_per_event_and_is_view_only(self):
        self._emit_one_event_with_two_recipients()
        raw_count = Notification.objects.filter(
            event_type=NotificationType.EXTRA_WORK_REQUESTED
        ).count()
        self.assertEqual(raw_count, 2)

        self.authenticate(self.super_admin)
        resp = self.client.get(
            f"/api/notifications/?company={self.company.id}"
        )
        self.assertEqual(resp.status_code, 200)
        results = resp.data["results"]
        self.assertEqual(
            len(
                [
                    r
                    for r in results
                    if r["event_type"]
                    == NotificationType.EXTRA_WORK_REQUESTED
                ]
            ),
            1,
        )
        # View-only: nothing was marked read by looking.
        self.assertEqual(
            Notification.objects.filter(read_at__isnull=True).count(),
            raw_count,
        )

    def test_company_mode_scopes_to_that_company(self):
        self._emit_one_event_with_two_recipients()
        self.authenticate(self.super_admin)
        resp = self.client.get(
            f"/api/notifications/?company={self.other_company.id}"
        )
        self.assertEqual(resp.data["count"], 0)

    def test_non_sa_company_param_is_ignored(self):
        self._emit_one_event_with_two_recipients()
        self.authenticate(self.company_admin)
        resp = self.client.get(
            f"/api/notifications/?company={self.company.id}"
        )
        self.assertEqual(resp.status_code, 200)
        # Own recipient-scoped feed, NOT the company stream: exactly the
        # admin's own row.
        for row in resp.data["results"]:
            self.assertEqual(
                row["event_type"], NotificationType.EXTRA_WORK_REQUESTED
            )
        self.assertEqual(resp.data["count"], 1)
