"""TU — ONE LIVE CONVERSATION PER JOB.

Once an Extra Work has spawned operational work, the ticket's thread IS
the job's conversation. The request's own thread becomes history:
readable for ever, writable never.

RECON RESULT pinned here, because it is why the freeze sits where it
does: `ExtraWorkMessageListCreateView.post` is the ONLY write path to an
EW thread anywhere in the codebase (a repo-wide search for
`ExtraWorkMessage.objects.create` finds nothing else outside the demo
seeder). One door, one bolt.

What these pin:

  * posting BEFORE work is spawned still works, exactly as before;
  * posting AFTER is refused 409 `thread_frozen` — 409 and not 403,
    because nothing about the ASKER is wrong: the same person may post
    the same words on the job a second later. It is the state of the
    resource that refuses;
  * reads are completely unaffected, for provider and customer alike,
    and the frozen history keeps its per-tier visibility filtering;
  * the freeze predicate agrees with the `spawned_tickets` serializer
    field that drives the provider's redirect and the customer's
    composer. If those two ever disagreed, one side would offer a
    composer the other refuses.
"""
from __future__ import annotations

from rest_framework import status

from extra_work.message_permissions import ew_thread_is_frozen
from extra_work.models import ExtraWorkMessage, ExtraWorkMessageType
from extra_work.serializers import _spawned_tickets_for
from tickets.models import Ticket, TicketStatus

from .test_m1_b6_ew_messages import _B6Fixture


class _FreezeFixture(_B6Fixture):
    def _messages_url(self, ew=None):
        return f"/api/extra-work/{(ew or self.ew).id}/messages/"

    def _spawn(self, ew=None):
        """Give the request a real operational ticket, through the
        canonical FK the money definition uses."""
        target = ew or self.ew
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Spawned job",
            description="d",
            status=TicketStatus.OPEN,
            extra_work_request=target,
        )

    def _post(self, actor, body="hello"):
        return self._api(actor).post(
            self._messages_url(),
            {
                "message": body,
                "message_type": ExtraWorkMessageType.PUBLIC_REPLY,
                "visibility_mode": "NORMAL",
            },
            format="json",
        )


class PostingBeforeTheJobExistsStillWorksTests(_FreezeFixture):
    def test_provider_post_pre_spawn_ok(self):
        response = self._post(self.admin)
        self.assertEqual(response.status_code, 201, response.data)

    def test_customer_post_pre_spawn_ok(self):
        response = self._post(self.cust)
        self.assertEqual(response.status_code, 201, response.data)

    def test_the_thread_is_not_frozen_before_a_ticket_exists(self):
        self.assertFalse(ew_thread_is_frozen(self.ew))


class PostingAfterTheJobExistsIsRefusedTests(_FreezeFixture):
    def setUp(self):
        super().setUp()
        self.ticket = self._spawn()

    def test_provider_post_post_spawn_409(self):
        response = self._post(self.admin)
        self.assertEqual(
            response.status_code, status.HTTP_409_CONFLICT, response.data
        )
        self.assertEqual(response.data["code"], "thread_frozen")

    def test_customer_post_post_spawn_409(self):
        response = self._post(self.cust)
        self.assertEqual(
            response.status_code, status.HTTP_409_CONFLICT, response.data
        )
        self.assertEqual(response.data["code"], "thread_frozen")

    def test_nothing_is_written(self):
        before = ExtraWorkMessage.objects.filter(extra_work=self.ew).count()
        self._post(self.cust)
        self.assertEqual(
            ExtraWorkMessage.objects.filter(extra_work=self.ew).count(), before
        )

    def test_a_soft_deleted_ticket_does_not_freeze_the_thread(self):
        """The predicate excludes soft-deleted tickets, exactly as the
        `spawned_tickets` serializer field does — so a request whose only
        job was withdrawn is a live request again."""
        self.ticket.deleted_at = "2026-01-01T00:00:00Z"
        self.ticket.save(update_fields=["deleted_at"])
        self.assertFalse(ew_thread_is_frozen(self.ew))
        self.assertEqual(self._post(self.admin).status_code, 201)

    def test_another_requests_thread_is_untouched(self):
        other = self._make_ew(
            self.customer, self.building, self.company, self.cust
        )
        response = self._api(self.admin).post(
            self._messages_url(other),
            {
                "message": "still open",
                "message_type": ExtraWorkMessageType.PUBLIC_REPLY,
                "visibility_mode": "NORMAL",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)


class ReadsAreUnaffectedTests(_FreezeFixture):
    def setUp(self):
        super().setUp()
        # A thread with history written BEFORE the job existed.
        self._api(self.admin).post(
            self._messages_url(),
            {
                "message": "provider says hello",
                "message_type": ExtraWorkMessageType.PUBLIC_REPLY,
                "visibility_mode": "NORMAL",
            },
            format="json",
        )
        self._api(self.cust).post(
            self._messages_url(),
            {
                "message": "customer replies",
                "message_type": ExtraWorkMessageType.PUBLIC_REPLY,
                "visibility_mode": "NORMAL",
            },
            format="json",
        )
        self.before_provider = self._read(self.admin)
        self.before_customer = self._read(self.cust)
        self.ticket = self._spawn()

    def _read(self, actor):
        response = self._api(actor).get(self._messages_url())
        self.assertEqual(response.status_code, 200, response.data)
        return [row["message"] for row in response.data]

    def test_provider_read_is_byte_identical_after_the_freeze(self):
        self.assertEqual(self._read(self.admin), self.before_provider)

    def test_customer_read_is_byte_identical_after_the_freeze(self):
        self.assertEqual(self._read(self.cust), self.before_customer)

    def test_the_history_is_still_there_and_not_empty(self):
        self.assertEqual(len(self._read(self.cust)), 2)


class TheFreezeAgreesWithTheSpawnedTicketsFieldTests(_FreezeFixture):
    """The predicate and the serializer field must answer the same
    question. The field drives the provider's redirect and the
    customer's composer; the predicate drives the refusal."""

    def test_they_agree_before_and_after_spawning(self):
        self.assertEqual(
            ew_thread_is_frozen(self.ew),
            len(_spawned_tickets_for(self.ew)) >= 1,
        )
        self._spawn()
        self.ew.refresh_from_db()
        self.assertEqual(
            ew_thread_is_frozen(self.ew),
            len(_spawned_tickets_for(self.ew)) >= 1,
        )
        self.assertTrue(ew_thread_is_frozen(self.ew))
