#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
PROJECT_NAME="${PROJECT_NAME:-cleaning-ticket-prod-restore-test}"
FRONTEND_PORT="${FRONTEND_PORT:-18080}"
BACKUP_DIR="${BACKUP_DIR:-backups/postgres/restore-test}"
MARKER="restore-test-$(date +%Y%m%d%H%M%S)"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

ok() {
  echo "[OK] $*"
}

compose() {
  FRONTEND_PORT="$FRONTEND_PORT" docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
  if [[ "${KEEP_RESTORE_TEST_STACK:-}" == "YES" ]]; then
    echo "[INFO] Keeping restore test stack because KEEP_RESTORE_TEST_STACK=YES"
    return 0
  fi

  echo
  echo "===== CLEANUP RESTORE TEST STACK ====="
  compose down -v --remove-orphans || true
}

if [[ "${RESTORE_TEST_CONFIRM:-}" != "YES" ]]; then
  echo "Refusing to run restore test without confirmation." >&2
  echo "Run with: RESTORE_TEST_CONFIRM=YES $0" >&2
  exit 1
fi

trap cleanup EXIT

echo "===== 1. CLEAN OLD RESTORE TEST PROJECT ====="
compose down -v --remove-orphans >/dev/null 2>&1 || true
ok "Old restore test project cleaned"

EXISTING_PROD_CONTAINERS="$(docker ps -a --format '{{.Names}}' | grep -E '^cleaning_ticket_prod_(db|redis|backend|frontend)$' || true)"
if [[ -n "$EXISTING_PROD_CONTAINERS" ]]; then
  echo "$EXISTING_PROD_CONTAINERS"
  fail "Production-named containers exist. Run: docker compose -f $COMPOSE_FILE down"
fi

wait_for_db() {
  for attempt in $(seq 1 30); do
    if compose exec -T db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
      ok "Database is ready"
      return 0
    fi

    echo "[WAIT] Database not ready yet (attempt $attempt/30)"
    sleep 2
  done

  fail "Database did not become ready"
}

wait_for_backend() {
  for attempt in $(seq 1 30); do
    if compose exec -T backend python manage.py check >/tmp/cleaning-ticket-restore-backend-check.log 2>&1; then
      ok "Backend check passed"
      return 0
    fi

    echo "[WAIT] Backend not ready yet (attempt $attempt/30)"
    sleep 2
  done

  cat /tmp/cleaning-ticket-restore-backend-check.log || true
  fail "Backend did not become ready"
}

echo
echo "===== 2. START CLEAN TEST STACK ====="
compose up -d --build db redis backend
wait_for_db
wait_for_backend

echo
echo "===== 3. SEED MARKER DATA ====="
compose exec -T -e RESTORE_MARKER="$MARKER" backend python manage.py shell <<'PYSEED'
import os

from accounts.models import User, UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerUserMembership
from tickets.models import Ticket

marker = os.environ["RESTORE_MARKER"]


def upsert_user(email, password, role, full_name, is_staff=False, is_superuser=False):
    user, _ = User.objects.get_or_create(
        email=email,
        defaults={
            "username": email,
            "role": role,
            "full_name": full_name,
            "is_staff": is_staff,
            "is_superuser": is_superuser,
            "is_active": True,
        },
    )

    user.username = email
    user.role = role
    user.full_name = full_name
    user.is_staff = is_staff
    user.is_superuser = is_superuser
    user.is_active = True
    user.deleted_at = None
    user.set_password(password)
    user.save()
    return user


admin = upsert_user(
    "restore-admin@example.com",
    "Admin12345!",
    UserRole.SUPER_ADMIN,
    "Restore Test Admin",
    is_staff=True,
    is_superuser=True,
)

manager = upsert_user(
    "restore-manager@example.com",
    "Test12345!",
    UserRole.BUILDING_MANAGER,
    "Restore Test Manager",
    is_staff=True,
)

customer_user = upsert_user(
    "restore-customer@example.com",
    "Test12345!",
    UserRole.CUSTOMER_USER,
    "Restore Test Customer",
)

company, _ = Company.objects.get_or_create(
    slug="restore-test-company",
    defaults={
        "name": "Restore Test Company",
        "default_language": "nl",
        "is_active": True,
    },
)

building, _ = Building.objects.get_or_create(
    company=company,
    name="Restore Test Building",
    defaults={
        "address": "Restore Test Street 1",
        "city": "Amsterdam",
        "country": "NL",
        "is_active": True,
    },
)

customer, _ = Customer.objects.get_or_create(
    company=company,
    building=building,
    name="Restore Test Customer",
    defaults={
        "contact_email": "restore-customer@example.com",
        "language": "nl",
        "is_active": True,
    },
)

BuildingManagerAssignment.objects.get_or_create(building=building, user=manager)
CustomerUserMembership.objects.get_or_create(customer=customer, user=customer_user)
CompanyUserMembership.objects.get_or_create(company=company, user=manager)

ticket = Ticket.objects.create(
    company=company,
    building=building,
    customer=customer,
    created_by=customer_user,
    title=marker,
    description="Restore test marker ticket.",
    room_label="Restore Test Room",
)

print(f"RESTORE_MARKER={marker}")
print(f"RESTORE_TICKET_ID={ticket.id}")
print(f"RESTORE_TICKET_NO={ticket.ticket_no}")
PYSEED
ok "Marker data seeded: $MARKER"

echo
echo "===== 4. CREATE BACKUP FROM SEEDED STACK ====="
mkdir -p "$BACKUP_DIR"

COMPOSE_PROJECT_NAME="$PROJECT_NAME" \
COMPOSE_FILE="$COMPOSE_FILE" \
BACKUP_DIR="$BACKUP_DIR" \
./scripts/backup_postgres.sh

BACKUP_FILE="$(ls -t "$BACKUP_DIR"/*.dump | head -1)"
[[ -f "$BACKUP_FILE" ]] || fail "Backup file not created"

ls -lh "$BACKUP_FILE"
ok "Backup created: $BACKUP_FILE"

echo
echo "===== 5. VALIDATE BACKUP FILE ====="
cat "$BACKUP_FILE" | compose exec -T db sh -c '
  cat > /tmp/restore-test-backup.dump
  pg_restore -l /tmp/restore-test-backup.dump >/dev/null
  rm /tmp/restore-test-backup.dump
'
ok "Backup is readable by pg_restore"

echo
echo "===== 6. WIPE TEST STACK TO CLEAN ENVIRONMENT ====="
compose down -v --remove-orphans
ok "Test database volume removed"

echo
echo "===== 7. START EMPTY DATABASE ====="
compose up -d db
wait_for_db

echo
echo "===== 8. RESTORE BACKUP INTO CLEAN DATABASE ====="
COMPOSE_PROJECT_NAME="$PROJECT_NAME" \
COMPOSE_FILE="$COMPOSE_FILE" \
CONFIRM_RESTORE=YES \
./scripts/restore_postgres.sh "$BACKUP_FILE"

ok "Backup restored into clean database"

echo
echo "===== 9. START BACKEND AND VERIFY RESTORED DATA ====="
compose up -d redis backend
wait_for_backend

VERIFY_OUTPUT="$(compose exec -T -e RESTORE_MARKER="$MARKER" backend python manage.py shell <<'PYVERIFY'
import os
from tickets.models import Ticket

marker = os.environ["RESTORE_MARKER"]
exists = Ticket.objects.filter(title=marker).exists()
count = Ticket.objects.filter(title=marker).count()

print(f"RESTORE_MARKER={marker}")
print(f"RESTORE_MARKER_COUNT={count}")
print("TICKET_RESTORED=YES" if exists else "TICKET_RESTORED=NO")
PYVERIFY
)"

echo "$VERIFY_OUTPUT"
echo "$VERIFY_OUTPUT" | grep -q "TICKET_RESTORED=YES" || fail "Restored marker ticket not found"

ok "Restored marker ticket verified"

echo
echo "======================================"
echo "PRODUCTION POSTGRES RESTORE TEST PASSED"
echo "Project: $PROJECT_NAME"
echo "Backup: $BACKUP_FILE"
echo "Marker: $MARKER"
echo "======================================"
