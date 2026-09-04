# Claude Code operational notes

Hard-won lessons from the admin-UI and audit-script batches. Read this before
editing shell scripts, running the Playwright audit, or shelling out through
the WSL bridge for anything that produces persistent artifacts.

## Edit tool drops the +x bit on shell scripts

When the Edit tool modifies a `.sh` file via the WSL bridge, the resulting
file loses its executable bit. Symptom: a previously-runnable script now
fails with "Permission denied" or git's index records mode 100644 instead of
100755.

Fix: after any edit to a `.sh` file, immediately run
`chmod +x path/to/script.sh` and verify with `ls -l`. The Phase 4 validation
block of any batch that touches a shell script must explicitly check the
executable bit.

This bit CHANGE-17.7 once and was caught by post-edit `ls -l`.

## `tee | head` truncates captured logs via SIGPIPE

The pattern `command 2>&1 | tee /tmp/log.txt | head -N` looks like it
captures the full output and previews the first N lines. It does not. Once
`head` exits after N lines, it closes the pipe; `tee` then aborts writing
to the file, leaving an N-line file. Subsequent `wc -l`, `grep -c`, etc.
all read the truncated file and miscount.

Fix: write to the file first, read separately afterwards.

```
command > /tmp/log.txt 2>&1
head -N /tmp/log.txt
tail -N /tmp/log.txt
grep -c PATTERN /tmp/log.txt
```

This bit CHANGE-17.7's audit-count check and almost shipped a wrong number.

## Root-owned files from container bind mounts

The `mcr.microsoft.com/playwright:v1.59.1-jammy` image runs as root. Any
files it creates inside a host bind mount (e.g. `node_modules/` after
`npm install` in `runner.sh`) are owned by root on the host. WSL user
cannot `rm -rf` them; `Permission denied` floods the terminal.

Fix: clean up via a throwaway container with the same image.

```
docker run --rm \
  -v "$(pwd)/scripts/playwright_admin_smoke:/work" \
  -w /work \
  --entrypoint bash \
  mcr.microsoft.com/playwright:v1.59.1-jammy \
  -c 'rm -rf node_modules'
```

The committed Playwright runner installs its `node_modules/` on first
invocation and reuses it on subsequent runs. The directory is gitignored
via the repo's existing top-level `node_modules/` rule. If you ever need
to force a clean reinstall, use the snippet above.

## Multi-line content through the WSL bridge

The pattern `wsl.exe -d Ubuntu -- bash -lc "...heredoc..."` does not
survive the outer double-quoted string: the heredoc terminator gets eaten
by the outer quoting and the command runs with empty stdin.

Fix: write multi-line content (commit messages, file bodies) via the Write
tool to a tempfile first, then invoke `git commit -F /path/to/tempfile`
or equivalent.

This bit the merge of `frontend-claude-design-port` once. The recovery was
clean (the failed merge produced no commit; the message was rewritten to a
tempfile and the merge re-ran), but the time cost was real.

## Audit script invocation

The committed Playwright admin UI smoke is runnable as documented in
`scripts/playwright_admin_smoke/README.md`. The first run installs
`playwright@1.59.1` into the bind mount; subsequent runs reuse it.

Expected results on a healthy branch: 42 PASS, 0 FAIL, 0 SKIP, 12 expected
console errors (all from COMPANY_ADMIN cross-tenant URL probes returning
403/404). Any unexpected FAIL or any console error originating from a path
the actor was authorised to view is a regression. Stop and diagnose.

If the smoke-super or user-3 fixture state has been disturbed by a previous
incomplete run (e.g. user 3 left soft-deleted), restore via the Django
shell snippet in the README. The audit's deactivate/reactivate flow leaves
state consistent on a successful run, but a failed run mid-flow can leave
artifacts.

## Frontend gate (node:22-alpine) and the measured-geometry rule

The frontend gate is three checks run inside a throwaway `node:22-alpine`
container against the bind-mounted `frontend/`:

```
sg docker -c "docker run --rm -v \"$(pwd)/frontend:/app\" -w /app node:22-alpine \
  sh -c 'npx tsc --noEmit -p tsconfig.app.json && npx eslint .'"
```

- `tsc --noEmit -p tsconfig.app.json` (Tier 1) must pass clean.
- `npx eslint .` must report **exactly 44 problems (42 errors, 2
  warnings)** as of `4823b17` — the frozen baseline, and the number
  CLAUDE.md carries. (48/46 until Sprint 179A; 44 until W8 added a
  third warning; 45 through W9; back to 44 once `0a5f725` removed it.
  CLAUDE.md is authoritative when the two disagree.) The two warnings
  are named in CLAUDE.md. Measure with ONE run and read the WHOLE
  output: tailing it is how W9's chats each blamed a different file for
  the same drift, including one file that had no warning at all.
  Capture it before AND after every
  commit and diff the per-file violation counts (`grep -oE
  '^/app/src/[^:]+' | sort | uniq -c`); the set must be identical modulo
  line-number shifts. Zero new violations, and (a standing rule since
  #109 Part J) **no new `eslint-disable` comments** — refactor to the
  starts-true loading idiom / guarded render-time state reset instead.
- `npm run build` (Tier 1 too) is the production build; run it before a
  screenshot/measurement pass since the preview server serves `dist/`.

**`tsc --noEmit -p tsconfig.app.json` is NOT a superset of the build's
type check — run all three, in this order, and treat a green Tier 1 as
no evidence about the build.** Sprint 179A passed `tsc --noEmit -p
tsconfig.app.json` clean and then `npm run build` failed on
`AgendaPage.tsx` with a real `TS2345` (a `string | null` handed to a
parameter typed `Role | null | undefined`). The two are different
invocations over different project graphs: `npm run build` runs
`tsc -b`, which builds the referenced projects in `tsconfig.json`, and
the `--noEmit -p` form checks one project on its own. Skipping the build
because "typecheck passed" is how a type error reaches a branch.

Two eslint rules from the React-Compiler plugin bite easily and are NOT
suppressible without a disable comment:
- `react-hooks/set-state-in-effect` — no synchronous `setState` at the
  top of an effect body. Clear/So set state inside the settled promise
  (`.then`/`.catch`/`.finally`) or start the state at its initial value.
- `react-hooks/preserve-manual-memoization` — do not add a `setState`
  call into an existing `useCallback` that the compiler had memoized;
  reset that state via a guarded render-time adjustment keyed on the id
  instead (the React "adjust state when a prop changes" pattern).

**Measured-geometry rule (standing since #109).** For any layout /
geometry / density claim — "full width", "no overflow", "the list
scrolls", "the preview is below the composer" — MEASURE the rendered
geometry with browser tooling and report the numbers; a screenshot
alone does not count. Drive the built `dist/` via `vite preview` + the
dev backend (see the branch-screenshots memory / token-inject pattern)
and read `boundingBox()` widths, `scrollHeight` vs `clientHeight`, or
`document.documentElement.scrollWidth > clientWidth`. To prove a scroll
cap bites regardless of seeded data, inject ≥50 synthetic rows into the
list via `page.evaluate` and confirm `clientHeight <= cap` with
`scrollHeight` far larger. Watch for cascade/specificity traps: a later
same-specificity rule can silently win (the #108 hero-grid used a
compound `.operations-kpi-grid.option-a-hero` selector to beat the base
`.operations-kpi-grid` media rules declared later in the file).

## Backend full-suite gate — a per-app pass is not a merge gate

CI's actual gate (`.github/workflows/test.yml`, the `Run test suite` step) is:

```
python manage.py test --noinput --verbosity=1 --parallel
```

That is the FULL backend suite (every app, ~3300 tests as of Sprint 137),
fanned across worker processes. A per-app run during development
(`python manage.py test accounts`, `python manage.py test invoicing`, ...)
is a fast, useful iteration check, but it is not equivalent to the CI gate
for two distinct reasons:

- **Cross-app fixture collisions.** A per-app run only ever sees that
  app's own test data. A new DB-level constraint (e.g. a partial
  `UniqueConstraint`) can be violated by a fixture pattern living in a
  completely different app's test module — per-app runs can't catch that
  because the colliding fixtures never share a process.
- **`--parallel`-only isolation bugs.** `--parallel` clones the test
  database per worker and distributes test classes across workers. A bug
  that depends on execution order, shared module-level state, or DB state
  leaking between test classes can pass sequentially and fail only under
  `--parallel` (or vice versa) — a different bug class from a plain
  assertion failure, needing different treatment (fix the isolation, not
  the assertion).

This container cannot substitute for CI on either count: it reports
`nproc=1` with no cgroup CPU limit, so `--parallel` forks no workers, and a
full sequential run takes roughly 168 minutes — even run to completion, it
still wouldn't reproduce CI's parallel conditions. Don't try to run the
full suite locally before pushing; treat CI as the actual full-suite gate
and use the targeted rule below instead.

**Standing rule:** when you change a shared service function, run every app
whose TESTS call it — not just the app whose files you edited.

Worked example: `grep -rln "reverse_invoice" backend --include=*.py` returns
`extra_work/tests/test_sprint127_2_label_lock.py` alongside the invoicing
files. Sprint 134 edited only `invoicing/`, so `extra_work` was never
re-run, and that is exactly why CI went red (a stale `extra_work` test had
documented pre-Sprint-134 double-reversal behaviour that Sprint 134's new
guard in `invoicing/state_machine.py` deliberately closed).

Also see [Parallel test runner traceback pickling](#parallel-test-runner-traceback-pickling-tblib)
below — in CI, a real failure inside a `--parallel` worker can be masked by
a `TypeError: cannot pickle 'traceback' object` from the reporter itself,
which reads as a totally unrelated crash if you don't know to look past it.

## Parallel test runner traceback pickling (tblib)

Django's `--parallel` test runner ships failing tests' exception info from
worker subprocesses back to the parent via `multiprocessing`, which means
pickling the `(exc_type, exc_value, traceback)` tuple. A raw Python
traceback object is not picklable by default. Confirmed directly against
the installed Django 5.2 runner source
(`django/test/runner.py::RemoteTestResult.check_picklable`): on a test
failure/error, the runner tries `pickle.loads(pickle.dumps(err))`; if that
itself raises, it prints a diagnostic ("tracebacks cannot be pickled... you
should install tblib") and **re-raises the pickling exception**, replacing
the original failure in the output.

Net effect: without `tblib` installed, a genuine assertion failure or
unhandled exception inside a `--parallel` worker can surface in CI logs as

```
TypeError: cannot pickle 'traceback' object
```

with the real failure's message and stack trace gone. `backend/requirements.txt`
pins `tblib` (Sprint 137) specifically so this class of failure stops being
unreadable — `tblib.pickling_support.install()` monkey-patches traceback
objects to make them picklable, which Django's runner uses automatically
when the package is importable (`if tblib is not None:
tblib.pickling_support.install()`). No runner-side configuration needed
beyond having the dependency installed.

## `ConfirmDialog` / native `<dialog>` is imperative — two distinct ways to get it wrong

`ConfirmDialog` (`frontend/src/components/ConfirmDialog.tsx`) wraps a
native `<dialog>` element behind a `forwardRef` + `useImperativeHandle`
handle (`{ open, close }` calling `showModal()` / `close()`). A native
`<dialog>` does NOT become visible just because it is mounted in the
DOM — unlike a normal conditionally-rendered `<div>` modal, mounting it
is not showing it, and unmounting it is not the only way to hide it.
That single fact produces two opposite-looking bugs from the same root
cause:

**Mount without `.open()` → the trigger button looks dead.** Wrapping
`<ConfirmDialog ref={dialogRef} .../>` in a conditional render (`{mode
=== "delete" && <ConfirmDialog .../>}`), the way a normal CSS-shown/
hidden modal would be, mounts an INVISIBLE `<dialog>` — nothing shows
until code explicitly calls `dialogRef.current.open()`. A caller that
sets the triggering state but never calls `.open()` sees no dialog, no
error, just a button that appears to do nothing. This shipped in Sprint
128 and was found by the owner in testing, not by CI or review.

**Unmount without `.close()` first → the whole page goes inert.**
Conversely, if a component holding an OPEN `<dialog>` (i.e. `.open()`
was called, `showModal()` is active) unmounts without calling `.close()`
first, the browser can leave the document in the modal's inert state —
the page LOOKS normal but nothing is clickable anywhere, including
outside where the dialog was. This is the frozen-screen bug Sprint 118
root-caused and fixed (see
`docs/archive/2026-06-sprints/sprint-116-119-build-log.md`) — the fix
was, and remains, calling `.close()` in the unmounting code path (a
cleanup effect, or before whatever state change causes the unmount)
rather than just letting the DOM node disappear.

**Fix, both directions:** always render `<ConfirmDialog>` unconditionally
(never behind `{condition && ...}`) and drive it ENTIRELY through the ref
— `.open()` to show it, `.close()` before any unmount or before the
underlying data it references goes away. The existing `useRef` +
`.open()` call sites elsewhere in the codebase are the pattern to copy;
a new dialog usage that looks different from those is worth a second
look before it ships.

This bit Sprint 128 (dead-looking delete button, invisible dialog) and
Sprint 118 (frozen screen, inert document) — the same imperative-API
mistake in both directions, three sprints apart, because the gotcha was
never written down after the first one.
