# Documentation index

This file is the **map of the documentation tree**. It is the single place
that lists every *live* (maintained) document. **If a document is not listed
in the table below, it is archived and unmaintained** — see the
[Archive](#archive) section. Do not rely on an unlisted doc as current truth.

---

## Live documents

| Path | What it covers | Update trigger |
|---|---|---|
| [README.md](README.md) | This index — the map of live vs archived docs. | Whenever a doc is added, moved, renamed, or archived. |
| [product/source-of-truth.md](product/source-of-truth.md) | Canonical product **target state**: what the system must become, what already works, what changes next, and the sprint order. The authoritative statement of *what the system is*. | Whenever the product target state changes. |
| [product/sot-addendum-a-meeting2.md](product/sot-addendum-a-meeting2.md) | **Addendum A** (Ramazan Meeting 2, 2026-06-05): revises the base SoT — company-wide Customer Company Admin, people management (Contacts/Users/Employees), recurrence/calendar model. **Wins over the base SoT for the items it covers.** | When a later stakeholder meeting refines the SoT. |
| [product/system-business-logic-and-workflows.md](product/system-business-logic-and-workflows.md) | Plain-English business logic: roles, permissions, ticket + Extra Work workflows, note-visibility taxonomy, audit rules, privacy floor. | Whenever business logic or a workflow changes. |
| [product/requirements-meeting-2026-05-15.md](product/requirements-meeting-2026-05-15.md) | Stakeholder-meeting requirements (Contacts vs Users, modular per-location permissions, view-first UI, Extra Work cart, pricing model, proposal builder, override audit). The **product floor**, at the same authority as the RBAC matrix. | When the underlying stakeholder requirements change. |
| [product/role-visibility-matrix.md](product/role-visibility-matrix.md) | Role → left-nav visibility matrix, every cell sourced from code (frontend nav gate **and** backend enforcement). | Whenever the frontend nav gate or backend role scoping changes. |
| [planning/sprint-checklist.md](planning/sprint-checklist.md) | The living gap-closing sprint plan; boxes are ticked as each sprint completes. | Every sprint. |
| [reference/rbac-matrix.md](reference/rbac-matrix.md) | Canonical RBAC / permissions / role-hierarchy source of truth, including the 11 hard invariants (H-1..H-11) — the **security floor**. | Whenever a role, permission key, scope rule, or hard invariant changes. |
| [engineering/claude-code-operational-notes.md](engineering/claude-code-operational-notes.md) | WSL / shell / container gotchas (Edit drops the +x bit, SIGPIPE truncation, root-owned Playwright artifacts, heredoc-over-the-bridge). | Whenever a new operational gotcha is learned. |
| [engineering/deployment.md](engineering/deployment.md) | Production deploy runbook: topology, env vars, the proxy headers Django expects, SES SMTP bootstrap, compose-level decisions. | Whenever the deploy topology or env contract changes. |
| [engineering/ci.md](engineering/ci.md) | CI/CD: the three GitHub Actions workflows (test.yml, playwright.yml, build-images.yml) and their triggers. | Whenever a CI workflow changes. |
| [engineering/env-setup.md](engineering/env-setup.md) | How to prepare the production `.env` (copy the template, generate the secret key, set domain/hosts). | Whenever the env contract or `.env.production.example` changes. |
| [engineering/backup-restore.md](engineering/backup-restore.md) | Backup & restore runbook: daily backups, retention, and the restore drill that gates go-live. Wraps the pg/media backup scripts. | Whenever the backup/restore scripts or procedure change. |
| [engineering/media-storage.md](engineering/media-storage.md) | Media storage strategy: the local Docker-volume rationale and the conditions under which it must change. | Whenever the media storage strategy changes. |

> `docs/transkript.txt` is a raw stakeholder transcript. It is intentionally
> **not** a maintained doc, must never be staged or quoted, and is therefore
> excluded from this index.

---

## Document hierarchy (which source wins)

1. **`product/source-of-truth.md` is authoritative for *what the system is*.**
2. **An Addendum wins over the base Source of Truth for the items it covers**
   (today: `product/sot-addendum-a-meeting2.md`).
3. **Where the docs and the code disagree, the code is the truth.** The drift
   must be **reported**, not silently followed — stop, surface the mismatch,
   and propose a fix.

---

## Archive

Everything under `docs/archive/` is kept for **history only**. Each archived
file carries an `ARCHIVED` banner at the top stating the date it last
described the system. Archived docs are **not maintained** and must not be
relied on as current truth. There are four buckets:

- **`archive/2026-05-pilot/`** — pilot-era launch, demo, and handoff material
  (go-live, demo scripts, the point-in-time security review, SES setup, pilot
  readiness/acceptance checklists, the frontend-design handoff).
- **`archive/2026-05-sprints/`** — sprint design and audit documents from the
  2026-05 sprint series (codebase/business-logic audits, sprint-23/28/29
  plans, the 2026-05 gap analysis).
- **`archive/superseded/`** — documents describing a model that no longer
  exists in the repo (the old `.claude/agents` backlog / PM-dispatch workflow,
  and the earlier P0 fix plan / audit report).
- **`archive/ideas/`** — unimplemented future concepts (bank-transaction
  matching, subscription billing). These are **ideas, not commitments.**

Archived scripts live under `scripts/archive/` and follow the same rule.

---

## Adding a new doc

Every new document is added to the **Live documents** table above **in the
same commit that creates it** — with its path, what it covers, and its update
trigger. A doc that is not in this table does not get created; if it is not
worth indexing, it is not worth adding.
