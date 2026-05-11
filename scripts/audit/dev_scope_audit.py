#!/usr/bin/env python3
"""
Sprint 9 — black-box dev scope audit.

Logs in to the local dev API as each demo role and verifies that the
server-side permission classes accept or reject the documented set of
endpoints. This is a *complement* to the test suite — the test suite
proves the rules in isolation; this script proves the wiring at the
HTTP boundary on a running stack, with the actual gunicorn / DRF /
auth middleware chain in the loop.

Pre-requisites:
    - Dev stack up (see scripts/demo_up.sh).
    - `python manage.py seed_demo_data` has run, so the canonical
      two-company demo (Osius Demo + Bright Facilities) exists.

Run:
    python3 scripts/audit/dev_scope_audit.py
    BASE_URL=http://localhost:8000 python3 scripts/audit/dev_scope_audit.py

Exit code 0 if every observed status code matches the expectation;
1 otherwise. No production credentials are referenced; the demo
password (`Demo12345!`) is the seed default.

This script does NOT mutate any data — it only issues GET requests.
For mutating coverage see scripts/scope_isolation_test.sh.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "Demo12345!")


# (label, email) — Sprint 21 retargets at the canonical seed_demo_data
# personas (Osius Demo / Company A). Cross-company isolation is
# verified by the Playwright cross_company_isolation.spec.ts suite,
# not by this audit.
ROLES = [
    ("super",    "superadmin@cleanops.demo"),
    ("company",  "ramazan-admin-osius@b-amsterdam.demo"),
    ("manager",  "gokhan-manager-osius@b-amsterdam.demo"),
    ("customer", "tom-customer-b-amsterdam@b-amsterdam.demo"),
]

# (path, expected_status_per_role) — expected status codes by role label.
# A tuple of allowed codes is OK; e.g. (200, 204).
CHECKS = [
    # path,                           super, company, manager, customer
    ("/health/live",                  200,   200,     200,     200),
    ("/api/auth/me/",                 200,   200,     200,     200),
    ("/api/users/",                   200,   200,     403,     403),
    ("/api/companies/",               200,   200,     200,     200),
    ("/api/buildings/",               200,   200,     200,     200),
    ("/api/customers/",               200,   200,     200,     200),
    ("/api/tickets/",                 200,   200,     200,     200),
    ("/api/audit-logs/",              200,   403,     403,     403),
    ("/api/reports/status-distribution/",       200, 200, 200, 403),
    ("/api/reports/tickets-by-type/",           200, 200, 200, 403),
    ("/api/reports/tickets-by-customer/",       200, 200, 200, 403),
    ("/api/reports/tickets-by-building/",       200, 200, 200, 403),
]


def _post_json(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_status(path: str, token: str | None) -> int:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(f"{BASE_URL}{path}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def login(email: str) -> str:
    data = _post_json(
        "/api/auth/token/",
        {"email": email, "password": DEMO_PASSWORD},
    )
    return data["access"]


def main() -> int:
    print(f"dev_scope_audit: BASE_URL={BASE_URL}")

    # Acquire one access token per role. Bail out early with a friendly
    # error if seed_demo has not been run — there is no point trying
    # to validate scope against an empty database.
    tokens: dict[str, str | None] = {}
    for label, email in ROLES:
        try:
            tokens[label] = login(email)
            print(f"  login {label:<8} {email}: ok")
        except urllib.error.HTTPError as exc:
            print(
                f"  login {label:<8} {email}: HTTP {exc.code} — "
                f"did you run `python manage.py seed_demo_data`?"
            )
            return 1
        except urllib.error.URLError as exc:
            print(f"  login {label:<8} {email}: connection error — {exc}")
            return 1

    failures: list[str] = []
    for entry in CHECKS:
        path = entry[0]
        expected = dict(zip([r[0] for r in ROLES], entry[1:]))
        for label, _ in ROLES:
            token = tokens[label] if path != "/health/live" else None
            actual = _get_status(path, token)
            want = expected[label]
            ok = actual == want
            mark = "OK  " if ok else "FAIL"
            print(f"  [{mark}] {label:<8} GET {path:<48} -> {actual} (want {want})")
            if not ok:
                failures.append(f"{label} GET {path}: got {actual}, want {want}")

    if failures:
        print(f"\n{len(failures)} check(s) failed:")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("\nall checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
