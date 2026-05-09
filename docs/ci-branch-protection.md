# CI and branch-protection settings for `master`

> **Status:** documentation only. The settings below cannot be set
> from the repo; an admin must apply them on GitHub. The CI workflow
> they reference (`.github/workflows/test.yml`) is already in the
> repo and runs on every PR + push to `master`.

This document is the canonical reference for the GitHub settings the
operator must apply to `master` before pilot launch. It is short on
purpose — the settings should match what is documented here, no
more, no less.

---

## What CI already runs (verified)

The workflow at [.github/workflows/test.yml](../.github/workflows/test.yml)
defines two jobs:

| Job | What it runs | Required for merge |
|---|---|---|
| `Backend (Django, Postgres, Redis)` | `manage.py check`, `manage.py makemigrations --check --dry-run`, `manage.py test --noinput --verbosity=1` against Postgres-16 + Redis-7 service containers | **yes** |
| `Frontend (lint, tsc, vite build)` | `npm ci`, `npm run lint` (informational, `continue-on-error: true` until the existing 33 pre-existing lint errors are cleared), `npm run build` (`tsc -b && vite build`) | **yes** |

The image-publishing workflow at
[.github/workflows/build-images.yml](../.github/workflows/build-images.yml)
publishes backend + frontend images to GHCR on master pushes /
release tags. It is **not** a merge gate (it runs after merge), so
do not add it to required-status-checks below.

---

## Required GitHub settings on `master`

Apply these via **Repository Settings → Branches → Branch protection
rules → master**:

### Pull-request requirements

- [ ] **Require a pull request before merging** = ON
  - **Require approvals** = 1 (one reviewer must approve)
  - **Dismiss stale pull request approvals when new commits are pushed** = ON
- [ ] **Require linear history** = ON (rejects merge commits with
  multiple parents — keeps the history readable)
- [ ] **Require conversation resolution before merging** = ON
  (every review comment must be resolved before merge)

### CI / status check requirements

- [ ] **Require status checks to pass before merging** = ON
  - **Require branches to be up to date before merging** = ON
    (forces the PR to rebase / merge from `master` before the green
    CI badge counts; otherwise a stale PR can merge against current
    master without re-running CI)
  - **Required status checks** (these are the workflow `name:` fields,
    NOT job ids):
    - `Backend (Django, Postgres, Redis)`
    - `Frontend (lint, tsc, vite build)`

### Push restrictions

- [ ] **Restrict who can push to matching branches** = ON
  - Allowed pushers: empty list (so nobody can push directly to
    master — every change goes through a PR)
- [ ] **Block force pushes** = ON
- [ ] **Restrict deletions** = ON (master cannot be deleted)
- [ ] **Do not allow bypassing the above settings** = ON
  (admins included — an admin can still merge by approving and
  passing CI, but cannot push directly)

### Optional (recommended, not blocking)

- [ ] **Require signed commits** = ON
  (requires every contributor to set up a signing key; nice for an
  audit trail but adds friction; defer to operator preference)

---

## How to verify the settings took effect

Open any PR against master. The merge button should:

1. Be **disabled** until the two required CI jobs are green
   (`Backend (Django, Postgres, Redis)` + `Frontend (lint, tsc,
   vite build)`).
2. Be **disabled** if the PR has no approving review.
3. Show **"This branch is out of date — Update branch"** when the
   base has moved on; clicking that button rebases / merges from
   master and triggers a new CI run.

If any of those three is missing, the protection rule is not
configured correctly.

---

## Why these specifically

- **Required CI** prevents the obvious failure mode: a PR merges
  green-on-author-machine but red on a clean Postgres+Redis CI
  environment.
- **Branches up to date** prevents the subtle failure mode: PR A is
  green at commit 100; master moves to commit 105 with a conflicting
  schema change; PR A merges without re-running CI on the merged
  state.
- **No direct push + no force push** prevents accidental local-master
  commits and prevents history rewrites that would make the audit
  log of merges meaningless.
- **Linear history** keeps `git log --oneline master` legible — every
  line is a real change, not a merge of merges.
- **One approval** is a process gate, not a security gate. For a
  pilot with two collaborators it is enough; for a wider rollout the
  operator should consider raising it to 2 or adding a CODEOWNERS
  file.

These rules apply to `master`. Sprint branches push freely; the gates
fire when they open a PR.

---

## What this document is NOT

- Not a guide to configuring a new repo — it assumes the workflow
  files already exist.
- Not a substitute for the actual GitHub settings — it is an audit
  reference. After applying the settings, this file is the
  documented contract; if the settings drift the operator can spot
  the mismatch by reading this file and comparing.
