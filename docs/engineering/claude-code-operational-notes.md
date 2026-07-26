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
- `npx eslint .` must report **exactly 49 problems (47 errors, 2
  warnings)** — the frozen baseline. Capture it before AND after every
  commit and diff the per-file violation counts (`grep -oE
  '^/app/src/[^:]+' | sort | uniq -c`); the set must be identical modulo
  line-number shifts. Zero new violations, and (a standing rule since
  #109 Part J) **no new `eslint-disable` comments** — refactor to the
  starts-true loading idiom / guarded render-time state reset instead.
- `npm run build` (Tier 1 too) is the production build; run it before a
  screenshot/measurement pass since the preview server serves `dist/`.

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
