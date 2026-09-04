"""P-19/P-20 — the shard plan is checked against the tree, not trusted.

`test.yml` fans the backend suite across the shards in `ci_shards.json`
(the old single job could never finish: P-16 measured 6077 tests in
21268 s serially, and the merge commit's run was killed at 50m22s).
Sharding buys the wall time but introduces a failure mode a single
`manage.py test` never had: **a directory missing from the plan is
silently never tested, and CI still reports green.**

So the plan is not a hand-maintained list. This script derives the truth
and asserts the plan covers it exactly once.

## P-20 — what "the truth" means, and why it was wrong

The first version asked "is this an app?" and answered it with
`(dir / "apps.py").exists()`. `backend/config` is the Django PROJECT
package: it owns `tests/test_allowed_hosts.py` and
`tests/test_settings_validator.py` — 12 tests over `ALLOWED_HOSTS` and
the production settings validator (placeholder secret key, wildcard
hosts, weak DB password, missing CORS/CSRF) — and it has no `apps.py`.
So the exact defect this guard exists to prevent already had an
instance, and the guard was built so it could never see it.

The question is now the one that actually matters: **does this directory
own a test file?** Not "is it an app". A directory that owns tests and
is not in a shard fails the run.

A directory that genuinely must not be sharded goes in `"exempt"` with a
written reason, and every run PRINTS the exemptions — an exemption
anybody can see beats a rule nobody can.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}


def dirs_with_tests() -> set[str]:
    """Every top-level directory under backend/ that owns a test module.

    Deliberately NOT "every app": see the module docstring. `config` has
    no `apps.py` and 12 security tests, and that is the whole point.
    """
    found = set()
    for entry in ROOT.iterdir():
        if not entry.is_dir() or entry.name in SKIP_DIRS:
            continue
        for test_file in entry.rglob("test*.py"):
            if "__pycache__" in test_file.parts:
                continue
            found.add(entry.name)
            break
    return found


def main() -> int:
    plan = json.loads((ROOT / "ci_shards.json").read_text())
    shards = plan["shards"]
    exempt = {e["dir"]: e["reason"] for e in plan.get("exempt", [])}

    planned: list[str] = []
    for shard in shards:
        planned.extend(shard["apps"].split())

    real = dirs_with_tests()
    seen = set(planned)

    problems = []
    missing = sorted(real - seen - set(exempt))
    if missing:
        problems.append(
            "directories that own tests but NO shard runs (they would "
            f"silently never be tested): {', '.join(missing)}"
        )
    unknown = sorted(seen - real)
    if unknown:
        problems.append(
            f"shard entries that own no test file: {', '.join(unknown)}"
        )
    duplicated = sorted({a for a in planned if planned.count(a) > 1})
    if duplicated:
        problems.append(
            f"directories listed in more than one shard: {', '.join(duplicated)}"
        )
    both = sorted(seen & set(exempt))
    if both:
        problems.append(
            f"listed as exempt AND in a shard: {', '.join(both)}"
        )
    stale = sorted(set(exempt) - real)
    if stale:
        problems.append(
            "exempt entries that own no test file (delete them): "
            f"{', '.join(stale)}"
        )

    if problems:
        print("ci_shards.json does not match backend/:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nFix ci_shards.json — it is the single source the matrix and "
            "this check both read.",
            file=sys.stderr,
        )
        return 1

    print(
        f"shard plan OK — {len(shards)} shards cover "
        f"{len(real) - len(exempt)} of {len(real)} directories with tests:"
    )
    for shard in shards:
        print(f"  {shard['name']:38} {shard['apps']}")
    # Always print the exemptions, even when there are none: a reader must
    # be able to see at a glance that nothing is being quietly skipped.
    if exempt:
        print("exempt from sharding (NOT run by CI):")
        for d, reason in sorted(exempt.items()):
            print(f"  {d:38} {reason}")
    else:
        print("exempt from sharding: none — every directory with tests is in a shard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
