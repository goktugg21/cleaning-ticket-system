# Sprint 22 — Pilot UX audit

This sprint reviewed the product from the point of view of a
first-time cleaning-company user and fixed the copy / helper-text
issues most likely to block a smooth pilot. No business logic,
authorization, scope, or data-model behaviour was changed.

## 1. Pages reviewed

- Login (`/login`) — including the demo-card panel gated by
  `VITE_DEMO_MODE=true`
- Password reset confirm (`/auth/password/confirm`)
- Dashboard / ticket list (`/`)
- Ticket detail (`/tickets/:id`)
- New ticket (`/tickets/new`)
- Admin: Companies / Buildings / Customers / Users / Invitations /
  Audit log
- Reports (`/reports`)
- Settings / profile (`/settings`)

## 2. UX issues found

| # | Page | Finding |
|---|---|---|
| 1 | Audit log | Whole page was English-only. Titles, filter labels, table headers, action labels (`Create` / `Update` / `Delete`), empty state, "Previous"/"Next" — none used the i18n layer. A Dutch demo audience would have seen English mid-sentence. |
| 2 | Audit log | The action-type filter labels rendered the raw enum string `Create / Update / Delete`. First-time users had no copy explaining what the page is for; no introduction paragraph. |
| 3 | Password reset | All on-page strings hardcoded English: title, subtitle, both field labels, "Saving…", "Set new password", "Back to sign in", "Hide / Show password" aria-labels, and the "incomplete link" error. Dutch UI was inconsistent with the rest of the auth flow. |
| 4 | Invitations | The Revoke-invitation confirm dialog used a template literal `Revoke invitation to ${email}?` and the body / confirm-button strings were hardcoded. Dutch operators saw English on a destructive action. |
| 5 | API errors | `getApiError` only had a humane sentence for HTTP 401. Every other status path either echoed the server's `detail` (which could be very technical) or fell back to "Network Error" / "Request failed with status 403". |
| 6 | Login | The email placeholder was `name@veridian.com` — a fictional reference from a design template. Pilot users may not recognise it as a placeholder. |
| 7 | Login demo cards | The super-admin card sat above Company A and Company B with no sub-label, so the visual hierarchy "one super admin → two companies" was not obvious. |
| 8 | Login demo cards | Company A / Company B group labels were hardcoded literal strings (`"Osius Demo — B Amsterdam"`) — not i18n. |
| 9 | Company form | `company_form.forbidden_title` rendered the word **"Forbidden"** in the empty-create-page banner. To a first-time user that reads like a denied permission error, not "your role is too low for this action". |
| 10 | New ticket | First-time users didn't see a top-level reminder that fields marked `*` are required. The `no_access_message` told them they had no access but not what to do next. |

## 3. Changes made

### a. AuditLogsAdminPage fully localised

[frontend/src/pages/admin/AuditLogsAdminPage.tsx](../../frontend/src/pages/admin/AuditLogsAdminPage.tsx)
now reads every visible string from a new `audit_logs.*` namespace
under `common.json` (en + nl), including:

- title / loading subtitle / count (with i18next plural rules)
- new intro paragraph explaining what the page records
- all 5 filter labels + placeholders ("Record type", "Record id",
  "Actor user id", "From", "To")
- action chip labels ("Created" / "Updated" / "Deleted")
- empty-state title + description for initial AND filtered cases
- "Apply filters", "Clear filters", "Previous", "Next"
- the page now reuses the shared `admin.pagination_page` format
  instead of its own English string

The action-tag's CSS class still uses the raw `CREATE/UPDATE/DELETE`
enum, so the visual state machine stays language-agnostic; only the
visible label changes per locale.

### b. ResetPasswordConfirmPage localised

[frontend/src/pages/ResetPasswordConfirmPage.tsx](../../frontend/src/pages/ResetPasswordConfirmPage.tsx)
now reads every string from the existing `login` namespace via a new
`reset_*` key family. Same set of fields as before, no behaviour
change — a Dutch UI now renders a Dutch reset page.

### c. Invitations revoke confirm dialog localised

[frontend/src/pages/admin/InvitationsAdminPage.tsx:818-829](../../frontend/src/pages/admin/InvitationsAdminPage.tsx#L818-L829)
swaps the hardcoded template literal for two new keys
(`invitations.dialog_revoke_title` with `{{email}}` interpolation
and `invitations.dialog_revoke_title_no_email`) plus
`invitations.dialog_revoke_body` and
`invitations.dialog_revoke_confirm`. The confirm button now reads
"Revoke invitation" instead of a bare "Revoke" so the destructive
action is clearer.

### d. `getApiError` made first-time-user friendly

[frontend/src/api/client.ts:123-176](../../frontend/src/api/client.ts#L123-L176)
keeps surfacing DRF-shaped `detail` / first-field messages verbatim
when present (those are usually the most precise), but adds a
status-aware fallback that resolves through the new `api_error.*`
i18n keys:

| HTTP | New sentence (en) |
|---|---|
| 401 | "Your session expired. Sign in again to continue." |
| 403 | "You don't have permission to perform this action." |
| 404 | "We couldn't find what you were looking for…" |
| 400 | "Some of the values you entered are not valid…" |
| 429 | "Too many requests in a short time…" |
| 5xx | "The server is having trouble right now…" |
| Network | "We can't reach the server. Check your connection…" |
| (other) | "Something unexpected happened. Please try again." |

The function is non-React; it imports the global `i18next` instance
to resolve keys at call time, so a language switch picks up
immediately on the next failure.

### e. Login page polish

- [frontend/src/i18n/en/login.json](../../frontend/src/i18n/en/login.json):
  `email_placeholder` changed from `name@veridian.com` to
  `you@company.com`. Dutch counterpart updated to
  `u@uw-bedrijf.nl`.
- New section labels `demo_section_super`,
  `demo_section_company_a`, `demo_section_company_b`, and the
  one-line scope hint `demo_super_scope` ("Both companies").
- [frontend/src/pages/LoginPage.tsx:294-326](../../frontend/src/pages/LoginPage.tsx#L294-L326):
  the super-admin card now sits under its own "Super admin (sees
  everything)" label, mirroring the Company A / Company B grouping
  below. A scope hint ("Both companies") sits inside the card so
  the role's reach is visible without consulting the seed doc.
- The previous hardcoded `COMPANY_A_LABEL` / `COMPANY_B_LABEL` TS
  constants were removed in favour of i18n keys
  (`demo_section_company_a` / `demo_section_company_b`).

### f. Company-form "Forbidden" → "Super admin access required"

[frontend/src/i18n/{en,nl}/common.json](../../frontend/src/i18n/en/common.json)
`company_form.forbidden_title` was the literal English word
"Forbidden" (and "Verboden" in Dutch). Both are technical and read
like an access-denied lock screen. Replaced with "Super admin
access required" / "Toegang vereist: superbeheerder", which matches
the existing supporting body text.

### g. New-ticket page helper text

- New `required_fields_hint` / `velden met * zijn verplicht.` key
  rendered just under the page subtitle so the `*` convention is
  obvious before the user reaches the first required field.
- `no_access_message` extended with a concrete next step: "Ask
  your company admin to grant access, then refresh this page."

## 4. What was intentionally NOT changed

- **No third demo company.** Per sprint brief, the two-company
  setup stays exactly as Sprint 21 v2 ended.
- **No authorization or scope changes.** Every change is a string
  or helper-text edit; the scoping helpers, the `CanManageUser`
  permission class, and the customer-user pair check are all
  untouched.
- **No change to the Sprint 21 v2 demo account matrix.** All 11
  canonical accounts and their roles are unchanged.
- **No production-safety check weakened.** `check_no_demo_accounts`
  retains every entry from Sprint 21 v2; no demo TLD suffix was
  removed.
- **No admin-table card transform.** The survey flagged that admin
  tables (Companies / Buildings / Customers / Users) still rely on
  horizontal scroll on phones. Sprint 20 already transformed the
  Invitations Activity table. Adding the same transform to all
  admin pages would be a one-day task on its own and was deferred
  rather than rushed into Sprint 22.
- **Reports page copy.** The Reports page already has thoughtful
  per-chart titles + subtitles and an existing locale namespace.
  No first-time-user-confusing string was found there.
- **Dashboard subtitle.** "{{count}} total tickets · {{visible}}
  visible · page {{page}} of {{pages}}" is dense but accurate and
  uses i18n. A simpler form would lose information; kept as-is.

## 5. Test results

| Step | Result |
|---|---|
| `manage.py check` | 0 issues |
| Full backend suite | **552 / 552 OK** (no backend changes — this just confirms the i18n changes did not ripple into a backend test) |
| `npm run build` | clean, 2775 modules, 449ms |
| Playwright full suite (rebuilt demo stack `VITE_DEMO_MODE=true`) | **190 / 190 OK** in 5.1 min |

## 6. Files touched

```
backend  — none
frontend
  src/api/client.ts                                — getApiError rewrite
  src/pages/LoginPage.tsx                          — demo section labels
  src/pages/ResetPasswordConfirmPage.tsx           — full i18n
  src/pages/CreateTicketPage.tsx                   — required-fields hint
  src/pages/admin/AuditLogsAdminPage.tsx           — full i18n
  src/pages/admin/InvitationsAdminPage.tsx         — revoke dialog i18n
  src/i18n/en/common.json                          — +audit_logs.*, +api_error.*, +invitations.dialog_revoke_*, "Forbidden" fix
  src/i18n/nl/common.json                          — same keys in Dutch
  src/i18n/en/login.json                           — +reset_*, +demo_section_*, email placeholder
  src/i18n/nl/login.json                           — same keys in Dutch
  src/i18n/en/create_ticket.json                   — +required_fields_hint, expanded no-access copy
  src/i18n/nl/create_ticket.json                   — same keys in Dutch
docs
  docs/audit/sprint-22-pilot-ux-audit.md           — new
```

## 7. Remaining nice-to-haves for after `v0.1.0-pilot`

These are visible but small; not blocking for pilot:

1. **Admin tables → card transform on mobile.** Companies /
   Buildings / Customers / Users / Audit-log tables still rely on
   horizontal scroll on phones. Sprint 20 set the pattern in the
   Invitations Activity card; replicating it everywhere is a
   focused 1-day follow-up.
2. **Audit-log "Record type" picker.** Currently a free-text field
   that requires the user to know the Django app label
   (`accounts.User`). A small dropdown of allowed values would
   eliminate guesswork. Backend filter shape supports this without
   a server change.
3. **`/api/users/` actor lookup.** The audit log's "Actor user id"
   filter takes a numeric id — operator-friendly would be an
   autocompleted email search. Larger feature, post-pilot.
4. **Dashboard subtitle simplification on phone.** The dense
   "X total · Y visible · page Z" line shrinks awkwardly under
   430 px. A media-query-driven shorter form ("X tickets · page Z")
   would read better on phones.
5. **In-form password-strength hint.** The settings / reset pages
   both validate `>= 8` chars but don't surface that requirement
   until after a failed submit. A live "8+ characters, mix of
   letters and numbers" hint under the field would help.
