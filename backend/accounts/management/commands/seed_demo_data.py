"""
Sprint 21 v2 — canonical demo seed (two-company edition).

Idempotent. Aligns with the demo cards rendered on the login page when
VITE_DEMO_MODE=true and with the Playwright test fixtures under
frontend/tests/e2e. Creates / updates two fully isolated demo companies
so every role and every cross-company scope rule can be exercised
end-to-end against a single seed.

The Sprint 21 v2 (post-mortem of the first Sprint 21 demo) renames
every persona to a `<name>-<role>-<tenant>@<tenant>.demo` shape so an
operator viewing /admin/users can identify each demo account at a
glance. Exactly one canonical super admin lives at
superadmin@cleanops.demo; the v1 emails (super@cleanops.demo,
admin@cleanops.demo, gokhan@cleanops.demo, …) are added to the legacy
prune list so a stack that previously ran v1 lands on a clean
matrix after the first v2 seed run.

Idempotent invariants after a successful run:

  Company A : 'Osius Demo'           (slug=osius-demo)
    Buildings (3)   : B1 / B2 / B3 Amsterdam
    Customer        : 'B Amsterdam' (consolidated; building=NULL)
                      linked to {B1, B2, B3}
    Tickets (4)     : OPEN / IN_PROGRESS / WAITING_CUSTOMER_APPROVAL / CLOSED
    Staff workflow  : 1 PENDING StaffAssignmentRequest from Ahmet on
                      the OPEN ticket (Sprint 23B review queue)
                    : 1 direct TicketStaffAssignment of Ahmet on the
                      IN_PROGRESS ticket (Sprint 25A admin direct
                      staff assignment)

  Company B : 'Bright Facilities'    (slug=bright-facilities)
    Buildings (2)   : R1 / R2 Rotterdam
    Customer        : 'City Office Rotterdam' (consolidated; building=NULL)
                      linked to {R1, R2}
    Tickets (2)     : OPEN / IN_PROGRESS

  Demo users (every account uses the password Demo12345!):

    superadmin@cleanops.demo                          SUPER_ADMIN (both companies)

    Company A — Osius Demo / B Amsterdam:
      ramazan-admin-osius@b-amsterdam.demo            COMPANY_ADMIN
      gokhan-manager-osius@b-amsterdam.demo           BUILDING_MANAGER  → B1, B2, B3
      murat-manager-osius@b-amsterdam.demo            BUILDING_MANAGER  → B1
      isa-manager-osius@b-amsterdam.demo              BUILDING_MANAGER  → B2
      tom-customer-b-amsterdam@b-amsterdam.demo       CUSTOMER_USER     → B1, B2, B3
      iris-customer-b-amsterdam@b-amsterdam.demo      CUSTOMER_USER     → B1, B2
      amanda-customer-b-amsterdam@b-amsterdam.demo    CUSTOMER_USER     → B3

    Company B — Bright Facilities:
      sophie-admin-bright@bright-facilities.demo      COMPANY_ADMIN
      bram-manager-bright@bright-facilities.demo      BUILDING_MANAGER  → R1, R2
      lotte-customer-bright@bright-facilities.demo    CUSTOMER_USER     → R1, R2

Usage
-----
    docker compose exec -T backend python manage.py seed_demo_data
    docker compose exec -T backend python manage.py seed_demo_data --reset-tickets

Safety
------
- Refuses to run when DJANGO_DEBUG=False unless the operator passes
  --i-know-this-is-not-prod. This lets the seed run on a CI / local
  dev stack but fails closed on a production-shaped settings tree.
- All passwords land at Demo12345! — DO NOT enable VITE_DEMO_MODE on
  a pilot/production frontend, and DO NOT run this command against a
  production database. The check_no_demo_accounts management command
  refuses pilot launch if any seeded demo email is present (both
  Company A and Company B accounts are covered by that guard, plus a
  catch-all @cleanops.demo suffix rule).

The `[DEMO]` prefix on ticket titles is a stable filter handle:
re-running with --reset-tickets deletes only those rows so the
operator can rebuild the lifecycle samples without disturbing real
tickets that may have been created during a manual walkthrough.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from tickets.models import (
    AssignmentRequestStatus,
    StaffAssignmentRequest,
    Ticket,
    TicketPriority,
    TicketStaffAssignment,
    TicketStatus,
    TicketType,
)
from tickets.state_machine import apply_transition


DEMO_PASSWORD = "Demo12345!"
DEMO_TICKET_PREFIX = "[DEMO]"


# ---------------------------------------------------------------------------
# Sprint 21 cleanup — Legacy demo personas seeded by commands that have
# since been deleted (`seed_demo`, `seed_b_amsterdam_demo`) or by the
# inline shell heredoc in the pre-Sprint-21 `scripts/demo_up.sh`. The
# rows themselves persist in any local/demo database that ran those
# scripts before Sprint 21 landed, so the canonical seed prunes them
# on every run. The list is exact-match only: a typo in a real
# operator's email will never collide because every entry is a
# documented historical seed value.
#
# The `check_no_demo_accounts` pilot guard still references the same
# emails — the prune here only fires on DEBUG/local stacks (the seed
# itself refuses on DJANGO_DEBUG=False without --i-know-this-is-not-prod),
# so a pilot host cannot reach this code path.
# ---------------------------------------------------------------------------
LEGACY_DEMO_EMAILS = (
    # Sprint 10 — seed_demo.py (removed in Sprint 21).
    "demo-super@example.com",
    "demo-company-admin@example.com",
    "demo-manager@example.com",
    "demo-customer@example.com",
    # Pre-Sprint-21 scripts/demo_up.sh inline shell heredoc.
    "admin@example.com",
    "companyadmin@example.com",
    "manager@example.com",
    "customer@example.com",
    # Sprint 14 — seed_b_amsterdam_demo.py (removed in Sprint 21).
    "tom@b-amsterdam.com",
    "iris@b-amsterdam.com",
    "amanda@b-amsterdam.com",
    "gokhan.kocak@osius.demo",
    "murat.ugurlu@osius.demo",
    "isa.ugurlu@osius.demo",
    # Sprint 21 v1 canonical demo emails — superseded by the v2
    # `<name>-<role>-<tenant>@<tenant>.demo` shape declared in
    # SUPER_ADMIN_USER and COMPANIES below. Adding them here means a
    # local / demo DB that previously ran the v1 seed transitions
    # cleanly to v2 on the first reseed (every v1 row gets soft-
    # deleted; the v2 rows are upserted in the same transaction).
    "super@cleanops.demo",
    "admin@cleanops.demo",
    "gokhan@cleanops.demo",
    "murat@cleanops.demo",
    "isa@cleanops.demo",
    "tom@cleanops.demo",
    "iris@cleanops.demo",
    "amanda@cleanops.demo",
    "admin-b@cleanops.demo",
    "manager-b@cleanops.demo",
    "customer-b@cleanops.demo",
    # Stray real-looking operator super-admin we discovered on the
    # current local demo DB. It is not part of any seed, but it
    # presents as a working SUPER_ADMIN on /admin/users alongside
    # the canonical set, which is confusing during a demo. Pruning
    # it leaves exactly one canonical super admin
    # (superadmin@cleanops.demo).
    "superadmin@osius.demo",
)

# Legacy single-company seed slugs. We deactivate (soft) rather than
# delete because their ID may already be referenced by historical
# tickets or audit rows; flipping `is_active=False` hides the row from
# every non-super-admin scope query, which is what an operator running
# the cleanup actually wants. The canonical Sprint 21 slugs (osius-demo,
# bright-facilities) are intentionally NOT in this list — they are
# upserted back to is_active=True by the seed itself.
LEGACY_COMPANY_SLUGS = (
    "demo-cleaning-bv",         # Sprint 10 seed_demo company
    "demo-cleaning-company",    # pre-Sprint-21 demo_up.sh inline seed
)


# Super admin spans both companies. No CompanyUserMembership row — the
# SUPER_ADMIN role bypasses tenant scoping. Sprint 21 v2 renamed the
# previous `super@cleanops.demo` to `superadmin@cleanops.demo` so the
# email name explicitly signals SUPER_ADMIN scope at a glance.
SUPER_ADMIN_USER = {
    "email": "superadmin@cleanops.demo",
    "full_name": "Super Admin",
    "role": UserRole.SUPER_ADMIN,
    "is_staff": True,
    "is_superuser": True,
    "language": "en",
}


# Two isolated demo companies. Adding a third company is a matter of
# appending another dict here — handle() iterates COMPANIES and never
# special-cases either one. The frontend demo cards and the Playwright
# isolation tests both rely on this same structure (Company A == "Osius
# Demo", Company B == "Bright Facilities"), so reorder with care.
#
# Sprint 21 v2: every persona email is `<name>-<role>-<tenant>@<tenant>.demo`
# so /admin/users shows the role and tenant at a glance. The previous
# v1 emails (super@, admin@, gokhan@, …) are in LEGACY_DEMO_EMAILS so
# a stack that ran v1 transitions cleanly to v2 on first reseed.
# #110 — extra Osius demo buildings so the contact-modal + permissions
# building pickers (the capped-scroll `.multi-select-list` treatment from
# #109 Part F) VISIBLY overflow in the demo. All are created under the
# Osius company and linked to the B Amsterdam customer (via the standard
# customer["buildings"] path), so a ~18-row picker exceeds the ~260-320px
# cap and scrolls. Managers / staff / tickets stay pinned to B1-B3.
_OSIUS_EXTRA_BUILDINGS = [
    f"Bijkantoor {n:02d} Amsterdam" for n in range(4, 19)
]
_OSIUS_ALL_BUILDINGS = [
    "B1 Amsterdam",
    "B2 Amsterdam",
    "B3 Amsterdam",
    *_OSIUS_EXTRA_BUILDINGS,
]

COMPANIES = [
    {
        "name": "Osius Demo",
        "slug": "osius-demo",
        "address": "Maroastraat 3, 1060LG Amsterdam",
        "default_language": "nl",
        "buildings": list(_OSIUS_ALL_BUILDINGS),
        "customer": {
            "name": "B Amsterdam",
            "language": "nl",
            "buildings": list(_OSIUS_ALL_BUILDINGS),
        },
        "company_admin": {
            "email": "ramazan-admin-osius@b-amsterdam.demo",
            "full_name": "Ramazan Uğurlu",
            "language": "en",
        },
        "building_managers": [
            {
                "email": "gokhan-manager-osius@b-amsterdam.demo",
                "full_name": "Gokhan Koçak",
                "buildings": ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
                "language": "en",
            },
            {
                "email": "murat-manager-osius@b-amsterdam.demo",
                "full_name": "Murat Uğurlu",
                "buildings": ["B1 Amsterdam"],
                "language": "en",
            },
            {
                "email": "isa-manager-osius@b-amsterdam.demo",
                "full_name": "İsa Uğurlu",
                "buildings": ["B2 Amsterdam"],
                "language": "en",
            },
        ],
        "customer_users": [
            {
                "email": "tom-customer-b-amsterdam@b-amsterdam.demo",
                "full_name": "Tom Verbeek",
                "buildings": ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
                "language": "nl",
            },
            {
                "email": "iris-customer-b-amsterdam@b-amsterdam.demo",
                "full_name": "Iris",
                "buildings": ["B1 Amsterdam", "B2 Amsterdam"],
                "language": "nl",
            },
            {
                "email": "amanda-customer-b-amsterdam@b-amsterdam.demo",
                "full_name": "Amanda",
                "buildings": ["B3 Amsterdam"],
                "language": "nl",
            },
        ],
        # Sprint 23B: one STAFF persona per company with a
        # StaffProfile and visibility on every building of the
        # company. Lets the demo show the "Request assignment"
        # flow end-to-end without an admin manually wiring it up
        # at boot time.
        "staff": [
            {
                "email": "ahmet-staff-osius@b-amsterdam.demo",
                "full_name": "Ahmet Yıldız",
                "phone": "+31 6 1234 5678",
                "buildings": ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
                "language": "nl",
            },
        ],
        "tickets": [
            {
                "title": f"{DEMO_TICKET_PREFIX} Open lobby light",
                "description": "Lobby light flickers, please replace.",
                "building": "B1 Amsterdam",
                "creator_email": "tom-customer-b-amsterdam@b-amsterdam.demo",
                "type": TicketType.REPORT,
                "priority": TicketPriority.NORMAL,
                "target_status": TicketStatus.OPEN,
            },
            {
                "title": f"{DEMO_TICKET_PREFIX} In progress hallway scuff",
                "description": "Hallway needs touch-up paint after move-in.",
                "building": "B2 Amsterdam",
                "creator_email": "iris-customer-b-amsterdam@b-amsterdam.demo",
                "type": TicketType.REQUEST,
                "priority": TicketPriority.NORMAL,
                "target_status": TicketStatus.IN_PROGRESS,
            },
            {
                "title": f"{DEMO_TICKET_PREFIX} Pantry zeepdispenser",
                "description": (
                    "Zeep en tork 1ste etage — Mycubes meldt dat de "
                    "zeepdispenser en torkrol al weken op zijn."
                ),
                "building": "B3 Amsterdam",
                "creator_email": "amanda-customer-b-amsterdam@b-amsterdam.demo",
                "type": TicketType.REPORT,
                "priority": TicketPriority.HIGH,
                "target_status": TicketStatus.WAITING_CUSTOMER_APPROVAL,
                # Sprint 180 §1 — the work-the-customer-never-answered
                # fixture. Backdates `sent_for_approval_at` so the
                # dashboard's "approval overdue" attention row has
                # something in it on a fresh seed.
                "stalled_approval_days": 21,
            },
            {
                "title": f"{DEMO_TICKET_PREFIX} Closed kitchen tap",
                "description": "Kitchen tap leak resolved last sprint.",
                "building": "B1 Amsterdam",
                "creator_email": "tom-customer-b-amsterdam@b-amsterdam.demo",
                "type": TicketType.REPORT,
                "priority": TicketPriority.NORMAL,
                "target_status": TicketStatus.CLOSED,
            },
        ],
    },
    {
        "name": "Bright Facilities",
        "slug": "bright-facilities",
        "address": "Coolsingel 12, 3011AA Rotterdam",
        "default_language": "nl",
        "buildings": ["R1 Rotterdam", "R2 Rotterdam"],
        "customer": {
            "name": "City Office Rotterdam",
            "language": "nl",
            "buildings": ["R1 Rotterdam", "R2 Rotterdam"],
        },
        "company_admin": {
            "email": "sophie-admin-bright@bright-facilities.demo",
            "full_name": "Sophie van Dijk",
            "language": "en",
        },
        "building_managers": [
            {
                "email": "bram-manager-bright@bright-facilities.demo",
                "full_name": "Bram de Jong",
                "buildings": ["R1 Rotterdam", "R2 Rotterdam"],
                "language": "en",
            },
        ],
        "customer_users": [
            {
                "email": "lotte-customer-bright@bright-facilities.demo",
                "full_name": "Lotte Visser",
                "buildings": ["R1 Rotterdam", "R2 Rotterdam"],
                "language": "nl",
            },
        ],
        # Sprint 23B: one STAFF persona for Bright too, so the
        # demo proves cross-company isolation also applies to
        # STAFF (a STAFF user under Bright cannot reach an Osius
        # ticket even with the same role name).
        "staff": [
            {
                "email": "noah-staff-bright@bright-facilities.demo",
                "full_name": "Noah Bakker",
                "phone": "+31 6 9876 5432",
                "buildings": ["R1 Rotterdam", "R2 Rotterdam"],
                "language": "nl",
            },
        ],
        "tickets": [
            {
                "title": f"{DEMO_TICKET_PREFIX} Reception lights flickering",
                "description": "Reception strip lights need replacement.",
                "building": "R1 Rotterdam",
                "creator_email": "lotte-customer-bright@bright-facilities.demo",
                "type": TicketType.REPORT,
                "priority": TicketPriority.NORMAL,
                "target_status": TicketStatus.OPEN,
            },
            {
                "title": f"{DEMO_TICKET_PREFIX} Lobby floor polish scheduled",
                "description": "Quarterly lobby floor polish — crew on site.",
                "building": "R2 Rotterdam",
                "creator_email": "lotte-customer-bright@bright-facilities.demo",
                "type": TicketType.REQUEST,
                "priority": TicketPriority.NORMAL,
                "target_status": TicketStatus.IN_PROGRESS,
            },
        ],
    },
]


class Command(BaseCommand):
    help = (
        "Seed the canonical Sprint 21 two-company demo dataset (Osius "
        "Demo + Bright Facilities). Dev-only; refuses on "
        "DJANGO_DEBUG=False unless --i-know-this-is-not-prod is set. "
        "Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-tickets",
            action="store_true",
            help=(
                "Delete any pre-existing demo-tagged tickets (titles "
                "starting with [DEMO]) in either company before "
                "re-creating them. Real tickets are never touched."
            ),
        )
        parser.add_argument(
            "--i-know-this-is-not-prod",
            action="store_true",
            help=(
                "Required to run when DJANGO_DEBUG is False. Confirms "
                "the operator is aware this command writes well-known "
                "demo passwords into the database."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG and not options["i_know_this_is_not_prod"]:
            raise CommandError(
                "Refusing to run on DJANGO_DEBUG=False. seed_demo_data "
                "writes well-known demo passwords. To proceed on a "
                "non-prod DEBUG=False stack pass --i-know-this-is-not-prod. "
                "On a real production host, run "
                "`python manage.py check_no_demo_accounts` instead."
            )

        User = get_user_model()
        super_admin = self._upsert_user(User, SUPER_ADMIN_USER)

        # Prune legacy demo rows BEFORE upserting the canonical seed.
        # The canonical accounts share zero email prefixes with the
        # legacy ones, so this ordering cannot accidentally soft-delete
        # a canonical persona. We must, however, run it after creating
        # super_admin so deleted_by can point at a real actor.
        prune_summary = self._prune_legacy_demo_rows(User, super_admin)

        for company_spec in COMPANIES:
            self._seed_company(
                User, super_admin, company_spec, reset_tickets=options["reset_tickets"]
            )

        # Sprint 29 Batch 29.8.5 — the service catalog + one demo Extra
        # Work request that's already operational so the 29.8 frontend
        # surfaces (spawned-tickets panel, IN_PROGRESS auto-trigger,
        # cancel-with-warning) have data to demo against. Both helpers
        # are idempotent.
        #
        self._seed_service_catalog()
        self._seed_demo_extra_work(User, super_admin)

        # #108 Part G — enrich the demo dataset so the Option-A
        # dashboard (hero, "Aandacht nodig", "Mijn werk"), the inbox
        # and the Facturen page all have content on a fresh seed.
        # Idempotent (marker titles / marker message bodies).
        self._seed_owner_batch2_enrichment(User, super_admin)

        # Sprint 179A §6 — the Work Plan's own fixture: dated ticket
        # slots and assigned extra work across several days, states and
        # buildings, so every count chip has a non-zero number and the
        # overdue list has entries. Idempotent, and re-stamps its dates
        # relative to today on every run (see the helper's docstring).
        self._seed_work_plan_demo(User, super_admin)

        self._print_summary(prune_summary=prune_summary)

    # -----------------------------------------------------------------
    # Per-company seed
    # -----------------------------------------------------------------
    def _seed_company(self, User, super_admin, spec, *, reset_tickets):
        company, _ = Company.objects.update_or_create(
            slug=spec["slug"],
            defaults={
                "name": spec["name"],
                "default_language": spec.get("default_language", "nl"),
                "is_active": True,
            },
        )

        buildings = {}
        for name in spec["buildings"]:
            building, _ = Building.objects.update_or_create(
                company=company,
                name=name,
                defaults={
                    "address": spec["address"],
                    "is_active": True,
                },
            )
            buildings[name] = building

        customer_spec = spec["customer"]
        customer = Customer.objects.filter(
            company=company, name=customer_spec["name"], building__isnull=True
        ).first()
        if customer is None:
            customer = Customer.objects.create(
                company=company,
                name=customer_spec["name"],
                building=None,
                contact_email="",
                phone="",
                language=customer_spec.get("language", "nl"),
                is_active=True,
            )
        elif not customer.is_active:
            customer.is_active = True
            customer.save(update_fields=["is_active"])

        for bname in customer_spec["buildings"]:
            CustomerBuildingMembership.objects.get_or_create(
                customer=customer, building=buildings[bname]
            )

        # COMPANY_ADMIN
        admin_spec = spec["company_admin"]
        company_admin = self._upsert_user(
            User,
            {
                "email": admin_spec["email"],
                "full_name": admin_spec["full_name"],
                "role": UserRole.COMPANY_ADMIN,
                "language": admin_spec.get("language", "en"),
            },
        )
        CompanyUserMembership.objects.get_or_create(
            user=company_admin, company=company
        )

        # BUILDING_MANAGER
        for mgr in spec["building_managers"]:
            manager = self._upsert_user(
                User,
                {
                    "email": mgr["email"],
                    "full_name": mgr["full_name"],
                    "role": UserRole.BUILDING_MANAGER,
                    "language": mgr.get("language", "en"),
                },
            )
            for bname in mgr["buildings"]:
                BuildingManagerAssignment.objects.get_or_create(
                    user=manager, building=buildings[bname]
                )

        # CUSTOMER_USER
        customer_user_lookup = {}
        for cu_spec in spec["customer_users"]:
            cu = self._upsert_user(
                User,
                {
                    "email": cu_spec["email"],
                    "full_name": cu_spec["full_name"],
                    "role": UserRole.CUSTOMER_USER,
                    "language": cu_spec.get("language", "nl"),
                },
            )
            membership, _ = CustomerUserMembership.objects.get_or_create(
                customer=customer, user=cu
            )
            for bname in cu_spec["buildings"]:
                CustomerUserBuildingAccess.objects.get_or_create(
                    membership=membership, building=buildings[bname]
                )
            customer_user_lookup[cu_spec["email"]] = cu

        # Sprint 23B — STAFF persona per company. Idempotent: re-runs
        # do not duplicate the StaffProfile or visibility rows. Each
        # staff user gets a phone (so the contact-visibility policy
        # demo actually has something to hide / reveal), a
        # StaffProfile, and BuildingStaffVisibility rows for every
        # building of the company so they can request assignment
        # on any in-company ticket.
        from accounts.models import StaffProfile
        from buildings.models import BuildingStaffVisibility

        for staff_spec in spec.get("staff", []):
            staff_user = self._upsert_user(
                User,
                {
                    "email": staff_spec["email"],
                    "full_name": staff_spec["full_name"],
                    "role": UserRole.STAFF,
                    "language": staff_spec.get("language", "nl"),
                },
            )
            profile, _ = StaffProfile.objects.get_or_create(
                user=staff_user,
                defaults={
                    "phone": staff_spec.get("phone", ""),
                    "can_request_assignment": True,
                    "is_active": True,
                },
            )
            # Keep phone in sync on re-runs so an operator changing
            # the seed value doesn't have to manually update the DB.
            if staff_spec.get("phone") and profile.phone != staff_spec["phone"]:
                profile.phone = staff_spec["phone"]
                profile.save(update_fields=["phone"])
            for bname in staff_spec["buildings"]:
                BuildingStaffVisibility.objects.get_or_create(
                    user=staff_user,
                    building=buildings[bname],
                    defaults={"can_request_assignment": True},
                )

        # Tickets
        if reset_tickets:
            Ticket.objects.filter(
                customer=customer, title__startswith=DEMO_TICKET_PREFIX
            ).delete()

        for tspec in spec["tickets"]:
            existing = Ticket.objects.filter(
                customer=customer, title=tspec["title"]
            ).first()
            if existing is not None:
                # Idempotent: leave the ticket at-or-past the target.
                continue

            building = buildings[tspec["building"]]
            creator = customer_user_lookup.get(tspec["creator_email"])
            if creator is None:
                creator = User.objects.get(email=tspec["creator_email"])

            ticket = Ticket.objects.create(
                company=company,
                building=building,
                customer=customer,
                created_by=creator,
                title=tspec["title"],
                description=tspec["description"],
                type=tspec["type"],
                priority=tspec["priority"],
                status=TicketStatus.OPEN,
            )
            self._walk_to_status(ticket, tspec["target_status"], super_admin)

            # Sprint 180 §1 — a fixture for the "customer never
            # answered" case. Without one, the dashboard's new
            # "approval overdue" attention row reads 0 on every fresh
            # seed and there is nothing to click through: freshly
            # walked tickets were sent for approval seconds ago.
            #
            # Backdating `sent_for_approval_at` directly (rather than
            # walking through a fake clock) is deliberate — it is the
            # one column the age filter reads, and the walk that set it
            # has already written its real history row.
            stalled_days = tspec.get("stalled_approval_days")
            if stalled_days and str(ticket.status) == str(
                TicketStatus.WAITING_CUSTOMER_APPROVAL
            ):
                ticket.sent_for_approval_at = timezone.now() - timedelta(
                    days=stalled_days
                )
                ticket.save(update_fields=["sent_for_approval_at"])

        # Sprint 25C audit-followup — make the demo seed actually
        # exercise the staff workflow features Sprints 23B and 25A
        # added. Without this, an operator on a fresh seed sees an
        # empty /admin/staff-assignment-requests queue and no
        # multi-staff assignments anywhere, so the review and
        # direct-assign UIs cannot be clicked through end-to-end
        # from cold start. The two rows are idempotent (filter-then-
        # create) and CASCADE on Ticket deletion, so --reset-tickets
        # cleans them automatically.
        self._seed_staff_workflow_demo(company, customer, super_admin)

    # -----------------------------------------------------------------
    # Sprint 25C audit-followup — staff workflow demo fixtures
    # -----------------------------------------------------------------
    def _seed_staff_workflow_demo(self, company, customer, super_admin):
        """
        Add one PENDING StaffAssignmentRequest (Sprint 23B flow) and
        one direct TicketStaffAssignment (Sprint 25A flow) to the
        Osius demo so a fresh seed exercises both staff-side paths
        end-to-end.

        Bright Facilities intentionally stays clean: it exists so
        cross-tenant isolation tests can prove that staff in one
        provider company never reach the other's tickets, and adding
        rows on the Bright side would muddy that signal.

        Targets (Osius only):
          * "[DEMO] Open lobby light" (OPEN, B1)  →  PENDING request
            from Ahmet awaiting manager review.
          * "[DEMO] In progress hallway scuff" (IN_PROGRESS, B2)  →
            direct TicketStaffAssignment of Ahmet, assigned_by the
            super admin (mirroring the admin/manager direct-assign
            path).

          The "Pantry zeepdispenser" (WCA) and "Closed kitchen tap"
          (CLOSED) tickets are intentionally LEFT UNTOUCHED — both
          are referenced by Playwright tests that don't expect
          pre-seeded staff assignments. The Sprint 24D pending-
          discovery test's `pickFreshOsiusTicketId` filters out
          tickets that already carry a PENDING for Ahmet or an
          existing assignment to Ahmet, so it falls through to one
          of those two without flakiness.
        """
        if company.slug != "osius-demo":
            return

        User = get_user_model()
        try:
            staff = User.objects.get(
                email="ahmet-staff-osius@b-amsterdam.demo",
                role=UserRole.STAFF,
            )
        except User.DoesNotExist:
            return

        pending_ticket = Ticket.objects.filter(
            customer=customer,
            title=f"{DEMO_TICKET_PREFIX} Open lobby light",
        ).first()
        if pending_ticket is not None:
            has_pending = StaffAssignmentRequest.objects.filter(
                staff=staff,
                ticket=pending_ticket,
                status=AssignmentRequestStatus.PENDING,
            ).exists()
            already_assigned = TicketStaffAssignment.objects.filter(
                ticket=pending_ticket, user=staff
            ).exists()
            if not has_pending and not already_assigned:
                StaffAssignmentRequest.objects.create(
                    staff=staff,
                    ticket=pending_ticket,
                    status=AssignmentRequestStatus.PENDING,
                )

        in_progress_ticket = Ticket.objects.filter(
            customer=customer,
            title=f"{DEMO_TICKET_PREFIX} In progress hallway scuff",
        ).first()
        if in_progress_ticket is not None:
            # Multi-slot per staff (#75) dropped unique_together(ticket,
            # user); get_or_create's .get() would raise
            # MultipleObjectsReturned if this demo ticket already carries
            # 2+ slots for the staff. Create one only if none exists so the
            # re-seed stays idempotent.
            if not TicketStaffAssignment.objects.filter(
                ticket=in_progress_ticket, user=staff
            ).exists():
                TicketStaffAssignment.objects.create(
                    ticket=in_progress_ticket,
                    user=staff,
                    assigned_by=super_admin,
                )

    # -----------------------------------------------------------------
    # Legacy demo cleanup
    # -----------------------------------------------------------------
    def _prune_legacy_demo_rows(self, User, super_admin):
        """
        Soft-deactivate legacy demo personas and their tenancy rows.

        Sprint 21 deleted the legacy `seed_demo` and
        `seed_b_amsterdam_demo` management commands, but any local /
        demo database that ran those commands before the deletion
        still carries their users, their company/building/customer
        memberships, and any tickets they created. Without this prune
        step the `/admin/users` page shows them as live demo personas
        alongside the canonical Sprint 21 set, which defeats the
        purpose of the Sprint 21 cleanup.

        The match is exact-by-email (no domain wildcards) so a real
        operator email can never trip the prune. The Sprint 21 v2
        canonical addresses live under two non-routable demo TLDs
        (`@cleanops.demo` for the super admin, `@b-amsterdam.demo`
        for Osius Demo personas, `@bright-facilities.demo` for
        Bright Facilities personas), and every v2 email starts with
        the persona's first name — none of which collide with any
        LEGACY_DEMO_EMAILS entry. This method therefore cannot
        accidentally soft-delete a canonical v2 account.

        Returns a small summary dict so the operator-facing output of
        seed_demo_data shows how many rows were touched.
        """
        targets = list(User.objects.filter(email__in=LEGACY_DEMO_EMAILS))
        if not targets:
            self._prune_legacy_companies()
            return {
                "users": 0,
                "tickets": 0,
                "company_memberships": 0,
                "manager_assignments": 0,
                "customer_memberships": 0,
                "customer_user_building_access": 0,
                "companies_deactivated": 0,
            }

        target_ids = [u.id for u in targets]

        # Step 1: drop every membership/assignment that ties the
        # legacy users into a tenant. Customer-user-building-access
        # rows hang off CustomerUserMembership, so we delete those
        # first via the membership FK.
        access_count = CustomerUserBuildingAccess.objects.filter(
            membership__user_id__in=target_ids
        ).count()
        CustomerUserBuildingAccess.objects.filter(
            membership__user_id__in=target_ids
        ).delete()

        cu_count = CustomerUserMembership.objects.filter(
            user_id__in=target_ids
        ).count()
        CustomerUserMembership.objects.filter(
            user_id__in=target_ids
        ).delete()

        mgr_count = BuildingManagerAssignment.objects.filter(
            user_id__in=target_ids
        ).count()
        BuildingManagerAssignment.objects.filter(
            user_id__in=target_ids
        ).delete()

        comp_count = CompanyUserMembership.objects.filter(
            user_id__in=target_ids
        ).count()
        CompanyUserMembership.objects.filter(
            user_id__in=target_ids
        ).delete()

        # Step 2: delete any legacy tickets the legacy users created.
        # Real demo activity uses the canonical [DEMO]-prefixed
        # titles seeded against the canonical customers, never these
        # legacy users — so a delete here can only remove legacy
        # rows. We do an unconditional delete on `created_by` because
        # the legacy tickets carry no marker prefix and may live in
        # the legacy "Demo Cleaning BV" company.
        ticket_count = Ticket.objects.filter(
            created_by_id__in=target_ids
        ).count()
        Ticket.objects.filter(created_by_id__in=target_ids).delete()

        # Step 3: soft-delete the users themselves. We use the model's
        # own soft_delete() so deleted_at + deleted_by + is_active are
        # all set consistently with the rest of the codebase.
        now = timezone.now()
        for user in targets:
            user.is_active = False
            if user.deleted_at is None:
                user.deleted_at = now
            if user.deleted_by_id is None:
                user.deleted_by = super_admin
            user.save(update_fields=["is_active", "deleted_at", "deleted_by"])

        # Step 4: deactivate legacy single-company seed slugs (the
        # canonical osius-demo / bright-facilities slugs are NOT in
        # LEGACY_COMPANY_SLUGS, so this cannot deactivate them).
        companies_deactivated = self._prune_legacy_companies()

        return {
            "users": len(targets),
            "tickets": ticket_count,
            "company_memberships": comp_count,
            "manager_assignments": mgr_count,
            "customer_memberships": cu_count,
            "customer_user_building_access": access_count,
            "companies_deactivated": companies_deactivated,
        }

    def _prune_legacy_companies(self):
        """Flip is_active=False on legacy single-company seed slugs."""
        count = 0
        for slug in LEGACY_COMPANY_SLUGS:
            updated = Company.objects.filter(
                slug=slug, is_active=True
            ).update(is_active=False)
            count += updated
        return count

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------
    def _upsert_user(self, User, spec):
        """
        Create or refresh a demo user. Always sets the demo password,
        so a re-run after a manual password change resets it back to
        the documented value.
        """
        defaults = {
            "full_name": spec["full_name"],
            "role": spec["role"],
            "language": spec.get("language", "nl"),
            "is_active": True,
            "is_staff": spec.get("is_staff", False),
            "is_superuser": spec.get("is_superuser", False),
        }
        user, _ = User.objects.get_or_create(
            email=spec["email"], defaults=defaults
        )
        dirty_fields = []
        for k, v in defaults.items():
            if getattr(user, k) != v:
                setattr(user, k, v)
                dirty_fields.append(k)
        # Clear any prior soft-delete so re-running the seed against a
        # soft-deleted user reactivates them deterministically.
        if getattr(user, "deleted_at", None) is not None:
            user.deleted_at = None
            dirty_fields.append("deleted_at")
        if dirty_fields:
            user.save(update_fields=dirty_fields)
        user.set_password(DEMO_PASSWORD)
        user.save(update_fields=["password"])
        return user

    def _walk_to_status(self, ticket, target_status, super_admin):
        """
        Walk a freshly-created OPEN ticket to the target status using
        apply_transition so timestamps and TicketStatusHistory rows
        populate correctly. Uses the super admin actor — they can
        perform any transition without the per-role scope checks.

        Sprint 180 §1 — the customer-approval leg
        (WAITING_CUSTOMER_APPROVAL -> APPROVED) auto-closes now, which
        breaks two assumptions this walk used to make: the ticket can
        overshoot the hop it was asked for, and the old unconditional
        CLOSED hop would then re-drive an already-CLOSED ticket and
        raise `no_op_transition`, aborting the entire seed. So the path
        is chosen per target instead of being one list with an early
        return.
        """
        if str(target_status) == str(TicketStatus.OPEN):
            return

        if str(target_status) == str(TicketStatus.APPROVED):
            # A fixture parked on APPROVED is, after Sprint 180, by
            # definition one that NO customer approved — every customer
            # approval closes. The super admin's cross-status privilege
            # produces exactly that: an administrative APPROVED with no
            # customer decision behind it, which is a real state the
            # auto-close deliberately leaves alone (see
            # `tickets.auto_close.should_auto_close`).
            path = [TicketStatus.IN_PROGRESS, TicketStatus.APPROVED]
        else:
            path = [
                TicketStatus.IN_PROGRESS,
                TicketStatus.WAITING_CUSTOMER_APPROVAL,
                TicketStatus.APPROVED,
                TicketStatus.CLOSED,
            ]

        for stop in path:
            # The APPROVED hop auto-closes, so the ticket may already BE
            # the next hop; re-driving it would raise `no_op_transition`.
            if str(ticket.status) == str(stop):
                continue
            # Sprint 27F-B1 — provider-driven customer-decision transitions
            # (WAITING_CUSTOMER_APPROVAL → APPROVED/REJECTED) are now coerced
            # to is_override=True with a mandatory reason. The seed walks
            # tickets through APPROVED as super_admin to build fixtures, so
            # pass a fixture-marker reason on every hop (no-op on hops the
            # coercion doesn't touch).
            ticket = apply_transition(
                ticket,
                super_admin,
                stop,
                note=f"seed_demo_data → {stop}",
                override_reason="seed_demo_data fixture walk",
            )
            # Compare against the ticket's ACTUAL status, not against the
            # hop we asked for: Sprint 180's auto-close means the APPROVED
            # hop can land on CLOSED, which is the target for every
            # `target_status=CLOSED` spec in this file.
            if str(ticket.status) == str(target_status):
                return

    # -----------------------------------------------------------------
    # Sprint 29 Batch 29.8.5 — per-company service catalog
    # -----------------------------------------------------------------
    def _seed_service_catalog(self, primary_company=None):
        """
        Idempotently upsert a small but realistic provider-side service
        catalog (4 categories, 14 services) for ONE provider company.

        Sprint 142 — `ServiceCategory` gained a `company` FK, so the
        header above ("provider-global") and the paragraph that said the
        catalog "is NOT scoped per-company" are both false now:
        categories are scoped exactly like the services under them, and
        both are pinned to `primary_company` below. Seeding stays a
        once-per-`handle()` pass because the demo fixture only needs one
        provider's catalog, not because the rows are shared.

        Imported here (not at module top) to keep the seed command's
        boot time fast for stacks that don't run extra_work, and to
        match the lazy-import style used for `accounts.StaffProfile`
        in `_seed_company`.
        """
        from decimal import Decimal

        from extra_work.models import (
            ExtraWorkPricingUnitType,
            Service,
            ServiceCategory,
        )

        catalog = [
            (
                "Cleaning",
                "Regular cleaning services across customer premises.",
                [
                    ("Standard cleaning shift", ExtraWorkPricingUnitType.HOURS, Decimal("32.50")),
                    ("Deep cleaning", ExtraWorkPricingUnitType.HOURS, Decimal("42.00")),
                    ("Carpet shampoo", ExtraWorkPricingUnitType.SQUARE_METERS, Decimal("4.75")),
                    ("Floor strip and seal", ExtraWorkPricingUnitType.SQUARE_METERS, Decimal("7.25")),
                ],
            ),
            (
                "Windows & Glass",
                "Window, glass and façade cleaning.",
                [
                    ("Interior window cleaning", ExtraWorkPricingUnitType.SQUARE_METERS, Decimal("3.50")),
                    ("Exterior window cleaning", ExtraWorkPricingUnitType.SQUARE_METERS, Decimal("5.50")),
                    ("Glass partition polish", ExtraWorkPricingUnitType.HOURS, Decimal("36.00")),
                ],
            ),
            (
                "Sanitary & Consumables",
                "Sanitary maintenance and consumable refills.",
                [
                    ("Sanitary deep clean", ExtraWorkPricingUnitType.HOURS, Decimal("38.00")),
                    ("Consumables refill — standard", ExtraWorkPricingUnitType.FIXED, Decimal("85.00")),
                    ("Soap dispenser replacement", ExtraWorkPricingUnitType.ITEM, Decimal("45.00")),
                    ("Hand-towel dispenser swap", ExtraWorkPricingUnitType.ITEM, Decimal("55.00")),
                ],
            ),
            (
                "Specialty",
                "Specialty and one-off services.",
                [
                    ("Event setup cleaning", ExtraWorkPricingUnitType.HOURS, Decimal("45.00")),
                    ("Waste removal — small van", ExtraWorkPricingUnitType.FIXED, Decimal("125.00")),
                    ("Emergency call-out", ExtraWorkPricingUnitType.HOURS, Decimal("75.00")),
                ],
            ),
        ]

        # Sprint 3B — Service is provider-scoped. Pin every seeded
        # row to a primary Company. If the caller did not pass one,
        # fall back to the first Company in the DB; if there is no
        # Company yet, skip the catalog seed entirely (the
        # `_seed_company` pass that ran first would normally have
        # created it).
        if primary_company is None:
            primary_company = Company.objects.order_by("id").first()
        if primary_company is None:
            self._service_catalog_counts = {"categories": 0, "services": 0}
            self._service_catalog_company = None
            return

        # Sprint 142 — remember WHICH company the catalog was seeded
        # under. Categories are company-scoped now, so the demo-EW
        # lookup below can no longer match a category by name alone.
        self._service_catalog_company = primary_company

        cat_count = 0
        svc_count = 0
        for cat_name, cat_description, services in catalog:
            # Sprint 142 — `company` is part of the lookup, not the
            # defaults: it is half of the row's identity now (uniqueness
            # is per-company), and it is NOT NULL, so an omitted key
            # would raise on the create branch.
            category, _ = ServiceCategory.objects.update_or_create(
                company=primary_company,
                name=cat_name,
                defaults={"description": cat_description, "is_active": True},
            )
            cat_count += 1
            for svc_name, unit_type, default_price in services:
                Service.objects.update_or_create(
                    company=primary_company,
                    category=category,
                    name=svc_name,
                    defaults={
                        "unit_type": unit_type,
                        "default_unit_price": default_price,
                        "default_vat_pct": Decimal("21.00"),
                        "is_active": True,
                    },
                )
                svc_count += 1

        self._service_catalog_counts = {
            "categories": cat_count,
            "services": svc_count,
        }

    # -----------------------------------------------------------------
    # Sprint 29 Batch 29.8.5 — demo Extra Work request with spawned tickets
    # -----------------------------------------------------------------
    def _seed_demo_extra_work(self, User, super_admin):
        """
        Create one demo Extra Work request that's already operational
        (CUSTOMER_APPROVED with spawned tickets, then driven to
        IN_PROGRESS via a ticket transition). This is the fixture the
        Sprint 29 Batch 29.8 frontend surfaces need to demo:
          * the operational-segment status badge (IN_PROGRESS),
          * the "Spawned tickets" panel,
          * the cancel-with-warning UX,
          * the auto-trigger that lifts the parent EW into IN_PROGRESS
            when its first spawned ticket enters IN_PROGRESS.

        Uses the INSTANT routing path:
          1. Seed a `CustomerServicePrice` row for the B Amsterdam
             customer on a Cleaning catalog service.
          2. Create the request directly in `CUSTOMER_APPROVED` state
             with one `ExtraWorkRequestItem` line pointing at that
             service.
          3. Call `spawn_tickets_for_request` to create the operational
             tickets attached to the line item.
          4. Drive one of the spawned tickets to IN_PROGRESS via
             `tickets.state_machine.apply_transition`. The
             29.8 auto-sync hook then lifts the parent EW to
             IN_PROGRESS automatically.

        We bypass the serializer path (which would re-run the price
        resolver) because the seed needs deterministic state — the
        INSTANT route requires `routing_decision=INSTANT` which the
        serializer computes from the resolver. By writing the rows
        directly we sidestep the timing dependency on `date.today()`
        falling inside the contract window.

        Idempotency guard: a marker title ensures a re-run does not
        create duplicates. If the lookup for any required actor or
        building fails, the helper logs a warning and returns without
        crashing the seed.
        """
        # Lazy imports — same rationale as `_seed_service_catalog`.
        from datetime import date, timedelta
        from decimal import Decimal

        from extra_work.instant_tickets import spawn_tickets_for_request
        from extra_work.models import (
            CustomerServicePrice,
            ExtraWorkCategory,
            ExtraWorkRequest,
            ExtraWorkRequestItem,
            ExtraWorkRoutingDecision,
            ExtraWorkStatus,
            Service,
        )
        from tickets.models import Ticket, TicketStatus
        from tickets.state_machine import apply_transition as ticket_apply

        demo_marker = "[DEMO] Lobby strip and seal (29.8.5)"

        # Resolve the Osius demo company by slug — keeps the lookup
        # decoupled from any rename of `COMPANIES` in this file.
        company = Company.objects.filter(slug="osius-demo").first()
        if company is None:
            self.stdout.write(self.style.WARNING(
                "seed_demo_data: skipping demo Extra Work — osius-demo "
                "company not found."
            ))
            return

        building = Building.objects.filter(
            company=company, name="B1 Amsterdam"
        ).first()
        if building is None:
            self.stdout.write(self.style.WARNING(
                "seed_demo_data: skipping demo Extra Work — B1 Amsterdam "
                "building not found."
            ))
            return

        customer = Customer.objects.filter(
            company=company, name="B Amsterdam"
        ).first()
        if customer is None:
            self.stdout.write(self.style.WARNING(
                "seed_demo_data: skipping demo Extra Work — B Amsterdam "
                "customer not found."
            ))
            return

        creator = User.objects.filter(
            email="tom-customer-b-amsterdam@b-amsterdam.demo"
        ).first()
        if creator is None:
            self.stdout.write(self.style.WARNING(
                "seed_demo_data: skipping demo Extra Work — Tom (creator) "
                "not found."
            ))
            return

        # Pick a service from the catalog seeded by
        # `_seed_service_catalog` above. Use "Floor strip and seal" to
        # match the demo marker title; fall back to the first Cleaning
        # service if it's missing (e.g. an operator renamed it).
        # Sprint 142 — both lookups are narrowed to the company the
        # catalog was actually seeded under (`_seed_service_catalog`
        # records it). `category__name="Cleaning"` alone stopped being
        # unambiguous this sprint: category names are unique PER COMPANY
        # now, so on a multi-company DB several providers may each have
        # a "Cleaning" and the fallback could pick a foreign one.
        #
        # NB this is deliberately the CATALOG's company, not `company`
        # (the osius-demo tenant the EW itself belongs to). Those two
        # already differ on a multi-company DB, and the resulting
        # cross-company `CustomerServicePrice` below predates this
        # sprint — reconciling the demo fixture is recorded in the
        # checklist rather than smuggled into a scoping sprint, because
        # it would re-target the seeded catalog to a different company
        # than existing dev DBs already have it under.
        catalog_company = getattr(self, "_service_catalog_company", None)
        catalog_scope = (
            {"company": catalog_company} if catalog_company else {}
        )
        service = (
            Service.objects.filter(
                **catalog_scope, name="Floor strip and seal"
            ).first()
            or Service.objects.filter(
                **catalog_scope, category__name="Cleaning"
            ).first()
        )
        if service is None:
            self.stdout.write(self.style.WARNING(
                "seed_demo_data: skipping demo Extra Work — no catalog "
                "service available (run _seed_service_catalog first)."
            ))
            return

        # Idempotency: skip if the demo EW already exists.
        if ExtraWorkRequest.objects.filter(
            company=company, title=demo_marker
        ).exists():
            self._demo_extra_work_summary = {
                "skipped": True,
                "title": demo_marker,
            }
            return

        # Contract-price row valid from yesterday onward so the
        # `resolve_price` call at spawn time succeeds regardless of
        # the seed's calendar day. The 29.8.5 demo EW uses a fixed
        # requested date one day in the future (well within the
        # open-ended contract window).
        today = date.today()
        CustomerServicePrice.objects.update_or_create(
            service=service,
            customer=customer,
            valid_from=today - timedelta(days=1),
            defaults={
                "unit_price": Decimal("7.25"),
                "vat_pct": Decimal("21.00"),
                "valid_to": None,
                "is_active": True,
            },
        )

        # Create the parent EW directly in CUSTOMER_APPROVED state.
        # The serializer path would compute routing_decision via
        # resolve_price; for the seed we write it explicitly so the
        # downstream spawn helper accepts the row regardless of date
        # drift in CI / dev environments.
        ew = ExtraWorkRequest.objects.create(
            company=company,
            building=building,
            customer=customer,
            created_by=creator,
            title=demo_marker,
            description=(
                "Lobby floor strip-and-seal job. Auto-approved via "
                "customer-specific contract price. Seeded by "
                "seed_demo_data (Sprint 29 Batch 29.8.5) so the "
                "operational-segment UI has demoable data."
            ),
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
        )

        requested_date = today + timedelta(days=1)
        line = ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=service,
            quantity=Decimal("120.00"),
            unit_type=service.unit_type,
            requested_date=requested_date,
            customer_note="Lobby floor — full strip + double seal coat.",
        )

        # Spawn operational tickets. The helper drives REQUESTED ->
        # CUSTOMER_APPROVED on success (writing the parent status +
        # history row directly, mirroring the production INSTANT path).
        # MUST be wrapped in an atomic block per the helper's contract;
        # we already run inside the seed's @transaction.atomic, so the
        # call is safe.
        spawned = spawn_tickets_for_request(ew, actor=creator)

        spawned_count = len(spawned)
        ew.refresh_from_db()

        # Drive one spawned ticket to IN_PROGRESS so the 29.8 auto-sync
        # hook lifts the parent EW into IN_PROGRESS. Pick the first
        # ticket and walk OPEN -> IN_PROGRESS. The super_admin actor
        # bypasses scope checks.
        ticket_statuses: list[tuple[int, str]] = []
        if spawned:
            first = spawned[0]
            ticket_apply(
                first,
                super_admin,
                TicketStatus.IN_PROGRESS,
                note="seed_demo_data — demo IN_PROGRESS for 29.8 UI",
            )
            ew.refresh_from_db()

            for t in Ticket.objects.filter(
                extra_work_request_item=line
            ).order_by("id"):
                ticket_statuses.append((t.id, t.status))

        self._demo_extra_work_summary = {
            "skipped": False,
            "ew_id": ew.id,
            "title": demo_marker,
            "status": ew.status,
            "spawned_count": spawned_count,
            "ticket_statuses": ticket_statuses,
        }

    # -----------------------------------------------------------------
    # #108 Part G — owner-batch-2 enrichment
    # -----------------------------------------------------------------
    def _seed_owner_batch2_enrichment(self, User, super_admin):
        """
        Enrich the Osius demo so the #108 surfaces have content on a
        fresh seed:

          * "Aandacht nodig" — a WAITING_MANAGER_REVIEW ticket, extra
            unassigned OPEN tickets, an EW awaiting pricing
            (UNDER_REVIEW) and an EW awaiting the customer decision
            (PRICING_PROPOSED, proposal SENT through the real proposal
            state machine).
          * "Mijn werk" — tickets / a melding / EW / a quote request
            created by the provider personas (super admin + Ramazan).
          * Billing history — two PAST months plus the CURRENT month
            with completed (spawned ticket CLOSED = earned), finalized
            (actual_hours + recompute_final_amounts) and
            invoice_date-set EWs; the OLDEST month is marked invoiced
            using the same is_earned/billing_month predicates the
            invoice run applies. Facturen shows history; the dashboard
            month widget shows non-zero open EUR.
          * Notifications + unread messages — real emit_* fan-out for
            the workflow events and a handful of ticket/EW messages
            across roles (customer -> provider and provider ->
            customer), so the feed, the inbox badge and "Recente
            activiteit" are populated.

        Idempotent: every created row is guarded by a stable marker
        title (tickets / EW) or marker message body. Snapshot prices
        come from CustomerServicePrice rows and every state mutation
        goes through the real state machines / spawn helper.
        """
        from datetime import date, timedelta
        from decimal import Decimal

        from extra_work.instant_tickets import spawn_tickets_for_request
        from extra_work.models import (
            CustomerServicePrice,
            ExtraWorkCategory,
            ExtraWorkMessage,
            ExtraWorkMessageType,
            ExtraWorkMessageVisibility,
            ExtraWorkRequest,
            ExtraWorkRequestIntent,
            ExtraWorkRequestItem,
            ExtraWorkRoutingDecision,
            ExtraWorkStatus,
            Proposal,
            ProposalLine,
            ProposalStatus,
            Service,
        )
        from extra_work.billing import billing_month, build_ticket_map, is_earned
        from extra_work.classification import classify_line
        from extra_work.proposal_state_machine import (
            apply_proposal_transition,
        )
        from extra_work.state_machine import apply_transition as ew_apply
        from notifications.services import (
            emit_extra_work_message_notifications,
            emit_extra_work_proposal_sent_notifications,
            emit_extra_work_requested_notifications,
            emit_ticket_message_notifications,
        )
        from tickets.models import (
            TicketMessage,
            TicketMessageType,
            TicketMessageVisibility,
        )
        from tickets.state_machine import apply_transition as ticket_apply

        summary = {
            "tickets": 0,
            "extra_work": 0,
            "billing_months": [],
            "invoiced_month": None,
            "messages": 0,
            "skipped": [],
        }

        company = Company.objects.filter(slug="osius-demo").first()
        customer = (
            Customer.objects.filter(company=company, name="B Amsterdam").first()
            if company
            else None
        )
        b1 = Building.objects.filter(company=company, name="B1 Amsterdam").first()
        b2 = Building.objects.filter(company=company, name="B2 Amsterdam").first()
        ramazan = User.objects.filter(
            email="ramazan-admin-osius@b-amsterdam.demo"
        ).first()
        tom = User.objects.filter(
            email="tom-customer-b-amsterdam@b-amsterdam.demo"
        ).first()
        if not all([company, customer, b1, b2, ramazan, tom]):
            self.stdout.write(self.style.WARNING(
                "seed_demo_data: skipping owner-batch-2 enrichment — "
                "Osius demo fixtures incomplete."
            ))
            return

        def _stamped_item_kwargs(service, requested_date):
            """Sprint 2A snapshot stamping via the REAL classifier —
            byte-identical to the cart-create serializer's write, so
            agreed-priced lines carry snapshot_unit_price/_vat_pct and
            recompute_final_amounts produces real money."""
            c = classify_line(
                service=service,
                customer=customer,
                requested_date=requested_date,
                custom_description="",
            )
            return {
                "line_price_source": c.source,
                "snapshot_unit_price": c.snapshot_unit_price,
                "snapshot_vat_pct": c.snapshot_vat_pct,
                "snapshot_service_name": c.snapshot_service_name,
                "snapshot_service_category_name": (
                    c.snapshot_service_category_name
                ),
                "snapshot_customer_service_price": c.contract,
            }

        # ---- (1) Attention-list + "Mijn werk" tickets ----------------
        # (title, building, creator, type, target status)
        ticket_specs = [
            (
                f"{DEMO_TICKET_PREFIX} Te bevestigen — trappenhuis kelder",
                b1,
                ramazan,
                TicketType.REQUEST,
                TicketStatus.WAITING_MANAGER_REVIEW,
            ),
            (
                f"{DEMO_TICKET_PREFIX} Melding — koffiehoek bijvullen",
                b2,
                super_admin,
                TicketType.REPORT,
                TicketStatus.OPEN,
            ),
            (
                f"{DEMO_TICKET_PREFIX} Inspectie plantenbakken atrium",
                b1,
                super_admin,
                TicketType.REQUEST,
                TicketStatus.OPEN,
            ),
        ]
        for title, building, creator, ttype, target in ticket_specs:
            if Ticket.objects.filter(customer=customer, title=title).exists():
                summary["skipped"].append(title)
                continue
            ticket = Ticket.objects.create(
                company=company,
                building=building,
                customer=customer,
                created_by=creator,
                title=title,
                description=f"Seeded by seed_demo_data (#108 Part G): {title}",
                type=ttype,
                priority=TicketPriority.NORMAL,
                status=TicketStatus.OPEN,
            )
            if target == TicketStatus.WAITING_MANAGER_REVIEW:
                ticket = ticket_apply(
                    ticket,
                    super_admin,
                    TicketStatus.IN_PROGRESS,
                    note="seed #108 Part G",
                )
                ticket_apply(
                    ticket,
                    super_admin,
                    TicketStatus.WAITING_MANAGER_REVIEW,
                    note="seed #108 Part G — awaiting manager review",
                )
            summary["tickets"] += 1

        # ---- (2) EW awaiting pricing (UNDER_REVIEW) -------------------
        # Same lookup style as _seed_demo_extra_work: by name first,
        # cheapest-id fallback. Deliberately NOT company-filtered — on a
        # long-lived dev DB the catalog may be pinned to an older first
        # company (the seed's _seed_service_catalog picks
        # Company.objects.order_by("id").first()).
        svc_specialty = (
            Service.objects.filter(name="Emergency call-out").first()
            or Service.objects.order_by("id").first()
        )
        ew_pricing_title = f"{DEMO_TICKET_PREFIX} Wacht op prijs — gevelreiniging"
        if svc_specialty and not ExtraWorkRequest.objects.filter(
            company=company, title=ew_pricing_title
        ).exists():
            ew = ExtraWorkRequest.objects.create(
                company=company,
                building=b1,
                customer=customer,
                created_by=tom,
                title=ew_pricing_title,
                description="Gevel oostzijde reinigen na waterschade.",
                category=ExtraWorkCategory.DEEP_CLEANING,
                status=ExtraWorkStatus.REQUESTED,
                routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
            )
            ExtraWorkRequestItem.objects.create(
                extra_work_request=ew,
                service=svc_specialty,
                quantity=Decimal("8.00"),
                unit_type=svc_specialty.unit_type,
                requested_date=date.today() + timedelta(days=7),
                customer_note="Graag buiten kantooruren.",
                **_stamped_item_kwargs(
                    svc_specialty, date.today() + timedelta(days=7)
                ),
            )
            ew = ew_apply(ew, super_admin, ExtraWorkStatus.UNDER_REVIEW,
                          note="seed #108 Part G — awaiting pricing")
            emit_extra_work_requested_notifications(ew, actor=tom)
            summary["extra_work"] += 1
        else:
            summary["skipped"].append(ew_pricing_title)

        # ---- (3) EW awaiting customer decision (PRICING_PROPOSED) ----
        svc_carpet = (
            Service.objects.filter(name="Carpet shampoo").first()
            or svc_specialty
        )
        ew_sent_title = f"{DEMO_TICKET_PREFIX} Offerte verstuurd — tapijtreiniging"
        if svc_carpet and not ExtraWorkRequest.objects.filter(
            company=company, title=ew_sent_title
        ).exists():
            ew = ExtraWorkRequest.objects.create(
                company=company,
                building=b2,
                customer=customer,
                created_by=super_admin,
                title=ew_sent_title,
                description=(
                    "Tapijt 2e etage dieptereiniging — omgezet vanuit een "
                    "melding door de provider."
                ),
                category=ExtraWorkCategory.DEEP_CLEANING,
                status=ExtraWorkStatus.REQUESTED,
                routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
            )
            ExtraWorkRequestItem.objects.create(
                extra_work_request=ew,
                service=svc_carpet,
                quantity=Decimal("85.00"),
                unit_type=svc_carpet.unit_type,
                requested_date=date.today() + timedelta(days=10),
                customer_note="",
                **_stamped_item_kwargs(
                    svc_carpet, date.today() + timedelta(days=10)
                ),
            )
            ew = ew_apply(ew, super_admin, ExtraWorkStatus.UNDER_REVIEW,
                          note="seed #108 Part G")
            proposal = Proposal.objects.create(
                extra_work_request=ew,
                status=ProposalStatus.DRAFT,
                created_by=ramazan,
            )
            ProposalLine.objects.create(
                proposal=proposal,
                service=svc_carpet,
                description="",
                quantity=Decimal("85.00"),
                unit_type=svc_carpet.unit_type,
                unit_price=Decimal("4.75"),
                vat_pct=Decimal("21.00"),
                customer_explanation="Inclusief meubels verplaatsen.",
                internal_note="Marge gecontroleerd — standaardtarief.",
            )
            proposal.recompute_totals()
            apply_proposal_transition(
                proposal, ramazan, ProposalStatus.SENT,
                note="seed #108 Part G — proposal sent",
            )
            ew.refresh_from_db()
            emit_extra_work_proposal_sent_notifications(ew, actor=ramazan)
            summary["extra_work"] += 1
        else:
            summary["skipped"].append(ew_sent_title)

        # ---- (4) Provider quote request ("Mijn werk" — Offertes) -----
        ew_quote_title = (
            f"{DEMO_TICKET_PREFIX} Offerteaanvraag — glazen scheidingswand"
        )
        if svc_specialty and not ExtraWorkRequest.objects.filter(
            company=company, title=ew_quote_title
        ).exists():
            ew = ExtraWorkRequest.objects.create(
                company=company,
                building=b1,
                customer=customer,
                created_by=super_admin,
                title=ew_quote_title,
                description="Prijsindicatie gevraagd voor glazen wand begane grond.",
                category=ExtraWorkCategory.OTHER,
                category_other_text="Glazen scheidingswand plaatsen",
                status=ExtraWorkStatus.REQUESTED,
                routing_decision=ExtraWorkRoutingDecision.PROPOSAL,
                request_intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
            )
            ExtraWorkRequestItem.objects.create(
                extra_work_request=ew,
                service=svc_specialty,
                quantity=Decimal("1.00"),
                unit_type=svc_specialty.unit_type,
                requested_date=date.today() + timedelta(days=21),
                customer_note="",
                **_stamped_item_kwargs(
                    svc_specialty, date.today() + timedelta(days=21)
                ),
            )
            summary["extra_work"] += 1
        else:
            summary["skipped"].append(ew_quote_title)

        # ---- (5) Billing history — two past months + current month ---
        svc_deep = (
            Service.objects.filter(name="Deep cleaning").first()
            or svc_specialty
        )
        today = date.today()

        def _month_shift(base: date, months_back: int) -> date:
            y, m = base.year, base.month - months_back
            while m <= 0:
                y -= 1
                m += 12
            return date(y, m, 1)

        billing_targets = [_month_shift(today, 2), _month_shift(today, 1),
                           date(today.year, today.month, 1)]
        if svc_deep:
            # One open-ended contract row valid before the OLDEST month
            # so resolve_price succeeds for every requested_date below.
            CustomerServicePrice.objects.update_or_create(
                service=svc_deep,
                customer=customer,
                valid_from=billing_targets[0] - timedelta(days=15),
                defaults={
                    "unit_price": Decimal("42.00"),
                    "vat_pct": Decimal("21.00"),
                    "valid_to": None,
                    "is_active": True,
                },
            )
        for month_start in billing_targets:
            label = f"{month_start.year}-{month_start.month:02d}"
            title = f"{DEMO_TICKET_PREFIX} Facturatie {label} — dieptereiniging"
            if svc_deep is None or ExtraWorkRequest.objects.filter(
                company=company, title=title
            ).exists():
                summary["skipped"].append(title)
                continue
            ew = ExtraWorkRequest.objects.create(
                company=company,
                building=b2,
                customer=customer,
                created_by=tom,
                title=title,
                description=f"Maandelijkse dieptereiniging ({label}).",
                category=ExtraWorkCategory.DEEP_CLEANING,
                status=ExtraWorkStatus.REQUESTED,
                routing_decision=ExtraWorkRoutingDecision.INSTANT,
            )
            item_date = min(month_start + timedelta(days=9), today)
            item = ExtraWorkRequestItem.objects.create(
                extra_work_request=ew,
                service=svc_deep,
                quantity=Decimal("6.00"),
                unit_type=svc_deep.unit_type,
                requested_date=item_date,
                customer_note="",
                **_stamped_item_kwargs(svc_deep, item_date),
            )
            spawned = spawn_tickets_for_request(ew, actor=tom)
            # Finalized: actual hours entered + final_* recomputed via
            # the real recompute helper. MUST happen before the ticket
            # walk — the Sprint 8B completion gate blocks
            # IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL while an hourly
            # line still lacks actual_hours.
            item.actual_hours = Decimal("6.50")
            item.actual_hours_entered_by = super_admin
            item.actual_hours_entered_at = timezone.now()
            item.save(update_fields=[
                "actual_hours",
                "actual_hours_entered_by",
                "actual_hours_entered_at",
            ])
            ew.refresh_from_db()
            ew.recompute_final_amounts()
            # Completed: drive the spawned ticket to CLOSED so the EW
            # is EARNED (the invoice run's own predicate).
            #
            # Sprint 180 §1 — the APPROVED hop auto-closes, so the
            # CLOSED hop below usually finds the ticket already there;
            # driving it again would raise `no_op_transition` and abort
            # the seed. The hop is kept (rather than deleted) so this
            # fixture still reaches CLOSED if the auto-close is ever
            # narrowed — it is the CLOSED status, not the route to it,
            # that `extra_work.billing.is_earned` cares about.
            for spawned_ticket in spawned:
                t = spawned_ticket
                for stop in (
                    TicketStatus.IN_PROGRESS,
                    TicketStatus.WAITING_CUSTOMER_APPROVAL,
                    TicketStatus.APPROVED,
                    TicketStatus.CLOSED,
                ):
                    if str(t.status) == str(stop):
                        continue
                    t = ticket_apply(
                        t,
                        super_admin,
                        stop,
                        note=f"seed #108 Part G — billing fixture {label}",
                        override_reason="seed #108 Part G billing fixture",
                    )
            ew.refresh_from_db()
            # Billing month pinned via the provider-set invoice_date
            # (COALESCE(invoice_date, completion) — M4 rule).
            ew.invoice_date = month_start + timedelta(days=24)
            ew.save(update_fields=["invoice_date", "updated_at"])
            summary["billing_months"].append(label)

        # Mark the OLDEST month invoiced with the SAME predicates the
        # invoice run uses (earned + bills-in-month + not yet invoiced).
        oldest = billing_targets[0]
        oldest_key = (oldest.year, oldest.month)
        ew_list = list(
            ExtraWorkRequest.objects.filter(
                company=company, deleted_at__isnull=True
            )
        )
        ticket_map = build_ticket_map([e.id for e in ew_list])
        to_mark = [
            e for e in ew_list
            if not e.is_invoiced
            and is_earned(ticket_map.get(e.id))
            and billing_month(e, ticket_map.get(e.id)) == oldest_key
        ]
        # Sprint 184 §4 — WHY these rows carry no invoice, and why that is
        # not the defect it looks like.
        #
        # An audit of crmtest found Extra Works flagged invoiced with no
        # invoice line and reported them as stranded data. They are
        # written HERE: this block sets the DENORMALISED flag directly so
        # a demo database opens with one month already billed, and it
        # never creates an `Invoice`. In the running product the flag is
        # a consequence of an invoice line existing, so this is a state
        # the application itself cannot reach.
        #
        # Left as it is, deliberately. The alternative — driving the real
        # invoice generator from the seeder — would push demo data
        # through the gapless per-company-per-year numbering sequence,
        # which is a production-shaped side effect for a demo
        # convenience. Anyone auditing such a row should start here and
        # not in `invoicing/`.
        if to_mark:
            now = timezone.now()
            for e in to_mark:
                e.is_invoiced = True
                e.invoiced_at = now
                e.save(update_fields=["is_invoiced", "invoiced_at", "updated_at"])
            summary["invoiced_month"] = f"{oldest.year}-{oldest.month:02d}"

        # ---- (6) Unread messages across roles -------------------------
        # Customer -> provider, provider -> customer, and one
        # provider-internal note. Real emit_* fan-out populates the
        # notification feed; absence of MessageReadCursor rows makes
        # them count as unread in the inbox.
        wca_ticket = Ticket.objects.filter(
            customer=customer,
            title=f"{DEMO_TICKET_PREFIX} Pantry zeepdispenser",
        ).first()
        open_ticket = Ticket.objects.filter(
            customer=customer,
            title=f"{DEMO_TICKET_PREFIX} Open lobby light",
        ).first()
        message_specs = [
            (
                wca_ticket,
                tom,
                TicketMessageType.PUBLIC_REPLY,
                "Kunt u aangeven wanneer dit wordt opgepakt? (seed #108)",
            ),
            (
                open_ticket,
                ramazan,
                TicketMessageType.PUBLIC_REPLY,
                "Wij plannen dit deze week in. (seed #108)",
            ),
            (
                open_ticket,
                super_admin,
                TicketMessageType.INTERNAL_NOTE,
                "Interne notitie: lamp type L-204 bestellen. (seed #108)",
            ),
        ]
        for ticket, author, mtype, body in message_specs:
            if ticket is None:
                continue
            if TicketMessage.objects.filter(ticket=ticket, message=body).exists():
                continue
            msg = TicketMessage.objects.create(
                ticket=ticket,
                author=author,
                message=body,
                message_type=mtype,
                visibility_mode=TicketMessageVisibility.NORMAL,
            )
            emit_ticket_message_notifications(msg, actor=author)
            summary["messages"] += 1

        ew_sent = ExtraWorkRequest.objects.filter(
            company=company, title=ew_sent_title
        ).first()
        ew_msg_body = "Is verplaatsen van de kasten inbegrepen? (seed #108)"
        if ew_sent is not None and not ExtraWorkMessage.objects.filter(
            extra_work=ew_sent, message=ew_msg_body
        ).exists():
            msg = ExtraWorkMessage.objects.create(
                extra_work=ew_sent,
                author=tom,
                message=ew_msg_body,
                message_type=ExtraWorkMessageType.PUBLIC_REPLY,
                visibility_mode=ExtraWorkMessageVisibility.NORMAL,
            )
            emit_extra_work_message_notifications(msg, actor=tom)
            summary["messages"] += 1

        self._owner_batch2_summary = summary

    # -----------------------------------------------------------------
    # Sprint 179A §6 — the Work Plan fixture
    # -----------------------------------------------------------------
    def _seed_work_plan_demo(self, User, super_admin):
        """
        Dated ticket slots and assigned extra work for Ahmet, spread
        across the week and across every state the Work Plan chips
        count, so a fresh seed shows a populated week rather than an
        empty one that looks broken.

        **What "idempotent" means here, precisely.** Running the command
        twice must not double the data — every row is looked up by a
        stable marker title first and created only when missing. But the
        dates ARE re-stamped on every run, relative to today. That is
        deliberate and is the difference between an idempotent seeder
        and a frozen one: a fixture pinned to the day it was first
        seeded drifts out of the current week within days, and then the
        demo it exists for shows an empty Monday-to-Sunday. Re-stamping
        keeps the same rows in the right week; it creates nothing.

        **The shapes seeded**, one per branch of the §12B rule:

          * planned this week (three days, three buildings),
          * one started, planned a month out    -> "started early",
          * one past its date and unfinished    -> "overdue",
          * one completed and one unable        -> the closed chips,
          * one with no date at all             -> the undated note,
          * extra work planned this week, extra work planned next month
            (-> "upcoming"), extra work IN_PROGRESS planned later, one
            completed, and — the owner's acceptance test —
            **an extra work assigned to Ahmet, past its deadline**,
            which his Work Plan must show as overdue.

        Assignments are written as real `objects.create()` rows so the
        audit receivers fire, exactly as the bulk-assign endpoint does.
        """
        from datetime import datetime, time, timedelta

        from buildings.models import BuildingStaffVisibility
        from extra_work.models import (
            ExtraWorkAssignment,
            ExtraWorkAssignmentRole,
            ExtraWorkRequest,
            ExtraWorkStatus,
        )
        from tickets.models import StaffAssignmentSlotStatus

        marker = f"{DEMO_TICKET_PREFIX} Werkplan —"
        summary = {"tickets": 0, "slots": 0, "extra_work": 0, "assignments": 0}

        company = Company.objects.filter(slug="osius-demo").first()
        customer = (
            Customer.objects.filter(company=company, name="B Amsterdam").first()
            if company
            else None
        )
        buildings = {
            name: Building.objects.filter(company=company, name=name).first()
            for name in ("B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam")
        }
        ahmet = User.objects.filter(
            email="ahmet-staff-osius@b-amsterdam.demo", role=UserRole.STAFF
        ).first()
        ramazan = User.objects.filter(
            email="ramazan-admin-osius@b-amsterdam.demo"
        ).first()
        if not all([company, customer, ahmet, *buildings.values()]):
            self.stdout.write(self.style.WARNING(
                "seed_demo_data: skipping the Work Plan fixture — Osius "
                "demo fixtures incomplete."
            ))
            return

        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())

        def at(day, hour):
            """An aware datetime, or None for a slot nobody has dated."""
            if day is None:
                return None
            return timezone.make_aware(
                datetime.combine(day, time(hour, 0))
            )

        # (title, building, ticket status, start day, end day, slot status)
        slot_specs = [
            (
                f"{marker} trappenhuis dweilen",
                "B1 Amsterdam",
                TicketStatus.OPEN,
                monday,
                monday,
                StaffAssignmentSlotStatus.ASSIGNED,
            ),
            (
                f"{marker} glasbewassing voorgevel",
                "B2 Amsterdam",
                TicketStatus.IN_PROGRESS,
                today,
                today,
                StaffAssignmentSlotStatus.ASSIGNED,
            ),
            (
                f"{marker} vloeronderhoud kantoorlaag",
                "B3 Amsterdam",
                TicketStatus.OPEN,
                monday + timedelta(days=3),
                monday + timedelta(days=3),
                StaffAssignmentSlotStatus.ASSIGNED,
            ),
            (
                f"{marker} kelderberging opruimen",
                "B1 Amsterdam",
                TicketStatus.OPEN,
                today - timedelta(days=4),
                today - timedelta(days=4),
                StaffAssignmentSlotStatus.ASSIGNED,
            ),
            (
                f"{marker} entree gereinigd",
                "B2 Amsterdam",
                TicketStatus.OPEN,
                today - timedelta(days=1),
                today - timedelta(days=1),
                StaffAssignmentSlotStatus.COMPLETED,
            ),
            (
                f"{marker} dakgoot niet bereikbaar",
                "B3 Amsterdam",
                TicketStatus.OPEN,
                today - timedelta(days=2),
                today - timedelta(days=2),
                StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE,
            ),
            (
                f"{marker} najaarsronde alvast begonnen",
                "B1 Amsterdam",
                TicketStatus.IN_PROGRESS,
                today + timedelta(days=24),
                today + timedelta(days=25),
                StaffAssignmentSlotStatus.ASSIGNED,
            ),
            (
                f"{marker} nog niet ingepland",
                "B2 Amsterdam",
                TicketStatus.OPEN,
                None,
                None,
                StaffAssignmentSlotStatus.ASSIGNED,
            ),
        ]

        for title, bname, tstatus, start, end, slot_status in slot_specs:
            building = buildings[bname]
            ticket = Ticket.objects.filter(
                customer=customer, title=title
            ).first()
            if ticket is None:
                ticket = Ticket.objects.create(
                    company=company,
                    building=building,
                    customer=customer,
                    created_by=super_admin,
                    title=title,
                    description=(
                        "Seeded by seed_demo_data (Sprint 179A) for the "
                        "Work Plan week view."
                    ),
                    type=TicketType.REQUEST,
                    priority=TicketPriority.NORMAL,
                    status=tstatus,
                )
                summary["tickets"] += 1
            elif ticket.status != tstatus:
                # Set directly rather than through the state machine:
                # this is fixture construction, and walking a demo row
                # through transitions would write a history that says an
                # operator did something they did not.
                ticket.status = tstatus
                ticket.save(update_fields=["status", "updated_at"])

            slot = TicketStaffAssignment.objects.filter(
                ticket=ticket, user=ahmet
            ).first()
            if slot is None:
                TicketStaffAssignment.objects.create(
                    ticket=ticket,
                    user=ahmet,
                    assigned_by=super_admin,
                    scheduled_start_at=at(start, 9),
                    scheduled_end_at=at(end, 12),
                    time_window_label="Ochtend" if start else "",
                    slot_status=slot_status,
                    completion_note=(
                        "Klaar, geen bijzonderheden."
                        if slot_status == StaffAssignmentSlotStatus.COMPLETED
                        else ""
                    ),
                    unable_to_complete_reason=(
                        "Geen ladder aanwezig op locatie."
                        if slot_status
                        == StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE
                        else ""
                    ),
                )
                summary["slots"] += 1
            else:
                slot.scheduled_start_at = at(start, 9)
                slot.scheduled_end_at = at(end, 12)
                slot.slot_status = slot_status
                slot.save(
                    update_fields=[
                        "scheduled_start_at",
                        "scheduled_end_at",
                        "slot_status",
                    ]
                )

        # (title, building, EW status, preferred, planned_end, deadline)
        ew_specs = [
            (
                f"{marker} EW kozijnen schilderen",
                "B1 Amsterdam",
                ExtraWorkStatus.CUSTOMER_APPROVED,
                monday + timedelta(days=1),
                monday + timedelta(days=2),
                monday + timedelta(days=4),
            ),
            (
                # THE acceptance test: assigned to Ahmet, past its
                # deadline, and therefore overdue in Ahmet's Work Plan.
                f"{marker} EW gevelreiniging (te laat)",
                "B2 Amsterdam",
                ExtraWorkStatus.CUSTOMER_APPROVED,
                today - timedelta(days=12),
                None,
                today - timedelta(days=3),
            ),
            (
                f"{marker} EW tapijtreiniging (al begonnen)",
                "B3 Amsterdam",
                ExtraWorkStatus.IN_PROGRESS,
                today + timedelta(days=21),
                None,
                today + timedelta(days=28),
            ),
            (
                f"{marker} EW voorjaarsronde volgende maand",
                "B1 Amsterdam",
                ExtraWorkStatus.CUSTOMER_APPROVED,
                today + timedelta(days=30),
                today + timedelta(days=31),
                today + timedelta(days=35),
            ),
            (
                f"{marker} EW ramen binnenzijde (afgerond)",
                "B2 Amsterdam",
                ExtraWorkStatus.COMPLETED,
                today - timedelta(days=2),
                None,
                today - timedelta(days=1),
            ),
        ]

        for title, bname, ew_status, preferred, planned_end, deadline in ew_specs:
            request = ExtraWorkRequest.objects.filter(
                customer=customer, title=title
            ).first()
            if request is None:
                request = ExtraWorkRequest.objects.create(
                    company=company,
                    building=buildings[bname],
                    customer=customer,
                    created_by=super_admin,
                    title=title,
                    description=(
                        "Seeded by seed_demo_data (Sprint 179A) for the "
                        "Work Plan week view."
                    ),
                    status=ew_status,
                    preferred_date=preferred,
                    planned_end_date=planned_end,
                    deadline=deadline,
                )
                summary["extra_work"] += 1
            else:
                request.status = ew_status
                request.preferred_date = preferred
                request.planned_end_date = planned_end
                request.deadline = deadline
                request.save(
                    update_fields=[
                        "status",
                        "preferred_date",
                        "planned_end_date",
                        "deadline",
                        "updated_at",
                    ]
                )

            # A WORKER must hold BuildingStaffVisibility on the request's
            # building — the same precondition the assign endpoint
            # enforces. The per-company staff seed already grants Ahmet
            # all three, but a demo DB predating that would silently
            # produce an assignment the real endpoint would refuse.
            BuildingStaffVisibility.objects.get_or_create(
                user=ahmet,
                building=buildings[bname],
                defaults={"can_request_assignment": True},
            )
            if not ExtraWorkAssignment.objects.filter(
                extra_work_request=request,
                user=ahmet,
                role=ExtraWorkAssignmentRole.WORKER,
            ).exists():
                ExtraWorkAssignment.objects.create(
                    extra_work_request=request,
                    user=ahmet,
                    role=ExtraWorkAssignmentRole.WORKER,
                    assigned_by=super_admin,
                )
                summary["assignments"] += 1
            # One responsible manager, so the team week shows both hats.
            if ramazan is not None and not ExtraWorkAssignment.objects.filter(
                extra_work_request=request,
                user=ramazan,
                role=ExtraWorkAssignmentRole.MANAGER,
            ).exists():
                ExtraWorkAssignment.objects.create(
                    extra_work_request=request,
                    user=ramazan,
                    role=ExtraWorkAssignmentRole.MANAGER,
                    assigned_by=super_admin,
                )
                summary["assignments"] += 1

        self._work_plan_summary = summary

    # -----------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------
    def _print_summary(self, *, prune_summary=None):
        out = self.stdout.write
        out(self.style.SUCCESS("seed_demo_data: done."))
        catalog = getattr(self, "_service_catalog_counts", None)
        if catalog:
            out("")
            out(
                f"Service catalog: {catalog['categories']} categories, "
                f"{catalog['services']} services."
            )
        batch2 = getattr(self, "_owner_batch2_summary", None)
        if batch2:
            out("")
            out(
                "#108 enrichment: "
                f"{batch2['tickets']} tickets, "
                f"{batch2['extra_work']} extra-work requests, "
                f"billing months {batch2['billing_months'] or '(existing)'}"
                + (
                    f" (invoiced: {batch2['invoiced_month']})"
                    if batch2["invoiced_month"]
                    else ""
                )
                + f", {batch2['messages']} messages."
            )
            if batch2["skipped"]:
                out(
                    f"  already present (skipped): {len(batch2['skipped'])} "
                    "marker rows."
                )
        work_plan = getattr(self, "_work_plan_summary", None)
        if work_plan:
            out("")
            out(
                "Work Plan fixture (Sprint 179A): "
                f"{work_plan['tickets']} tickets, "
                f"{work_plan['slots']} dated slots, "
                f"{work_plan['extra_work']} extra-work requests, "
                f"{work_plan['assignments']} people assigned. "
                "Zeroes on a re-run mean the rows were already there — "
                "their dates are re-stamped relative to today either way."
            )
        demo_ew = getattr(self, "_demo_extra_work_summary", None)
        if demo_ew:
            out("")
            if demo_ew.get("skipped"):
                out(
                    f"Demo Extra Work already present (title='{demo_ew['title']}') "
                    "— left untouched."
                )
            else:
                ticket_repr = ", ".join(
                    f"#{tid}={tstatus}" for tid, tstatus in demo_ew["ticket_statuses"]
                ) or "(none)"
                out(
                    f"Demo Extra Work created: id={demo_ew['ew_id']} "
                    f"status={demo_ew['status']} spawned={demo_ew['spawned_count']} "
                    f"tickets=[{ticket_repr}]"
                )
        if prune_summary and prune_summary["users"] > 0:
            out("")
            out(
                f"Pruned legacy demo rows: "
                f"{prune_summary['users']} users (soft-deleted), "
                f"{prune_summary['tickets']} tickets, "
                f"{prune_summary['company_memberships']} company memberships, "
                f"{prune_summary['manager_assignments']} manager assignments, "
                f"{prune_summary['customer_memberships']} customer memberships, "
                f"{prune_summary['customer_user_building_access']} "
                "customer-user-building-access rows."
            )
            if prune_summary["companies_deactivated"] > 0:
                out(
                    f"Deactivated {prune_summary['companies_deactivated']} "
                    "legacy single-company seed slug(s)."
                )
        out("")
        out(f"All demo accounts use password: {DEMO_PASSWORD}")
        out("")
        out(f"  SUPER_ADMIN      {SUPER_ADMIN_USER['email']}")
        for company in COMPANIES:
            out("")
            out(f"Company  : {company['name']} (slug={company['slug']})")
            out(f"Customer : {company['customer']['name']}")
            out(f"Buildings: {', '.join(company['buildings'])}")
            out(
                f"  COMPANY_ADMIN    {company['company_admin']['email']}"
            )
            for mgr in company["building_managers"]:
                out(
                    f"  BUILDING_MANAGER {mgr['email']:<26} → "
                    f"{', '.join(mgr['buildings'])}"
                )
            for cu_spec in company["customer_users"]:
                out(
                    f"  CUSTOMER_USER    {cu_spec['email']:<26} → "
                    f"{', '.join(cu_spec['buildings'])}"
                )
