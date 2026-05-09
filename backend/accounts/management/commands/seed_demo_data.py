"""
Sprint 16 — canonical demo seed.

Idempotent. Aligns with the demo cards rendered on the login page when
VITE_DEMO_MODE=true and with the Playwright test fixtures under
frontend/tests/e2e. Creates / updates exactly the accounts and scope
shape Sprint 14 introduced (consolidated customer with M:N building
links and per-customer-user building access), so all roles can be
exercised end-to-end against a single seed.

Idempotent invariants after a successful run:

  Company         : 'Osius Demo'  (slug=osius-demo)
  Buildings (3)   : B1 / B2 / B3 Amsterdam at Maroastraat 3
  Customer        : 'B Amsterdam' (consolidated; building=NULL)
                    linked to {B1, B2, B3} via CustomerBuildingMembership

  Demo users (every account uses the password Demo12345!):

    super@cleanops.demo            SUPER_ADMIN
    admin@cleanops.demo            COMPANY_ADMIN  (Osius Demo)
    gokhan@cleanops.demo           BUILDING_MANAGER  → B1, B2, B3
    murat@cleanops.demo            BUILDING_MANAGER  → B1
    isa@cleanops.demo              BUILDING_MANAGER  → B2
    tom@cleanops.demo              CUSTOMER_USER     → B1, B2, B3
    iris@cleanops.demo             CUSTOMER_USER     → B1, B2
    amanda@cleanops.demo           CUSTOMER_USER     → B3

  Tickets (created via apply_transition so timestamps populate
  correctly for dashboards and SLA):

    [DEMO] Open lobby light       B1   OPEN
    [DEMO] In progress hallway    B2   IN_PROGRESS
    [DEMO] Pantry zeepdispenser   B3   WAITING_CUSTOMER_APPROVAL
    [DEMO] Closed kitchen tap     B1   APPROVED -> CLOSED

Usage
-----
    docker compose exec -T backend python manage.py seed_demo_data
    docker compose exec -T backend python manage.py seed_demo_data --reset-tickets

Safety
------
- Refuses to run when DJANGO_DEBUG=False unless the operator passes
  --i-know-this-is-not-prod. This is the same gate seed_b_amsterdam_demo
  uses; it lets the seed run on a CI / local dev stack but fails closed
  on a production-shaped settings tree.
- All passwords land at Demo12345! — DO NOT enable VITE_DEMO_MODE on a
  pilot/production frontend, and DO NOT run this command against a
  production database. The check_no_demo_accounts management command
  (added in Sprint 10) refuses pilot launch if any seeded demo email
  is present.

The `[DEMO]` prefix on ticket titles is a stable filter handle:
re-running with --reset-tickets deletes only those rows so the
operator can rebuild the lifecycle samples without disturbing real
tickets that may have been created during a manual walkthrough.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from tickets.models import Ticket, TicketPriority, TicketStatus, TicketType
from tickets.state_machine import apply_transition


DEMO_PASSWORD = "Demo12345!"

COMPANY_NAME = "Osius Demo"
COMPANY_SLUG = "osius-demo"

CUSTOMER_NAME = "B Amsterdam"
CUSTOMER_ADDRESS = "Maroastraat 3, 1060LG Amsterdam"

BUILDING_NAMES = ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"]


# ---------------------------------------------------------------------------
# User specs. The same email convention is reused on the frontend demo
# cards (see frontend/src/pages/LoginPage.tsx) so a one-click "Fill login"
# is reliable.
# ---------------------------------------------------------------------------
SUPER_ADMIN_USER = {
    "email": "super@cleanops.demo",
    "full_name": "Super Admin",
    "role": UserRole.SUPER_ADMIN,
    "is_staff": True,
    "is_superuser": True,
    "language": "en",
}

COMPANY_ADMIN_USER = {
    "email": "admin@cleanops.demo",
    "full_name": "Company Admin",
    "role": UserRole.COMPANY_ADMIN,
    "language": "en",
}

BUILDING_MANAGERS = [
    {
        "email": "gokhan@cleanops.demo",
        "full_name": "Gokhan Koçak",
        "buildings": ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
        "language": "en",
    },
    {
        "email": "murat@cleanops.demo",
        "full_name": "Murat Uğurlu",
        "buildings": ["B1 Amsterdam"],
        "language": "en",
    },
    {
        "email": "isa@cleanops.demo",
        "full_name": "İsa Uğurlu",
        "buildings": ["B2 Amsterdam"],
        "language": "en",
    },
]

CUSTOMER_USERS = [
    {
        "email": "tom@cleanops.demo",
        "full_name": "Tom Verbeek",
        "buildings": ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
        "language": "nl",
    },
    {
        "email": "iris@cleanops.demo",
        "full_name": "Iris",
        "buildings": ["B1 Amsterdam", "B2 Amsterdam"],
        "language": "nl",
    },
    {
        "email": "amanda@cleanops.demo",
        "full_name": "Amanda",
        "buildings": ["B3 Amsterdam"],
        "language": "nl",
    },
]


DEMO_TICKET_PREFIX = "[DEMO]"

# Lifecycle samples. Ordered by status — apply_transition walks each
# from OPEN to its target.
DEMO_TICKETS = [
    {
        "title": f"{DEMO_TICKET_PREFIX} Open lobby light",
        "description": "Lobby light flickers, please replace.",
        "building": "B1 Amsterdam",
        "creator_email": "tom@cleanops.demo",
        "type": TicketType.REPORT,
        "priority": TicketPriority.NORMAL,
        "target_status": TicketStatus.OPEN,
    },
    {
        "title": f"{DEMO_TICKET_PREFIX} In progress hallway scuff",
        "description": "Hallway needs touch-up paint after move-in.",
        "building": "B2 Amsterdam",
        "creator_email": "iris@cleanops.demo",
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
        "creator_email": "amanda@cleanops.demo",
        "type": TicketType.REPORT,
        "priority": TicketPriority.HIGH,
        "target_status": TicketStatus.WAITING_CUSTOMER_APPROVAL,
    },
    {
        "title": f"{DEMO_TICKET_PREFIX} Closed kitchen tap",
        "description": "Kitchen tap leak resolved last sprint.",
        "building": "B1 Amsterdam",
        "creator_email": "tom@cleanops.demo",
        "type": TicketType.REPORT,
        "priority": TicketPriority.NORMAL,
        "target_status": TicketStatus.CLOSED,
    },
]


class Command(BaseCommand):
    help = (
        "Seed the canonical Sprint 16 demo dataset (Osius Demo / "
        "B Amsterdam / Tom-Iris-Amanda). Dev-only; refuses on "
        "DJANGO_DEBUG=False unless --i-know-this-is-not-prod is set. "
        "Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-tickets",
            action="store_true",
            help=(
                "Delete any pre-existing demo-tagged tickets (titles "
                "starting with [DEMO]) before re-creating them. Real "
                "tickets are never touched."
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

        company, _ = Company.objects.update_or_create(
            slug=COMPANY_SLUG,
            defaults={"name": COMPANY_NAME, "is_active": True},
        )

        buildings = {}
        for name in BUILDING_NAMES:
            building, _ = Building.objects.update_or_create(
                company=company,
                name=name,
                defaults={"address": CUSTOMER_ADDRESS, "is_active": True},
            )
            buildings[name] = building

        # Consolidated B Amsterdam customer with NULL anchor.
        customer = (
            Customer.objects.filter(
                company=company, name=CUSTOMER_NAME, building__isnull=True
            ).first()
        )
        if customer is None:
            customer = Customer.objects.create(
                company=company,
                name=CUSTOMER_NAME,
                building=None,
                contact_email="",
                phone="",
                language="nl",
                is_active=True,
            )
        else:
            # Idempotent re-run: keep is_active true.
            if not customer.is_active:
                customer.is_active = True
                customer.save(update_fields=["is_active"])

        for name in BUILDING_NAMES:
            CustomerBuildingMembership.objects.get_or_create(
                customer=customer, building=buildings[name]
            )

        User = get_user_model()

        # --- Super admin ---
        super_admin = self._upsert_user(User, SUPER_ADMIN_USER)

        # --- Company admin ---
        company_admin = self._upsert_user(User, COMPANY_ADMIN_USER)
        CompanyUserMembership.objects.get_or_create(
            user=company_admin, company=company
        )

        # --- Building managers ---
        for spec in BUILDING_MANAGERS:
            manager = self._upsert_user(
                User,
                {
                    "email": spec["email"],
                    "full_name": spec["full_name"],
                    "role": UserRole.BUILDING_MANAGER,
                    "language": spec["language"],
                },
            )
            for bname in spec["buildings"]:
                BuildingManagerAssignment.objects.get_or_create(
                    user=manager, building=buildings[bname]
                )

        # --- Customer users ---
        customer_user_lookup = {}
        for spec in CUSTOMER_USERS:
            cu = self._upsert_user(
                User,
                {
                    "email": spec["email"],
                    "full_name": spec["full_name"],
                    "role": UserRole.CUSTOMER_USER,
                    "language": spec["language"],
                },
            )
            membership, _ = CustomerUserMembership.objects.get_or_create(
                customer=customer, user=cu
            )
            for bname in spec["buildings"]:
                CustomerUserBuildingAccess.objects.get_or_create(
                    membership=membership, building=buildings[bname]
                )
            customer_user_lookup[spec["email"]] = cu

        if options["reset_tickets"]:
            Ticket.objects.filter(
                customer=customer, title__startswith=DEMO_TICKET_PREFIX
            ).delete()

        for spec in DEMO_TICKETS:
            existing = Ticket.objects.filter(
                customer=customer,
                title=spec["title"],
            ).first()
            if existing is not None:
                # Idempotent: leave the ticket as-is if its status is
                # already at-or-past the target. We do NOT walk it back.
                continue

            building = buildings[spec["building"]]
            creator = customer_user_lookup.get(spec["creator_email"])
            if creator is None:
                creator = User.objects.get(email=spec["creator_email"])

            ticket = Ticket.objects.create(
                company=company,
                building=building,
                customer=customer,
                created_by=creator,
                title=spec["title"],
                description=spec["description"],
                type=spec["type"],
                priority=spec["priority"],
                status=TicketStatus.OPEN,
            )
            self._walk_to_status(ticket, spec["target_status"], super_admin)

        # Output summary so the operator can see what landed.
        self.stdout.write(self.style.SUCCESS("seed_demo_data: done."))
        self.stdout.write("")
        self.stdout.write(f"Company  : {COMPANY_NAME} (slug={COMPANY_SLUG})")
        self.stdout.write(f"Customer : {CUSTOMER_NAME}")
        self.stdout.write(f"Buildings: {', '.join(BUILDING_NAMES)}")
        self.stdout.write("")
        self.stdout.write(f"All demo accounts use password: {DEMO_PASSWORD}")
        self.stdout.write("")
        for spec in [
            {"label": "SUPER_ADMIN", **SUPER_ADMIN_USER},
            {"label": "COMPANY_ADMIN", **COMPANY_ADMIN_USER},
        ]:
            self.stdout.write(f"  {spec['label']:<16} {spec['email']}")
        for spec in BUILDING_MANAGERS:
            buildings_str = ", ".join(spec["buildings"])
            self.stdout.write(
                f"  BUILDING_MANAGER {spec['email']:<26} → {buildings_str}"
            )
        for spec in CUSTOMER_USERS:
            buildings_str = ", ".join(spec["buildings"])
            self.stdout.write(
                f"  CUSTOMER_USER    {spec['email']:<26} → {buildings_str}"
            )

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
        user, created = User.objects.get_or_create(
            email=spec["email"], defaults=defaults
        )
        # Idempotent: align fields if drifted.
        dirty_fields = []
        for k, v in defaults.items():
            if getattr(user, k) != v:
                setattr(user, k, v)
                dirty_fields.append(k)
        if dirty_fields:
            user.save(update_fields=dirty_fields)
        # Always reset the demo password so the published credential
        # always works.
        user.set_password(DEMO_PASSWORD)
        user.save(update_fields=["password"])
        return user

    def _walk_to_status(self, ticket, target_status, super_admin):
        """
        Walk a freshly-created OPEN ticket to the target status using
        apply_transition so timestamps and TicketStatusHistory rows
        populate correctly. Uses the super admin actor — they can
        perform any transition without the per-role scope checks.
        """
        if target_status == TicketStatus.OPEN:
            return
        # Path: OPEN -> IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL -> APPROVED -> CLOSED.
        path = [
            TicketStatus.IN_PROGRESS,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            TicketStatus.APPROVED,
            TicketStatus.CLOSED,
        ]
        for stop in path:
            ticket = apply_transition(
                ticket,
                super_admin,
                stop,
                note=f"seed_demo_data → {stop}",
            )
            if str(stop) == str(target_status):
                return
