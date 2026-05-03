#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"

if [[ "${DEMO_DELETE_VOLUMES:-NO}" == "YES" ]]; then
  echo "Stopping demo stack and deleting volumes..."
  FRONTEND_PORT="$FRONTEND_PORT" docker compose -f "$COMPOSE_FILE" down -v --remove-orphans
else
  echo "Stopping demo stack..."
  FRONTEND_PORT="$FRONTEND_PORT" docker compose -f "$COMPOSE_FILE" down --remove-orphans
fi

echo "[OK] Demo stack stopped"
