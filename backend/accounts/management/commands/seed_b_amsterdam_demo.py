"""
Sprint 14 — B Amsterdam customer + multi-building + per-user-access demo.

This is a development-only seed that exercises the new
CustomerBuildingMembership and CustomerUserBuildingAccess models. It is
SAFE to run repeatedly: every object is upserted on a stable natural
key, so re-running adds no duplicates.

Idempotent invariants after a successful run:

  Company          : 'Osius Demo'                    (slug=osius-demo)
  Buildings (3)    : B1 Amsterdam, B2 Amsterdam, B3 Amsterdam
                     all at "Maroastraat 3, 1060LG Amsterdam"
  Customer         : 'B Amsterdam'                   (consolidated, building=NULL)
  Customer↔buildings link  : B Amsterdam ↔ {B1, B2, B3}

  Customer users :
    tom@b-amsterdam.com     access → B1, B2, B3
    iris@b-amsterdam.com    access → B1, B2
    amanda@b-amsterdam.com  access → B3
                                     ^^^ matches the brief's example.
                                         Amanda only sees B3 tickets.

  Building managers (Osius-side, BuildingManagerAssignment):
    gokhan.kocak@osius.demo  → B1, B2, B3
    murat.ugurlu@osius.demo  → B1
    isa.ugurlu@osius.demo    → B2

  Optional ticket: --with-ticket creates exactly the example ticket
  from the brief (B Amsterdam / B3 Amsterdam, Dutch description).
  --reset-demo-tickets removes prior runs of that ticket first.

Passwords:

  - The customer-user accounts (tom/iris/amanda) are created with an
    UNUSABLE password by default. The operator generates one via the
    standard password-reset flow (or invitation flow) instead. This
    avoids checking a default credential into the codebase.
  - The Osius-side manager accounts use a clearly-marked DEV-ONLY
    password (`Sprint14Demo!`) printed at the end of the run. They are
    NOT created on production hosts (the command refuses unless
    DJANGO_DEBUG=True OR --i-know-this-is-not-prod is passed).

Usage:

    docker compose exec -T backend python manage.py seed_b_amsterdam_demo
    docker compose exec -T backend python manage.py seed_b_amsterdam_demo --with-ticket
    docker compose exec -T backend python manage.py seed_b_amsterdam_demo --reset-demo-tickets

Refuses to run on a production-shaped settings unless --i-know-this-is-not-prod.
"""
from __future__ import annotations

from typing import Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from tickets.models import Ticket, TicketPriority, TicketStatus, TicketType


COMPANY_NAME = "Osius Demo"
COMPANY_SLUG = "osius-demo"

CUSTOMER_NAME = "B Amsterdam"
CUSTOMER_ADDRESS = "Maroastraat 3, 1060LG Amsterdam"

BUILDING_NAMES = ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"]

CUSTOMER_USERS: list[dict] = [
    {
        "email": "tom@b-amsterdam.com",
        "full_name": "Tom Verbeek",
        "buildings": ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
    },
    {
        "email": "iris@b-amsterdam.com",
        "full_name": "Iris",
        "buildings": ["B1 Amsterdam", "B2 Amsterdam"],
    },
    {
        "email": "amanda@b-amsterdam.com",
        "full_name": "Amanda",
        "buildings": ["B3 Amsterdam"],
    },
]

# Dev-only password. Documented in the command output. Any deployment
# that runs in DEBUG=False will refuse to run this command without an
# explicit override flag.
MANAGER_PASSWORD = "Sprint14Demo!"

OSIUS_MANAGERS: list[dict] = [
    {
        "email": "gokhan.kocak@osius.demo",
        "full_name": "Gokhan Koçak",
        "buildings": ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
    },
    {
        "email": "murat.ugurlu@osius.demo",
        "full_name": "Murat Uğurlu",
        "buildings": ["B1 Amsterdam"],
    },
    {
        "email": "isa.ugurlu@osius.demo",
        "full_name": "İsa Uğurlu",
        "buildings": ["B2 Amsterdam"],
    },
]

DEMO_TICKET_TITLE = (
    "B.3.1.k.07 & B.3.1.k.06 // zeepdispenser en torkrol in de pantry al weken op"
)
DEMO_TICKET_DESCRIPTION = (
    "Zeep en tork 1ste etage\n\n"
    "Hi, Mycubes kwam melden dat de zeepdispenser en torkrol in de pantry "
    "al weken op zijn en niet worden gevuld :(\n"
    "Heb ook meteen gemeld dat zij dit zelf ook kunnen/mogen melden in de app."
)


class Command(BaseCommand):
    help = (
        "Seed the B Amsterdam customer demo (Sprint 14). Dev-only; refuses "
        "to run on DJANGO_DEBUG=False unless --i-know-this-is-not-prod is set."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-ticket",
            action="store_true",
            help="Also create the example B3 ticket from the brief.",
        )
        parser.add_argument(
            "--reset-demo-tickets",
            action="store_true",
            help="Remove any pre-existing run of the example ticket before re-creating.",
        )
        parser.add_argument(
            "--i-know-this-is-not-prod",
            action="store_true",
            help=(
                "Required to run when DJANGO_DEBUG is False. Operator confirms "
                "this command is being run on a non-production host."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG and not options["i_know_this_is_not_prod"]:
            raise CommandError(
                "Refusing to run on DJANGO_DEBUG=False. This command is a "
                "dev/demo seed and must not run on a production host. If you "
                "really want to proceed, re-run with "
                "--i-know-this-is-not-prod (still required to be a non-prod "
                "host)."
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
                defaults={
                    "address": CUSTOMER_ADDRESS,
                    "is_active": True,
                },
            )
            buildings[name] = building

        # Sprint 14 customer: consolidated row with building=NULL. The
        # M:N CustomerBuildingMembership table is the source of truth
        # for which buildings B Amsterdam operates at.
        customer = Customer.objects.filter(
            company=company, name=CUSTOMER_NAME, building__isnull=True
        ).first()
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

        for name in BUILDING_NAMES:
            CustomerBuildingMembership.objects.get_or_create(
                customer=customer, building=buildings[name]
            )

        User = get_user_model()

        for entry in CUSTOMER_USERS:
            user, created = User.objects.get_or_create(
                email=entry["email"],
                defaults={
                    "full_name": entry["full_name"],
                    "role": UserRole.CUSTOMER_USER,
                    "language": "nl",
                    "is_active": True,
                },
            )
            if created:
                # Unusable password — operator finishes onboarding via
                # the password-reset flow.
                user.set_unusable_password()
                user.save(update_fields=["password"])
            else:
                # Idempotent path: align role / name with seed if drifted.
                fields = []
                if user.role != UserRole.CUSTOMER_USER:
                    user.role = UserRole.CUSTOMER_USER
                    fields.append("role")
                if user.full_name != entry["full_name"]:
                    user.full_name = entry["full_name"]
                    fields.append("full_name")
                if fields:
                    user.save(update_fields=fields)

            membership, _ = CustomerUserMembership.objects.get_or_create(
                customer=customer, user=user
            )
            for bname in entry["buildings"]:
                CustomerUserBuildingAccess.objects.get_or_create(
                    membership=membership, building=buildings[bname]
                )

        for entry in OSIUS_MANAGERS:
            user, created = User.objects.get_or_create(
                email=entry["email"],
                defaults={
                    "full_name": entry["full_name"],
                    "role": UserRole.BUILDING_MANAGER,
                    "language": "en",
                    "is_active": True,
                },
            )
            if created:
                user.set_password(MANAGER_PASSWORD)
                user.save(update_fields=["password"])
            else:
                fields = []
                if user.role != UserRole.BUILDING_MANAGER:
                    user.role = UserRole.BUILDING_MANAGER
                    fields.append("role")
                if user.full_name != entry["full_name"]:
                    user.full_name = entry["full_name"]
                    fields.append("full_name")
                if fields:
                    user.save(update_fields=fields)

            for bname in entry["buildings"]:
                BuildingManagerAssignment.objects.get_or_create(
                    user=user, building=buildings[bname]
                )

        if options["with_ticket"]:
            self._maybe_seed_ticket(
                customer=customer,
                building=buildings["B3 Amsterdam"],
                creator_email=CUSTOMER_USERS[0]["email"],
                reset=options["reset_demo_tickets"],
            )

        self.stdout.write(self.style.SUCCESS("B Amsterdam demo seed complete."))
        self.stdout.write("")
        self.stdout.write("Customer: B Amsterdam (company: Osius Demo)")
        self.stdout.write("Linked buildings: B1, B2, B3 Amsterdam")
        self.stdout.write("")
        self.stdout.write("Customer users (passwords UNUSABLE — use password-reset to set one):")
        for entry in CUSTOMER_USERS:
            self.stdout.write(
                f"  - {entry['email']:<28} access → {', '.join(entry['buildings'])}"
            )
        self.stdout.write("")
        self.stdout.write(
            f"Osius managers (DEV-ONLY password '{MANAGER_PASSWORD}'):"
        )
        for entry in OSIUS_MANAGERS:
            self.stdout.write(
                f"  - {entry['email']:<28} assigned → {', '.join(entry['buildings'])}"
            )

    def _maybe_seed_ticket(self, *, customer, building, creator_email, reset):
        if reset:
            Ticket.objects.filter(
                customer=customer,
                building=building,
                title=DEMO_TICKET_TITLE,
            ).delete()
        if Ticket.objects.filter(
            customer=customer, building=building, title=DEMO_TICKET_TITLE
        ).exists():
            return
        User = get_user_model()
        creator = User.objects.get(email=creator_email)
        Ticket.objects.create(
            company=customer.company,
            building=building,
            customer=customer,
            created_by=creator,
            title=DEMO_TICKET_TITLE,
            description=DEMO_TICKET_DESCRIPTION,
            type=TicketType.REPORT,
            priority=TicketPriority.NORMAL,
            status=TicketStatus.OPEN,
        )
