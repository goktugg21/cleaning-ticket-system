"""P-19 Part C — the shard plan is checked against the apps, not trusted.

`test.yml` fans the backend suite across the shards in `ci_shards.json`
(the 50-minute job could never finish the full suite: P-16 measured
6077 tests in 21268 s serially, and the merge commit's run was killed
at 50m22s). Sharding buys the wall time, but it introduces a failure
mode a single `manage.py test` never had: **an app missing from the
plan is silently never tested, and CI still goes green.**

So the plan is not a hardcoded list that anyone maintains by hand. This
script derives the truth — every Django app in `backend/` that owns at
least one `test*.py` — and asserts the plan covers it EXACTLY once. Add
an app with tests and forget to shard it and the plan job fails with
the app's name, before a single test runs.

Exits 0 and prints the plan when it is sound; exits 1 naming the gap
when it is not.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def apps_with_tests() -> set[str]:
    """Every app package under backend/ that owns a test module."""
    found = set()
    for app in ROOT.iterdir():
        if not app.is_dir() or not (app / "apps.py").exists():
            continue
        if any(app.rglob("test*.py")):
            found.add(app.name)
    return found


def main() -> int:
    plan = json.loads((ROOT / "ci_shards.json").read_text())
    planned: list[str] = []
    for shard in plan:
        planned.extend(shard["apps"].split())

    real = apps_with_tests()
    seen = set(planned)

    problems = []
    missing = sorted(real - seen)
    if missing:
        problems.append(
            "apps with tests that NO shard runs (they would silently "
            f"never be tested): {', '.join(missing)}"
        )
    unknown = sorted(seen - real)
    if unknown:
        problems.append(
            "shard entries that are not apps with tests: "
            f"{', '.join(unknown)}"
        )
    duplicated = sorted({a for a in planned if planned.count(a) > 1})
    if duplicated:
        problems.append(
            f"apps listed in more than one shard: {', '.join(duplicated)}"
        )

    if problems:
        print("ci_shards.json does not match backend/:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nFix ci_shards.json (it is the single source the matrix and "
            "this check both read).",
            file=sys.stderr,
        )
        return 1

    print(f"shard plan OK — {len(plan)} shards cover {len(real)} apps:")
    for shard in plan:
        print(f"  {shard['name']:38} {shard['apps']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
