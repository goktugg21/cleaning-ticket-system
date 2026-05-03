#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PYSECRET'
import secrets
print(secrets.token_urlsafe(64))
PYSECRET
