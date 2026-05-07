"""
B5 verification: trigger every email type the system sends, so MailHog
captures one of each. Run inside the backend container's Django shell:

    docker compose exec -T backend python manage.py shell < scripts/b5_send_all_emails.py
"""
import os
import time

from django.utils import timezone

from accounts.invitations import Invitation, InvitationStatus, generate_invitation_token, hash_invitation_token
from accounts.models import User, UserRole
from buildings.models import Building
from companies.models import Company
from customers.models import Customer
from notifications.services import (
    send_invitation_email,
    send_password_reset_email,
    send_ticket_assigned_email,
    send_ticket_created_email,
    send_ticket_status_changed_email,
    send_ticket_unassigned_email,
)
from tickets.models import Ticket, TicketStatus, TicketType, TicketPriority

stamp = int(time.time())
print(f"=== B5 email burst @ {stamp} ===")

# Pick a stable inviter / actor (super admin is always present in dev).
inviter = User.objects.get(email="admin@example.com")

# Pick any company/building/customer in the dev DB.
company = Company.objects.first()
building = Building.objects.first()
customer = Customer.objects.first()

# Recipient candidates for ticket-* emails. The pipeline drops the actor and
# any users not in scope, so we use users who are scoped to (company, building,
# customer) by membership. The dev DB seeds these via fixtures.
manager = User.objects.filter(
    role=UserRole.BUILDING_MANAGER,
    building_assignments__building=building,
    is_active=True,
    deleted_at__isnull=True,
).first()

print(f"  company={company.name!r}, building={building.name!r}, customer={customer.name!r}")
print(f"  manager={manager and manager.email}")

# 1. Invitation
print("\n[1] Invitation")
raw_token, token_hash = generate_invitation_token()
inv = Invitation.objects.create(
    email=f"b5-invite-{stamp}@example.com",
    role=UserRole.BUILDING_MANAGER,
    created_by=inviter,
    token_hash=token_hash,
    expires_at=timezone.now() + timezone.timedelta(days=7),
)
inv.buildings.set([building])
log = send_invitation_email(inv, raw_token=raw_token, accept_url=f"http://localhost:5173/accept-invitation?token={raw_token}")
print(f"  -> log {log.id}, recipient={log.recipient_email}")

# 2. Password reset
print("\n[2] Password reset")
target = User.objects.filter(email="customer@example.com").first()
log = send_password_reset_email(
    target,
    uid="MQ",
    token="b5-test-token",
    reset_url="http://localhost:5173/reset-password?uid=MQ&token=b5-test-token",
)
print(f"  -> log {log.id}, recipient={log.recipient_email}")

# 3-6. Build a temporary ticket so the ticket-* emails have real context.
print("\n[3-6] Ticket emails")
ticket = Ticket.objects.create(
    company=company,
    building=building,
    customer=customer,
    created_by=inviter,
    title=f"B5 NL email test ticket {stamp}",
    description="Testticket aangemaakt door B5 verificatie. Negeer of verwijder na test.",
    type=TicketType.REPORT,
    priority=TicketPriority.NORMAL,
    status=TicketStatus.OPEN,
)
print(f"  ticket {ticket.ticket_no} created")

# 3. Ticket created
logs = send_ticket_created_email(ticket, actor=inviter)
print(f"  [3] created -> {len(logs)} log(s) -> {[l.recipient_email for l in logs]}")

# 4. Status changed (normal + override variants)
logs = send_ticket_status_changed_email(
    ticket, old_status="OPEN", new_status="IN_PROGRESS", actor=inviter,
)
print(f"  [4a] status changed normal -> {len(logs)} log(s)")
logs = send_ticket_status_changed_email(
    ticket,
    old_status="WAITING_CUSTOMER_APPROVAL",
    new_status="APPROVED",
    actor=inviter,
    is_admin_override=True,
)
print(f"  [4b] status changed admin-override -> {len(logs)} log(s)")

# 5. Ticket assigned
if manager:
    ticket.assigned_to = manager
    ticket.save(update_fields=["assigned_to", "updated_at"])
    logs = send_ticket_assigned_email(ticket, actor=inviter)
    print(f"  [5] assigned -> {len(logs)} log(s)")

    # 6. Ticket unassigned
    logs = send_ticket_unassigned_email(ticket, recipient_user=manager, actor=inviter)
    print(f"  [6] unassigned -> {len(logs)} log(s)")
else:
    print("  [5,6] skipped: no manager scoped to building")

print("\nDone. Wait a few seconds then poll MailHog at http://localhost:8025/api/v2/messages")
