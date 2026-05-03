#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

ok() {
  echo "[OK] $*"
}

echo "===== 1. ENSURE BACKEND IS RUNNING ====="
docker compose up -d backend >/dev/null
docker compose exec -T backend python manage.py check >/dev/null
ok "Backend is running"

echo
echo "===== 2. RUN NOTIFICATION EMAIL DRY-RUN ====="
docker compose exec -T backend python manage.py shell <<'PY'
from django.test import override_settings
from django.core import mail

from accounts.models import User, UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerUserMembership
from notifications.models import NotificationLog, NotificationStatus
from notifications.services import (
    send_ticket_assigned_email,
    send_ticket_created_email,
    send_ticket_status_changed_email,
)
from tickets.models import Ticket, TicketPriority, TicketStatus, TicketType

PASSWORD = "Test12345!"

def make_user(email, role, full_name):
    user, _ = User.objects.get_or_create(
        email=email,
        defaults={
            "role": role,
            "full_name": full_name,
            "language": "nl",
            "is_active": True,
        },
    )
    user.role = role
    user.full_name = full_name
    user.language = "nl"
    user.is_active = True
    user.deleted_at = None
    user.set_password(PASSWORD)
    user.save()
    return user

company, _ = Company.objects.get_or_create(
    slug="notification-test-company",
    defaults={
        "name": "Notification Test Company",
        "default_language": "nl",
        "is_active": True,
    },
)
company.name = "Notification Test Company"
company.is_active = True
company.save()

building, _ = Building.objects.get_or_create(
    company=company,
    name="Notification Test Building",
    defaults={
        "address": "Notification Street 1",
        "city": "Amsterdam",
        "country": "Netherlands",
        "postal_code": "1000 AA",
        "is_active": True,
    },
)
building.is_active = True
building.save()

customer, _ = Customer.objects.get_or_create(
    company=company,
    building=building,
    name="Notification Test Customer",
    defaults={
        "contact_email": "notification-customer@example.com",
        "phone": "",
        "language": "nl",
        "is_active": True,
    },
)
customer.is_active = True
customer.save()

company_admin = make_user(
    "notification-company-admin@example.com",
    UserRole.COMPANY_ADMIN,
    "Notification Company Admin",
)
manager = make_user(
    "notification-manager@example.com",
    UserRole.BUILDING_MANAGER,
    "Notification Manager",
)
customer_user = make_user(
    "notification-customer-user@example.com",
    UserRole.CUSTOMER_USER,
    "Notification Customer User",
)

CompanyUserMembership.objects.get_or_create(user=company_admin, company=company)
BuildingManagerAssignment.objects.get_or_create(user=manager, building=building)
CustomerUserMembership.objects.get_or_create(user=customer_user, customer=customer)

ticket = Ticket.objects.create(
    company=company,
    building=building,
    customer=customer,
    created_by=customer_user,
    assigned_to=manager,
    title="Notification dry-run ticket",
    description="Created by notification_email_test.sh",
    room_label="Notification Room",
    type=TicketType.REPORT,
    priority=TicketPriority.NORMAL,
    status=TicketStatus.OPEN,
)

NotificationLog.objects.filter(ticket=ticket).delete()

with override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="test@example.com",
):
    logs = []
    logs.extend(send_ticket_created_email(ticket, actor=customer_user))
    logs.extend(
        send_ticket_status_changed_email(
            ticket,
            old_status=TicketStatus.OPEN,
            new_status=TicketStatus.IN_PROGRESS,
            actor=manager,
        )
    )
    logs.extend(
        send_ticket_assigned_email(
            ticket,
            old_assigned_to=None,
            actor=company_admin,
        )
    )

    if not logs:
        raise AssertionError("No notification logs were created.")

    failed = [log for log in logs if log.status != NotificationStatus.SENT]
    if failed:
        raise AssertionError([(log.recipient_email, log.status, log.error_message) for log in failed])

    if len(mail.outbox) != len(logs):
        raise AssertionError(f"Expected {len(logs)} emails, got {len(mail.outbox)}")

print(f"[OK] Notification dry-run sent {len(logs)} emails for ticket {ticket.ticket_no}")
PY

ok "Notification dry-run passed"

echo
echo "======================================"
echo "NOTIFICATION EMAIL TEST PASSED"
echo "======================================"
