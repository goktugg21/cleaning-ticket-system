"""
Sprint 21 — canonical demo seed (two-company edition).

Idempotent. Aligns with the demo cards rendered on the login page when
VITE_DEMO_MODE=true and with the Playwright test fixtures under
frontend/tests/e2e. Creates / updates two fully isolated demo companies
so every role and every cross-company scope rule can be exercised
end-to-end against a single seed.

Idempotent invariants after a successful run:

  Company A : 'Osius Demo'           (slug=osius-demo)
    Buildings (3)   : B1 / B2 / B3 Amsterdam
    Customer        : 'B Amsterdam' (consolidated; building=NULL)
                      linked to {B1, B2, B3}
    Tickets (4)     : OPEN / IN_PROGRESS / WAITING_CUSTOMER_APPROVAL / CLOSED

  Company B : 'Bright Facilities'    (slug=bright-facilities)
    Buildings (2)   : R1 / R2 Rotterdam
    Customer        : 'City Office Rotterdam' (consolidated; building=NULL)
                      linked to {R1, R2}
    Tickets (2)     : OPEN / IN_PROGRESS

  Demo users (every account uses the password Demo12345!):

    super@cleanops.demo          SUPER_ADMIN (spans both companies)

    Company A — Osius Demo:
      admin@cleanops.demo        COMPANY_ADMIN
      gokhan@cleanops.demo       BUILDING_MANAGER  → B1, B2, B3
      murat@cleanops.demo        BUILDING_MANAGER  → B1
      isa@cleanops.demo          BUILDING_MANAGER  → B2
      tom@cleanops.demo          CUSTOMER_USER     → B1, B2, B3
      iris@cleanops.demo         CUSTOMER_USER     → B1, B2
      amanda@cleanops.demo       CUSTOMER_USER     → B3

    Company B — Bright Facilities:
      admin-b@cleanops.demo      COMPANY_ADMIN
      manager-b@cleanops.demo    BUILDING_MANAGER  → R1, R2
      customer-b@cleanops.demo   CUSTOMER_USER     → R1, R2

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
DEMO_TICKET_PREFIX = "[DEMO]"


# Super admin spans both companies. No CompanyUserMembership row — the
# SUPER_ADMIN role bypasses tenant scoping.
SUPER_ADMIN_USER = {
    "email": "super@cleanops.demo",
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
COMPANIES = [
    {
        "name": "Osius Demo",
        "slug": "osius-demo",
        "address": "Maroastraat 3, 1060LG Amsterdam",
        "default_language": "nl",
        "buildings": ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
        "customer": {
            "name": "B Amsterdam",
            "language": "nl",
            "buildings": ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
        },
        "company_admin": {
            "email": "admin@cleanops.demo",
            "full_name": "Company Admin",
            "language": "en",
        },
        "building_managers": [
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
        ],
        "customer_users": [
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
        ],
        "tickets": [
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
            "email": "admin-b@cleanops.demo",
            "full_name": "Sophie van Dijk",
            "language": "en",
        },
        "building_managers": [
            {
                "email": "manager-b@cleanops.demo",
                "full_name": "Bram de Jong",
                "buildings": ["R1 Rotterdam", "R2 Rotterdam"],
                "language": "en",
            },
        ],
        "customer_users": [
            {
                "email": "customer-b@cleanops.demo",
                "full_name": "Lotte Visser",
                "buildings": ["R1 Rotterdam", "R2 Rotterdam"],
                "language": "nl",
            },
        ],
        "tickets": [
            {
                "title": f"{DEMO_TICKET_PREFIX} Reception lights flickering",
                "description": "Reception strip lights need replacement.",
                "building": "R1 Rotterdam",
                "creator_email": "customer-b@cleanops.demo",
                "type": TicketType.REPORT,
                "priority": TicketPriority.NORMAL,
                "target_status": TicketStatus.OPEN,
            },
            {
                "title": f"{DEMO_TICKET_PREFIX} Lobby floor polish scheduled",
                "description": "Quarterly lobby floor polish — crew on site.",
                "building": "R2 Rotterdam",
                "creator_email": "customer-b@cleanops.demo",
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

        for company_spec in COMPANIES:
            self._seed_company(
                User, super_admin, company_spec, reset_tickets=options["reset_tickets"]
            )

        self._print_summary()

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
        """
        if target_status == TicketStatus.OPEN:
            return
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

    # -----------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------
    def _print_summary(self):
        out = self.stdout.write
        out(self.style.SUCCESS("seed_demo_data: done."))
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
