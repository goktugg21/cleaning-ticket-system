"""
M1 B6 — Extra Work message thread (mirrors the B5 ticket model, MINUS staff).

Three channels (SA = Super Admin, MGMT = Company Admin / Building Manager,
CUST = customer-side). STAFF have no EW scope and see / post NOTHING.

  READ-VISIBILITY (NORMAL):
    PUBLIC_REPLY        SA y  MGMT y  CUST y
    INTERNAL_NOTE       SA y  MGMT y  CUST n
    CUSTOMER_INTERNAL   SA y  MGMT n  CUST y   (SA forensic)
  POSTING:
    PUBLIC_REPLY = CUST+MGMT+SA;  INTERNAL_NOTE = MGMT+SA;  CUSTOMER_INTERNAL = CUST.

Everything is enforced SERVER-SIDE (chokepoint + create-path authz +
validation). Item-7: a direct-publish (quote-bypass) notifies the customer side.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.message_permissions import (
    ew_message_type_visible_to_user,
    filter_ew_messages_visible_to,
)
from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkMessage,
    ExtraWorkMessageType,
    ExtraWorkMessageVisibility,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestIntent,
    ExtraWorkRequestItem,
    ExtraWorkStatus,
    Proposal,
    ProposalLine,
    ProposalStatus,
    Service,
    ServiceCategory,
)
from notifications.models import Notification, NotificationType

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
MT = ExtraWorkMessageType
VIS = ExtraWorkMessageVisibility
AccessRole = CustomerUserBuildingAccess.AccessRole


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, role=role,
        full_name=email.split("@")[0], **extra,
    )


class _B6Fixture(TestCase):
    """Provider A (company/building/customer) + a cross-tenant Provider B.

    Roles on the Provider-A EW `self.ew`:
      * SA    = super_admin
      * MGMT  = admin (CA of company) + bm (BM of building)
      * CUST  = cust (creator, view_own) + cust2/cust3 (view_location)
    Cross-tenant foils (never notified about a Provider-A EW): other_admin,
    other_bm, other_cust. STAFF (no EW scope): staff.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov A", slug="b6-a")
        cls.other_company = Company.objects.create(name="Prov B", slug="b6-b")
        cls.building = Building.objects.create(company=cls.company, name="B6-A")
        cls.other_building = Building.objects.create(
            company=cls.other_company, name="B6-B"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust-A", building=cls.building
        )
        cls.other_customer = Customer.objects.create(
            company=cls.other_company, name="Cust-B", building=cls.other_building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.other_customer, building=cls.other_building
        )

        cls.super_admin = _mk(
            "b6-super@example.com", UserRole.SUPER_ADMIN,
            is_staff=True, is_superuser=True,
        )
        cls.admin = _mk("b6-admin@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)
        cls.bm = _mk("b6-bm@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(user=cls.bm, building=cls.building)
        cls.other_admin = _mk("b6-other-admin@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.other_admin, company=cls.other_company
        )
        cls.other_bm = _mk("b6-other-bm@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.other_bm, building=cls.other_building
        )
        cls.staff = _mk("b6-staff@example.com", UserRole.STAFF)

        cls.cust = cls._customer_member(
            "b6-cust@example.com", cls.customer, cls.building,
            AccessRole.CUSTOMER_USER,
        )
        cls.cust2 = cls._customer_member(
            "b6-cust2@example.com", cls.customer, cls.building,
            AccessRole.CUSTOMER_LOCATION_MANAGER,
        )
        cls.cust3 = cls._customer_member(
            "b6-cust3@example.com", cls.customer, cls.building,
            AccessRole.CUSTOMER_LOCATION_MANAGER,
        )
        cls.other_cust = cls._customer_member(
            "b6-other-cust@example.com", cls.other_customer, cls.other_building,
            AccessRole.CUSTOMER_USER,
        )

        cls.service_cat = ServiceCategory.objects.create(name="B6-Cat")
        cls.service = Service.objects.create(
            category=cls.service_cat, company=cls.company, name="Window cleaning",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

        cls.ew = cls._make_ew(cls.customer, cls.building, cls.company, cls.cust)

    @classmethod
    def _customer_member(cls, email, customer, building, access_role):
        user = _mk(email, UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            user=user, customer=customer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=building, access_role=access_role
        )
        return user

    @classmethod
    def _make_ew(cls, customer, building, company, creator,
                 *, status=ExtraWorkStatus.REQUESTED, intent=None):
        ew = ExtraWorkRequest.objects.create(
            company=company, building=building, customer=customer,
            created_by=creator, title="B6 EW", description="d",
            category=ExtraWorkCategory.DEEP_CLEANING, status=status,
            request_intent=intent,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew, service=cls.service, quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            requested_date=date(2026, 6, 15), customer_note="",
        )
        return ew

    # -- helpers ---------------------------------------------------------
    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _messages_url(self, ew=None):
        return f"/api/extra-work/{(ew or self.ew).id}/messages/"

    def _recipients_url(self, ew=None):
        return f"/api/extra-work/{(ew or self.ew).id}/message-recipients/"

    def _mk_msg(self, author, message_type, *, visibility=VIS.NORMAL,
                directed=None, message="x", ew=None):
        msg = ExtraWorkMessage.objects.create(
            extra_work=ew or self.ew, author=author, message_type=message_type,
            visibility_mode=visibility, message=message,
        )
        if directed:
            msg.directed_to.set(directed)
        return msg

    def _visible_ids(self, actor):
        resp = self._api(actor).get(self._messages_url())
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        # The EW messages list returns a flat array (like proposals).
        data = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        return {row["id"] for row in data}

    def _post(self, author, **payload):
        body = {"message": payload.pop("message", "hi")}
        body.update(payload)
        return self._api(author).post(self._messages_url(), body, format="json")

    def _recipients(self, actor, message_type, ew=None):
        resp = self._api(actor).get(
            self._recipients_url(ew) + f"?message_type={message_type}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        return resp.data["results"]

    def _recipient_ids(self, event_type, ew=None):
        return set(
            Notification.objects.filter(
                event_type=event_type, extra_work=ew or self.ew
            ).values_list("recipient_id", flat=True)
        )


# ---------------------------------------------------------------------------
# READ visibility per role
# ---------------------------------------------------------------------------
class ReadVisibilityTests(_B6Fixture):
    def setUp(self):
        self.public = self._mk_msg(self.admin, MT.PUBLIC_REPLY)
        self.internal = self._mk_msg(self.admin, MT.INTERNAL_NOTE)
        self.cust_internal = self._mk_msg(self.cust, MT.CUSTOMER_INTERNAL)

    def test_super_admin_sees_every_tier(self):
        self.assertEqual(
            self._visible_ids(self.super_admin),
            {self.public.id, self.internal.id, self.cust_internal.id},
        )

    def test_mgmt_sees_all_except_customer_internal(self):
        for actor in (self.admin, self.bm):
            ids = self._visible_ids(actor)
            self.assertEqual(ids, {self.public.id, self.internal.id})
            self.assertNotIn(self.cust_internal.id, ids)

    def test_customer_sees_public_and_customer_internal_not_internal(self):
        ids = self._visible_ids(self.cust)
        self.assertEqual(ids, {self.public.id, self.cust_internal.id})
        self.assertNotIn(self.internal.id, ids)

    def test_staff_sees_nothing_404_no_scope(self):
        # STAFF have no EW scope -> the messages endpoint 404s entirely.
        resp = self._api(self.staff).get(self._messages_url())
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# RESTRICTED CUSTOMER_INTERNAL — party-only (incl. NOT SA on the list)
# ---------------------------------------------------------------------------
class RestrictedReadTests(_B6Fixture):
    def setUp(self):
        self.msg = self._mk_msg(
            self.cust, MT.CUSTOMER_INTERNAL, visibility=VIS.RESTRICTED,
            directed=[self.cust2], message="CUST-PRIVATE",
        )

    def test_visible_only_to_author_and_directed(self):
        self.assertIn(self.msg.id, self._visible_ids(self.cust))   # author
        self.assertIn(self.msg.id, self._visible_ids(self.cust2))  # directed
        self.assertNotIn(self.msg.id, self._visible_ids(self.cust3))  # non-party
        self.assertNotIn(self.msg.id, self._visible_ids(self.admin))  # MGMT
        # SA is forensic for the tier but STILL bound by RESTRICTED on the list.
        self.assertNotIn(self.msg.id, self._visible_ids(self.super_admin))


# ---------------------------------------------------------------------------
# POSTING authz
# ---------------------------------------------------------------------------
class PostingAuthzTests(_B6Fixture):
    def test_customer_cannot_post_internal_note(self):
        resp = self._post(self.cust, message_type=MT.INTERNAL_NOTE)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertEqual(
            getattr(resp.data["message_type"][0], "code", None),
            "ew_message_type_not_allowed",
        )

    def test_mgmt_cannot_post_customer_internal(self):
        for actor in (self.admin, self.bm):
            resp = self._post(actor, message_type=MT.CUSTOMER_INTERNAL)
            self.assertEqual(
                resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content
            )

    def test_customer_can_post_customer_internal(self):
        resp = self._post(self.cust, message_type=MT.CUSTOMER_INTERNAL)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        self.assertEqual(resp.data["message_type"], MT.CUSTOMER_INTERNAL)

    def test_customer_can_post_public_reply(self):
        resp = self._post(self.cust, message_type=MT.PUBLIC_REPLY)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)

    def test_mgmt_can_post_public_reply_and_internal_note(self):
        self.assertEqual(
            self._post(self.admin, message_type=MT.PUBLIC_REPLY).status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(
            self._post(self.admin, message_type=MT.INTERNAL_NOTE).status_code,
            status.HTTP_201_CREATED,
        )

    def test_staff_post_is_blocked(self):
        # No EW scope -> 404 (the staff actor cannot resolve the parent EW).
        resp = self._post(self.staff, message_type=MT.PUBLIC_REPLY)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(ExtraWorkMessage.objects.exists())


# ---------------------------------------------------------------------------
# directed_to / RESTRICTED side-aware authz
# ---------------------------------------------------------------------------
class DirectedRestrictedAuthzTests(_B6Fixture):
    def test_customer_cannot_direct_a_provider(self):
        for target in (self.admin, self.super_admin):
            resp = self._post(
                self.cust, message_type=MT.PUBLIC_REPLY, directed_to=[target.id]
            )
            self.assertEqual(
                resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content
            )
            self.assertEqual(
                getattr(resp.data["directed_to"][0], "code", None),
                "directed_to_must_be_customer_side",
            )

    def test_customer_can_direct_another_customer_on_public_reply(self):
        resp = self._post(
            self.cust, message_type=MT.PUBLIC_REPLY, directed_to=[self.cust2.id]
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)

    def test_customer_cannot_restrict_public_reply(self):
        resp = self._post(
            self.cust, message_type=MT.PUBLIC_REPLY,
            visibility_mode=VIS.RESTRICTED, directed_to=[self.cust2.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertEqual(
            getattr(resp.data["visibility_mode"][0], "code", None),
            "restricted_only_for_customer_internal",
        )

    def test_customer_can_restrict_customer_internal(self):
        resp = self._post(
            self.cust, message_type=MT.CUSTOMER_INTERNAL,
            visibility_mode=VIS.RESTRICTED, directed_to=[self.cust2.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        self.assertEqual(resp.data["visibility_mode"], VIS.RESTRICTED)


# ---------------------------------------------------------------------------
# Recipients endpoint — side-aware by caller + no email
# ---------------------------------------------------------------------------
class RecipientsSideAwareTests(_B6Fixture):
    def test_customer_caller_gets_customer_side_only(self):
        results = self._recipients(self.cust, MT.PUBLIC_REPLY)
        sides = {r["side"] for r in results}
        ids = {r["id"] for r in results}
        self.assertEqual(sides, {"customer"})
        self.assertIn(self.cust2.id, ids)
        self.assertNotIn(self.admin.id, ids)
        self.assertNotIn(self.bm.id, ids)
        self.assertNotIn(self.cust.id, ids)  # caller excluded
        self.assertTrue(all("email" not in r for r in results))

    def test_mgmt_caller_gets_full_audience(self):
        results = self._recipients(self.admin, MT.PUBLIC_REPLY)
        ids = {r["id"] for r in results}
        self.assertIn(self.cust.id, ids)
        self.assertIn(self.bm.id, ids)
        self.assertTrue(all("email" not in r for r in results))

    def test_internal_note_picker_provider_only(self):
        results = self._recipients(self.admin, MT.INTERNAL_NOTE)
        sides = {r["side"] for r in results}
        self.assertTrue(results)
        self.assertEqual(sides, {"provider"})

    def test_out_of_scope_caller_404(self):
        resp = self._api(self.other_admin).get(
            self._recipients_url() + f"?message_type={MT.PUBLIC_REPLY}"
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# EMIT — fan-out per tier
# ---------------------------------------------------------------------------
class EmitTests(_B6Fixture):
    def test_public_reply_notifies_provider_mgmt_and_customer_not_sa(self):
        resp = self._post(self.bm, message_type=MT.PUBLIC_REPLY)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        recipients = self._recipient_ids(NotificationType.EXTRA_WORK_MESSAGE)
        self.assertEqual(
            recipients,
            {self.admin.id, self.cust.id, self.cust2.id, self.cust3.id},
        )
        # SA never auto-notified; author (bm) excluded; staff never.
        self.assertNotIn(self.super_admin.id, recipients)
        self.assertNotIn(self.bm.id, recipients)
        self.assertNotIn(self.staff.id, recipients)

    def test_internal_note_notifies_provider_mgmt_only(self):
        resp = self._post(self.bm, message_type=MT.INTERNAL_NOTE)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        recipients = self._recipient_ids(NotificationType.EXTRA_WORK_MESSAGE)
        self.assertEqual(recipients, {self.admin.id})

    def test_customer_internal_notifies_customer_only(self):
        resp = self._post(self.cust, message_type=MT.CUSTOMER_INTERNAL)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        recipients = self._recipient_ids(NotificationType.EXTRA_WORK_MESSAGE)
        self.assertEqual(recipients, {self.cust2.id, self.cust3.id})
        self.assertNotIn(self.admin.id, recipients)
        self.assertNotIn(self.super_admin.id, recipients)

    def test_restricted_notifies_directed_only(self):
        resp = self._post(
            self.cust, message_type=MT.CUSTOMER_INTERNAL,
            visibility_mode=VIS.RESTRICTED, directed_to=[self.cust2.id],
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        recipients = self._recipient_ids(NotificationType.EXTRA_WORK_MESSAGE)
        self.assertEqual(recipients, {self.cust2.id})

    def test_cross_tenant_isolation(self):
        # A message on Provider-A's EW never notifies Provider-B users.
        self._post(self.bm, message_type=MT.PUBLIC_REPLY)
        recipients = self._recipient_ids(NotificationType.EXTRA_WORK_MESSAGE)
        self.assertNotIn(self.other_admin.id, recipients)
        self.assertNotIn(self.other_bm.id, recipients)
        self.assertNotIn(self.other_cust.id, recipients)


# ---------------------------------------------------------------------------
# Item-7 — direct-publish notifies the customer side, exactly once
# ---------------------------------------------------------------------------
class DirectPublishNotifyTests(_B6Fixture):
    def _setup_quote_ew(self):
        ew = self._make_ew(
            self.customer, self.building, self.company, self.cust,
            status=ExtraWorkStatus.UNDER_REVIEW,
            intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
        )
        proposal = Proposal.objects.create(
            extra_work_request=ew, status=ProposalStatus.DRAFT,
            created_by=self.admin,
        )
        ProposalLine.objects.create(
            proposal=proposal, service=self.service, quantity=Decimal("2.00"),
            unit_type=ExtraWorkPricingUnitType.HOURS,
            unit_price=Decimal("50.00"), vat_pct=Decimal("21.00"),
        )
        return ew, proposal

    def test_direct_publish_notifies_customer_side_exactly_once(self):
        ew, proposal = self._setup_quote_ew()
        # SUPER_ADMIN can direct-publish without the dangerous company grant.
        resp = self._api(self.super_admin).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/direct-publish/",
            {"override_reason": "Customer agreed on the phone."},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)

        rows = Notification.objects.filter(
            event_type=NotificationType.EXTRA_WORK_PUBLISHED, extra_work=ew
        )
        recipients = set(rows.values_list("recipient_id", flat=True))
        # Customer side notified; provider mgmt + SA never.
        self.assertEqual(recipients, {self.cust.id, self.cust2.id, self.cust3.id})
        self.assertNotIn(self.admin.id, recipients)
        self.assertNotIn(self.bm.id, recipients)
        self.assertNotIn(self.super_admin.id, recipients)
        # Exactly ONE row per recipient (no double-fire).
        self.assertEqual(rows.count(), 3)

    def test_normal_proposal_flow_does_not_emit_published(self):
        # A plain DRAFT proposal create does NOT direct-publish -> no
        # EXTRA_WORK_PUBLISHED notification.
        self._setup_quote_ew()
        self.assertFalse(
            Notification.objects.filter(
                event_type=NotificationType.EXTRA_WORK_PUBLISHED
            ).exists()
        )


# ---------------------------------------------------------------------------
# LOCKSTEP — predicate == queryset across every role x the 3 tiers
# ---------------------------------------------------------------------------
class LockstepParityTests(_B6Fixture):
    def test_predicate_and_queryset_agree(self):
        per_tier = {}
        for tier in (MT.PUBLIC_REPLY, MT.INTERNAL_NOTE, MT.CUSTOMER_INTERNAL):
            per_tier[tier] = self._mk_msg(self.admin, tier, message="x")

        actors = {
            "SA": self.super_admin, "CA": self.admin, "BM": self.bm,
            "STAFF": self.staff, "CUST": self.cust, "anon": None,
        }
        for label, user in actors.items():
            visible = set(
                filter_ew_messages_visible_to(
                    ExtraWorkMessage.objects.filter(extra_work=self.ew), user
                ).values_list("id", flat=True)
            )
            for tier, msg in per_tier.items():
                predicate = ew_message_type_visible_to_user(user, tier)
                in_qs = msg.id in visible
                self.assertEqual(
                    predicate, in_qs,
                    f"lockstep drift: actor={label} tier={tier} "
                    f"predicate={predicate} queryset={in_qs}",
                )
