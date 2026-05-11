# Sprint 22 — Final mobile + copy polish (before PR #49 merge)

This is the third (and last) pass on the Sprint 22 PR. The previous
generic admin table card-transform attempt was reverted and is NOT
reintroduced — instead each admin list page now emits its own
explicit mobile card markup alongside the existing desktop table,
matching the pattern that worked for the Dashboard on commit
`3ebd32b`.

## 1. Pages and flows reviewed

- Login + demo cards (no change — already polished in earlier pass)
- Password reset / set new password
- Accept invitation (password setup)
- Dashboard / ticket list (cards work, no change here)
- **Ticket detail** — activity timeline + status history list
- New ticket
- Reports
- Settings / profile (password change)
- **Admin: Companies / Buildings / Customers / Users / Audit log**
- /admin/invitations (Sprint 20 pattern already covers it)
- EN ↔ NL parity for every key added

## 2. Issues found

| # | Severity | Finding |
|---|---|---|
| 1 | High | Ticket-detail Activity timeline and Status history both rendered the seed-generated note `seed_demo_data → IN_PROGRESS` verbatim. Demo customers (Tom, Iris, Amanda, …) saw `Superadmin changed status from Open to In progress. seed_demo_data → IN_PROGRESS.` |
| 2 | High | The 5 admin list pages (Companies / Buildings / Customers / Users / Audit logs) still depended on horizontal table scroll on phones, cramping the demo experience on iPhone 14 Pro Max and below. |
| 3 | Medium | Password helper text (`"Use at least 8 characters."`) was technically correct but did not mention the two other Django validators (CommonPasswordValidator, NumericPasswordValidator) that the backend enforces. Reset and accept-invitation pages had no helper text at all. |

## 3. Safe fixes made

### 3.1 Internal variable name leak (Part A)

[`frontend/src/pages/TicketDetailPage.tsx:113-127`](../../frontend/src/pages/TicketDetailPage.tsx#L113-L127)
adds a module-level `sanitizeStatusNote()` helper that drops any
status-history note whose value matches `^seed_demo_data\b` or
contains `seed_demo_data →`. Both render sites are wired through
the helper:

- the Activity timeline (line ~587) — `entry.note`
- the Status history list (line ~1190) — `item.note`

Result: the seeded `seed_demo_data → IN_PROGRESS` text is filtered
out at render time. Operator-typed notes are preserved verbatim.
Backend code is unchanged.

A new permanent Playwright regression test in
[`workflow.spec.ts:101`](../../frontend/tests/e2e/workflow.spec.ts#L101)
opens the `[DEMO] Closed kitchen tap` ticket (which walks through
4 transitions, so every history row's note is populated by the
seed) and asserts `timeline.textContent()` does NOT contain the
`seed_demo_data` substring.

### 3.2 Admin tables → mobile card pattern (Part B)

Same pattern the Dashboard now uses, applied per-page. Each admin
page emits TWO trees:

- the existing `<table className="data-table">` wrapped in
  `<div className="table-wrap admin-list-wrap">` — visible at
  ≥ 601 px (tablet / desktop) exactly as before
- a new `<ul className="admin-card-list" data-testid="admin-card-list">`
  with one `<li className="admin-card">` per row — visible at
  ≤ 600 px (phones)

A single new CSS block at the end of
[`index.css`](../../frontend/src/index.css) gates the swap:
`.admin-card-list { display: none }` by default;
`@media (max-width: 600px)` hides `.admin-list-wrap` and shows
`.admin-card-list` as a flex column of bordered cards. The CSS
itself is shared; the markup is per page, so each card shows the
right metadata for that entity.

Pages converted:

| Page | Card identity | Body rows | Footer |
|---|---|---|---|
| Companies | name (bold) + Active/Inactive pill | SLUG / DEFAULT LANG / CREATED | Edit (full-width) |
| Buildings | name + pill | COMPANY / ADDRESS / CREATED | Edit |
| Customers | name + pill | COMPANY / BUILDING / CONTACT EMAIL | Edit |
| Users | email + pill | NAME / ROLE / LANGUAGE | Edit |
| Audit log | timestamp + Created/Updated/Deleted pill | ACTOR / RECORD / REQUEST | Show changes ▶ JSON |

Each card is itself a `<Link>` (except audit log, which is
non-clickable like the desktop table). The link has `min-height:
44px` so the tap target is comfortable. Manual screenshots at
360 / 390 / 430 px confirm: no horizontal body overflow, no
clipped columns, pills do not overlap, Edit button reachable,
audit-log JSON disclosure works inside the card.

The `/admin/invitations` page already has its own mobile card
transform from Sprint 20 — it is NOT touched.

Two existing mobile_layout tests were updated to assert against
the new card list at 390 px instead of the now-hidden
`.data-table tbody tr`:

- `mobile_layout.spec.ts:237` admin users page readability →
  asserts `[data-testid="admin-card-list"] .admin-card`
- `mobile_layout.spec.ts:249` /admin/audit-logs renders →
  asserts `[data-testid="audit-card"]` or `[data-testid="audit-empty"]`
- `mobile_layout.spec.ts:631` /admin/users pagination reach →
  selector list extended to include `.card .admin-card-list`

### 3.3 Password helper copy (Part C)

Sprint 22's first pass shipped a thin `"Use at least 8 characters."`
hint. This pass extends it to describe the two additional Django
validators the backend enforces. Three keys added (each EN + NL):

- `settings.password_requirements_hint` →
  *"Use at least 8 characters. Avoid very common or all-numeric
  passwords." / "Gebruik minimaal 8 tekens. Vermijd veelgebruikte
  of volledig numerieke wachtwoorden."*
- `login.reset_password_requirements_hint` — same copy
- `common.accept_invitation.password_requirements_hint` — same copy

Wired into:

- [SettingsPage.tsx](../../frontend/src/pages/SettingsPage.tsx) —
  shown under New password, linked via `aria-describedby`.
- [ResetPasswordConfirmPage.tsx](../../frontend/src/pages/ResetPasswordConfirmPage.tsx)
  — same.
- [AcceptInvitationPage.tsx](../../frontend/src/pages/AcceptInvitationPage.tsx)
  — same. (The accept-invitation flow previously had no helper
  copy at all.)

The hint matches the actually-enforced validators
(`MinimumLengthValidator(min_length=8)`, `CommonPasswordValidator`,
`NumericPasswordValidator`) — no invented frontend rule.
`UserAttributeSimilarityValidator` is intentionally not mentioned;
the message would require a longer explanation than a hint allows.

## 4. Items intentionally deferred / not changed

| Item | Reason |
|---|---|
| `humanName()` on the status-history list (`item.changed_by_email`) | Sprint 22 first pass left the technical-view list as-is; only the Activity timeline humanizes the actor. Changing the audit list shape would risk losing forensic detail. |
| Audit log `target_model` free-text → dropdown | The free-text input was kept exactly as it is on master. The Sprint 22 first pass that added the dropdown was part of the reverted commit; I am not reintroducing it in this polish-only pass. |
| Audit log actor autocomplete | Still deferred (component complexity) — `<UserPicker />` is a Sprint 23 follow-up. |
| Generic `.data-table-cards` CSS class | Explicitly NOT reintroduced. Per-page mobile markup is the correct, safer pattern. |
| Tablet (768 px) admin layout | Untouched; tablet still sees the desktop table. The new CSS block only fires below 600 px. |

## 5. Risk notes

| Change | Risk |
|---|---|
| `sanitizeStatusNote()` in TicketDetailPage | LOW. Pure pre-render string filter; only matches `seed_demo_data` markers. Real operator notes (no `seed_demo_data` substring) flow through unchanged. Backend untouched. New regression test guards against regressions. |
| Admin mobile card list (5 pages) | LOW. CSS is opt-in via a new `.admin-card-list` / `.admin-list-wrap` class pair. Desktop and tablet are guaranteed unchanged because the new block is inside `@media (max-width: 600px)` and the cards default to `display: none`. The existing Playwright admin_crud + scope + mobile_layout suites all still pass. |
| Password helper text | NONE. Pure decoration with `aria-describedby` link; no validation behavior change. EN + NL parity verified. |

## 6. Test results

| Step | Result |
|---|---|
| `manage.py check` | **0 issues** |
| `npm run build` (Vite) | clean, **507 ms**, 2775 modules |
| Rebuilt frontend image with `VITE_DEMO_MODE=true` | OK |
| `seed_demo_data --i-know-this-is-not-prod` (after rebuild) | OK; 11 active canonical users |
| Playwright full suite (rebuilt demo stack) | **192 / 192 OK** in 5.1 min (190 prior + 3 new dashboard mobile from `3ebd32b` − 1 retired) plus the new `seed_demo_data` regression test in `workflow.spec.ts` |
| Manual screenshots at 360 / 390 / 430 px on Companies / Buildings / Customers / Users / Audit logs | clean card stacks, no horizontal overflow, pills do not overlap, Edit buttons reachable |
| Backend test suite | Skipped this pass — no backend file modified. Last green run 552 / 552 OK at commit `2c3e7c9`. |

## 7. Files touched

```
frontend
  src/index.css                              — +.admin-card-list block (~110 lines)
  src/pages/TicketDetailPage.tsx             — sanitizeStatusNote() helper + 2 call sites
  src/pages/SettingsPage.tsx                 — password_requirements_hint
  src/pages/ResetPasswordConfirmPage.tsx     — reset_password_requirements_hint
  src/pages/AcceptInvitationPage.tsx         — accept_invitation.password_requirements_hint
  src/pages/admin/CompaniesAdminPage.tsx     — .admin-list-wrap + mobile card list
  src/pages/admin/BuildingsAdminPage.tsx     — same
  src/pages/admin/CustomersAdminPage.tsx     — same
  src/pages/admin/UsersAdminPage.tsx         — same
  src/pages/admin/AuditLogsAdminPage.tsx     — same
  src/i18n/en/common.json                    — accept_invitation.password_requirements_hint
  src/i18n/nl/common.json                    — same
  src/i18n/en/login.json                     — reset_password_requirements_hint
  src/i18n/nl/login.json                     — same
  src/i18n/en/settings.json                  — password_requirements_hint
  src/i18n/nl/settings.json                  — same
  tests/e2e/mobile_layout.spec.ts            — 3 admin-mobile assertions updated to use card list
  tests/e2e/workflow.spec.ts                 — +regression test for seed_demo_data note leak
docs
  docs/audit/sprint-22-final-mobile-and-copy-polish.md  — new (this doc)
```

## 8. Recommendation

**MERGE NOW.**

- 192 / 192 Playwright tests pass after every change in this pass.
- Frontend build is clean.
- Django check is clean; no backend change means the 552-test
  backend suite from `2c3e7c9` still applies.
- The previously reverted generic admin table card transform is
  NOT reintroduced; this pass uses per-page mobile markup as
  requested.
- Demo account matrix unchanged; no scope / permission / API /
  data-model behavior touched. EN ↔ NL parity verified on every
  new key.
- The biggest UX leak in the Sprint 22 first pass — the visible
  `seed_demo_data → IN_PROGRESS` note in every demo ticket
  timeline — is closed and guarded by a permanent regression test.
- Manual screenshots at 360 / 390 / 430 px on all 5 converted
  admin pages confirm the layout is clean, not cramped, and
  tap-friendly.

## 9. Suggested post-pilot follow-ups

- Sprint 23: shared `<UserPicker />` autocomplete component
  (consumed by audit-log actor filter + assignment dialogs).
- Sprint 23: audit-log changes-payload key/value viewer (replace
  the `<pre>{JSON.stringify(...)}</pre>`).
- Sprint 23: friendlier `target_model` dropdown on /admin/audit-logs
  (the v1 of this was reverted alongside the bad admin transform).
- Sprint 23: typed-confirm "type the company name to confirm"
  pattern on Company Deactivate, matching the Ticket Delete dialog.
