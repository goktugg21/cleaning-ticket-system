# Merge recipe — the redesign train into `main` (P-16 Part G)

**This merge runs ONLY on the owner's word.** Prepared 2026-09-03; the
dry run (`git merge --no-commit --no-ff` of the train tip into
`origin/main` in a scratch worktree) completed with **zero conflicts**.
The sequence, when the word comes:

```bash
git checkout main
git pull origin main
git merge --no-ff feat/p16-nothing-left \
  -m "Merge the frontend redesign train (P-7 … P-16)"
git tag v2026.09-redesign
git push origin main --tags
```

Then deploy crmtest from `main` (the compose stack is unchanged —
same `docker-compose.prod.yml`, same six containers; the backend
recreate auto-runs `migrate && collectstatic`):

```bash
git checkout main   # on the dev server
sg docker -c 'docker compose -f docker-compose.prod.yml up -d --build backend frontend worker beat'
```

## What main gains

- ~337 commits (WP-1 → FE-1…FE-7 → P-1…P-16), **including the
  `feat/ew-gap-closing` chain (Sprints 153–189)** the train is stacked
  on — merging the train tip brings that history whether or not its
  own PR is opened first. If the owner merges `feat/ew-gap-closing`
  first (the fast-forward PR the checklist describes), this merge
  simply gets smaller; the order does not matter to the result.
- The migrations `main` does not have (auto-applied on the first
  backend recreate): contracts 0005–0006, extra_work 0033–0038,
  notifications 0017–0022, planned_work 0006, reports 0001, sla
  0001–0002, tickets 0027–0034, timesheets 0010. All additive; none
  edits an applied migration.

## What "merge" does NOT do

- **No production exists.** The compose stack on crmtest is the only
  deployment; merging changes which branch it is built from, nothing
  else. Production deployment remains a separate, open milestone.
- **The tag is the restore point.** `v2026.09-redesign` marks the
  merge; anything that goes wrong after it is
  `git checkout v2026.09-redesign` away from a known state.
- Nothing is deleted at merge time. **One week after** a green merge,
  delete the train branches (each fully contained in `main`):
  `feat/ew-gap-closing`, `feat/wp1-*` (if present), `feat/fe-1` …
  `feat/fe-7-final-audit`, `feat/p1-honest-dates` …
  `feat/p16-nothing-left` — `git branch -d` locally,
  `git push origin --delete <name>` remotely. `git branch -d` (not
  `-D`) so an unmerged branch refuses instead of vanishing.

## After the merge

Sprints branch from `main` (CLAUDE.md §1 records the same line). The
stacked-train workflow ends with this merge; web-Claude verifies
future sprints against `origin/main`-based branches.
