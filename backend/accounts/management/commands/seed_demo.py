"""
Idempotent local-demo seed.

Usage:
    docker compose exec -T backend python manage.py seed_demo
    docker compose exec -T backend python manage.py seed_demo --reset-demo-tickets

Creates / updates a deterministic set of demo objects so Ramazan (or any
operator) can run a clean two-browser walkthrough on `localhost`:

  - 4 demo users (super admin, company admin, building manager, customer)
  - 1 demo company / 1 demo building / 1 demo customer-location
  - the three memberships/assignments that wire the users into scope
  - 4 demo tickets across the lifecycle (OPEN, IN_PROGRESS,
    WAITING_CUSTOMER_APPROVAL, APPROVED) so the dashboard / reports
    have something to show before the live demo starts

Re-running is safe: every object is keyed by a stable identifier
(`User.email`, `Company.slug`, `(company, name)` for buildings,
`(company, building, name)` for customers, `(company, customer, title)`
for tickets) and we use `update_or_create` semantics. Re-running with
`--reset-demo-tickets` deletes only the demo-tagged tickets before
re-creating them; non-demo tickets and audit rows are never touched.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerUserMembership
from tickets.models import Ticket, TicketPriority, TicketStatus, TicketType
from tickets.state_machine import apply_transition


DEMO_PASSWORD = "Demo12345!"

DEMO_USERS = [
    {
        "email": "demo-super@example.com",
        "role": UserRole.SUPER_ADMIN,
        "full_name": "Demo Super Admin",
        "is_staff": True,
        "is_superuser": True,
    },
    {
        "email": "demo-company-admin@example.com",
        "role": UserRole.COMPANY_ADMIN,
        "full_name": "Demo Company Admin",
    },
    {
        "email": "demo-manager@example.com",
        "role": UserRole.BUILDING_MANAGER,
        "full_name": "Demo Building Manager",
    },
    {
        "email": "demo-customer@example.com",
        "role": UserRole.CUSTOMER_USER,
        "full_name": "Demo Customer User",
    },
]

COMPANY_NAME = "Demo Cleaning BV"
COMPANY_SLUG = "demo-cleaning-bv"
BUILDING_NAME = "Demo Building A"
CUSTOMER_NAME = "Acme Demo Customer"

# Title prefix that uniquely tags rows produced by this seed. The
# `--reset-demo-tickets` path deletes only rows whose title starts with
# this prefix, so non-demo tickets cannot be removed by mistake.
DEMO_TICKET_PREFIX = "[DEMO]"

# Demo tickets are always CREATED in the OPEN state. To pre-stage one in
# a later state for the dashboard / reports, the seed walks the live
# state machine forward via `apply_transition`, which records every hop
# in TicketStatusHistory and stamps the right timestamp fields
# (sent_for_approval_at, approved_at, resolved_at) — i.e. it produces
# the same shape as a real user clicking through the workflow. The
# super-admin user is the actor for the seed transitions because
# SUPER_ADMIN can perform any transition (state_machine line 95-97), so
# the seed does not need to encode the role/scope matrix itself.
TARGET_STATUS_CHAIN = [
    TicketStatus.OPEN,
    TicketStatus.IN_PROGRESS,
    TicketStatus.WAITING_CUSTOMER_APPROVAL,
    TicketStatus.APPROVED,
]

DEMO_TICKETS = [
    {
        "title": f"{DEMO_TICKET_PREFIX} Lekkage in vergaderzaal A",
        "description": (
            "Demo: er druipt water uit het plafond boven het bureau. "
            "Voorbeeldticket — voor de openings-flow van de demo."
        ),
        "type": TicketType.REPORT,
        "priority": TicketPriority.HIGH,
        "target_status": TicketStatus.OPEN,
        "room_label": "Vergaderzaal A",
        "assigned_to_email": None,
    },
    {
        "title": f"{DEMO_TICKET_PREFIX} Schoonmaak vloer toiletruimte",
        "description": (
            "Demo: vloer is glad, vraag om extra schoonmaakronde. "
            "Voorbeeldticket — wordt gepresenteerd als 'in behandeling'."
        ),
        "type": TicketType.REQUEST,
        "priority": TicketPriority.NORMAL,
        "target_status": TicketStatus.IN_PROGRESS,
        "room_label": "Toiletten 2e verdieping",
        "assigned_to_email": "demo-manager@example.com",
    },
    {
        "title": f"{DEMO_TICKET_PREFIX} Lampen vervangen kantine",
        "description": (
            "Demo: drie tl-lampen knipperen. Vervanging gepland. "
            "Voorbeeldticket — wacht op klantgoedkeuring na uitvoering."
        ),
        "type": TicketType.REQUEST,
        "priority": TicketPriority.NORMAL,
        "target_status": TicketStatus.WAITING_CUSTOMER_APPROVAL,
        "room_label": "Kantine",
        "assigned_to_email": "demo-manager@example.com",
    },
    {
        "title": f"{DEMO_TICKET_PREFIX} Offerteaanvraag glasbewassing",
        "description": (
            "Demo: vraag om offerte voor maandelijkse glasbewassing. "
            "Voorbeeldticket — al goedgekeurd, klaar om te sluiten."
        ),
        "type": TicketType.QUOTE_REQUEST,
        "priority": TicketPriority.NORMAL,
        "target_status": TicketStatus.APPROVED,
        "room_label": "",
        "assigned_to_email": "demo-manager@example.com",
    },
]


class Command(BaseCommand):
    help = "Idempotently seed local-demo users, scoping, and sample tickets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-demo-tickets",
            action="store_true",
            help=(
                "Delete only tickets whose title begins with "
                f"'{DEMO_TICKET_PREFIX}' before recreating the demo set. "
                "Non-demo tickets are not touched."
            ),
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            users = self._upsert_users()
            company = self._upsert_company()
            building = self._upsert_building(company)
            customer = self._upsert_customer(company, building)
            self._upsert_memberships(users, company, building, customer)
            if options.get("reset_demo_tickets"):
                self._reset_demo_tickets(company)
            self._upsert_tickets(users, company, building, customer)

        self._print_summary(users, company, building, customer)

    # ---- users -----------------------------------------------------------
    def _upsert_users(self):
        User = get_user_model()
        created = {}
        for spec in DEMO_USERS:
            email = spec["email"]
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(
                    email=email,
                    password=DEMO_PASSWORD,
                    role=spec["role"],
                    full_name=spec["full_name"],
                    is_staff=spec.get("is_staff", False),
                    is_superuser=spec.get("is_superuser", False),
                )
            else:
                # Re-runs reset the password and key fields so an
                # operator who fat-fingered them last time is not stuck.
                user.role = spec["role"]
                user.full_name = spec["full_name"]
                user.is_staff = spec.get("is_staff", False)
                user.is_superuser = spec.get("is_superuser", False)
                user.is_active = True
                user.deleted_at = None
                user.deleted_by = None
                user.set_password(DEMO_PASSWORD)
                user.save()
            created[email] = user
        return created

    # ---- company / building / customer -----------------------------------
    def _upsert_company(self):
        company, _ = Company.objects.update_or_create(
            slug=COMPANY_SLUG,
            defaults={
                "name": COMPANY_NAME,
                "default_language": "nl",
                "is_active": True,
            },
        )
        return company

    def _upsert_building(self, company):
        building, _ = Building.objects.update_or_create(
            company=company,
            name=BUILDING_NAME,
            defaults={
                "address": "Demoweg 1",
                "city": "Amsterdam",
                "country": "NL",
                "postal_code": "1000 AA",
                "is_active": True,
            },
        )
        return building

    def _upsert_customer(self, company, building):
        customer, _ = Customer.objects.update_or_create(
            company=company,
            building=building,
            name=CUSTOMER_NAME,
            defaults={
                "contact_email": "contact@acme-demo.example",
                "phone": "+31 20 555 0100",
                "language": "nl",
                "is_active": True,
            },
        )
        return customer

    # ---- memberships -----------------------------------------------------
    def _upsert_memberships(self, users, company, building, customer):
        # super admin: no membership row required (role grants access).
        CompanyUserMembership.objects.get_or_create(
            company=company,
            user=users["demo-company-admin@example.com"],
        )
        BuildingManagerAssignment.objects.get_or_create(
            building=building,
            user=users["demo-manager@example.com"],
        )
        CustomerUserMembership.objects.get_or_create(
            customer=customer,
            user=users["demo-customer@example.com"],
        )

    # ---- tickets ---------------------------------------------------------
    def _reset_demo_tickets(self, company):
        # Only deletes rows that this seed produced. The prefix tag is
        # unique to seed-managed tickets, so any non-demo ticket sharing
        # this company still survives.
        Ticket.objects.filter(
            company=company,
            title__startswith=DEMO_TICKET_PREFIX,
        ).delete()

    def _upsert_tickets(self, users, company, building, customer):
        creator = users["demo-customer@example.com"]
        actor = users["demo-super@example.com"]
        for spec in DEMO_TICKETS:
            assigned_email = spec["assigned_to_email"]
            assigned_to = users.get(assigned_email) if assigned_email else None
            # Create the row in the OPEN state on first run; on later
            # runs leave the existing row's `status` alone so we don't
            # silently bounce a transitioned ticket back to OPEN. Other
            # display fields (description, priority, room_label,
            # assignee) are kept in sync each run so a typo can be
            # corrected by re-seeding.
            ticket, created = Ticket.objects.get_or_create(
                company=company,
                building=building,
                customer=customer,
                title=spec["title"],
                defaults={
                    "description": spec["description"],
                    "type": spec["type"],
                    "priority": spec["priority"],
                    "status": TicketStatus.OPEN,
                    "room_label": spec["room_label"],
                    "created_by": creator,
                    "assigned_to": assigned_to,
                },
            )
            if not created:
                ticket.description = spec["description"]
                ticket.type = spec["type"]
                ticket.priority = spec["priority"]
                ticket.room_label = spec["room_label"]
                ticket.assigned_to = assigned_to
                ticket.save(
                    update_fields=[
                        "description",
                        "type",
                        "priority",
                        "room_label",
                        "assigned_to",
                        "updated_at",
                    ]
                )

            # Walk forward through the state machine until the ticket
            # reaches its target. Each hop goes through apply_transition
            # so TicketStatusHistory + sent_for_approval_at / approved_at
            # / resolved_at / first_response_at are populated correctly.
            # If the ticket already sits at (or past) the target — e.g.
            # the operator manually advanced it during the demo and
            # then re-ran the seed — the loop is a no-op.
            self._walk_to_target(ticket, actor, spec["target_status"])

    def _walk_to_target(self, ticket, actor, target_status):
        try:
            current_idx = TARGET_STATUS_CHAIN.index(TicketStatus(ticket.status))
        except ValueError:
            # The ticket sits in a state outside the seed chain (e.g.
            # operator transitioned to REJECTED or CLOSED during the
            # demo). Don't try to walk it back; leave the ticket alone.
            return
        try:
            target_idx = TARGET_STATUS_CHAIN.index(target_status)
        except ValueError:
            return
        if current_idx >= target_idx:
            return

        for next_status in TARGET_STATUS_CHAIN[current_idx + 1 : target_idx + 1]:
            apply_transition(ticket, actor, next_status, note="seed_demo")
            ticket.refresh_from_db()

    # ---- output ----------------------------------------------------------
    def _print_summary(self, users, company, building, customer):
        out = self.stdout.write
        out("Demo seed complete.")
        out("Users:")
        for spec in DEMO_USERS:
            out(f"- {spec['email']} / {DEMO_PASSWORD}")
        out("")
        out(f"Company:  {company.name}")
        out(f"Building: {building.name}")
        out(f"Customer: {customer.name}")
        out(f"Tickets:  {len(DEMO_TICKETS)} demo tickets seeded "
            f"(prefix '{DEMO_TICKET_PREFIX}').")
