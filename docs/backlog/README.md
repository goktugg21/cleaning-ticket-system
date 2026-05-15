# Backlog board

This directory is the **live work tracker** for the cleaning-ticket-system.
Only the `project-manager` sub-agent edits these files (see
[`../../.claude/agents/project-manager.md`](../../.claude/agents/project-manager.md)).

| File | Purpose |
|---|---|
| [PRODUCT_BACKLOG.md](PRODUCT_BACKLOG.md) | Prioritised feature work. Sprint-tagged items + standing GAP_ANALYSIS items. |
| [BUGS.md](BUGS.md) | Open defects with reproduction notes. |
| [DONE.md](DONE.md) | Append-only ledger of closed items + commit SHA. |

## How it flows

1. User asks for work → Claude routes to `project-manager`.
2. PM reads these three files + the matrix doc + last 5 commits.
3. PM picks the highest-priority unblocked item.
4. PM dispatches to `backend-engineer` and/or `frontend-engineer` via
   parallel `Agent` calls when independent.
5. Engineer ships the change, including tests and matrix-doc updates.
6. PM verifies (re-reads diff, runs tests), then moves the row from
   `PRODUCT_BACKLOG.md` / `BUGS.md` to `DONE.md` with the commit SHA.

## How a row is shaped

See the header of each file for the exact row template. Every row carries:

- A stable ID (`27F-B1`, `BUG-F2`, `BACKEND-CRUD-1`, …) so commits can
  reference it.
- A source pointer back to the gap doc or sprint design that motivates it.
- An owner: `backend-engineer`, `frontend-engineer`, or `both`.
- Acceptance criteria stated as observable behaviour.
- The test file the change must add or extend (or `NEEDS-TEST` if not
  written yet).
