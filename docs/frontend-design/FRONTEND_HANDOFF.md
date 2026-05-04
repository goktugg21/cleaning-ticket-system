# CleanOps — Frontend Implementation Brief

**Reference mockup:** `claude-design-reference.html` (HTML/CSS prototype — port to React + TypeScript + Vite).
**Target:** existing repo at `~/cleaning-ticket-system/frontend/` (React + TS + Vite + DRF backend).

---

## Hard rules

1. **Do NOT redesign or reinterpret the Claude-designed pages.** Copy them as closely as possible — colors, spacing, typography, card style, layout architecture, hierarchy. Responsive adjustments only.
2. **Do NOT introduce Next.js, shadcn, or any new heavy UI library.** Use existing dependencies + `lucide-react` for icons.
3. **Do NOT touch Django / backend / security code.** Frontend only.
4. **Preserve existing P0 auth changes:**
   - Refresh-token replacement flow
   - Backend logout call
   - Demo credentials gated behind `import.meta.env.DEV || import.meta.env.VITE_SHOW_DEMO_USERS === 'true'`
5. **Keep TypeScript strict.** `npm run build` must pass.
6. **Do NOT invent backend endpoints.** If a UI element needs data that doesn't exist, derive it from the existing ticket list/detail data in a typed helper, and add a `// TODO(backend): replace with /api/...` comment.

---

## File targets

| Page / shell | File |
|---|---|
| Login | `frontend/src/pages/LoginPage.tsx` |
| Dashboard | `frontend/src/pages/DashboardPage.tsx` |
| Create ticket | `frontend/src/pages/CreateTicketPage.tsx` |
| Ticket detail | `frontend/src/pages/TicketDetailPage.tsx` |
| App shell / sidebar | `frontend/src/layout/AppShell.tsx` |
| API client | `frontend/src/api/client.ts` (only if absolutely necessary) |
| API types | `frontend/src/api/types.ts` (only if absolutely necessary) |

---

## 1. Login page — combine two Stitch references

The login is the **only** page where two references are merged. Everything else is 1:1 from the mockup.

### Left side — photographic panel (from photo-based Stitch reference)

- Full-bleed blurred facility / interior photo background.
- Dark overlay so text reads cleanly.
- **No** solid emerald/green illustration panel. **No** "24/7 Monitoring" / "SLA Enforcement" feature cards.
- Bottom-left tagline:
  - **Title:** "Precision. Efficiency. Excellence." (two lines, with break after "Efficiency.")
  - **Subtitle:** "Empowering facility managers with the tools to maintain pristine environments seamlessly."
- Mockup classes for reference: `.login-visual`, `.lv-tagline`, `.lv-tagline-title`, `.lv-tagline-sub`.
- For the photo: use a real photo asset (drop one at `frontend/src/assets/login-bg.jpg`) — the mockup's CSS scene is a stand-in, not part of the spec.

### Right side — premium form layout (from modern Stitch reference)

Vertical order, top to bottom:

1. **Compact brand row at top-left** — small green icon tile (32×32, rounded 8px) + "CleanOps" wordmark. Not centered.
2. **Vertically centered card area** containing:
   - **Welcome heading** (left-aligned):
     - h2: "Welcome Back" (32px, 800, tight tracking)
     - sub: "Access your CleanOps console."
   - **Quick-access demo cards** — GATED, see below.
   - **"Or continue with email" divider** — uppercase 10.5px label, hairlines on both sides.
   - **Form:**
     - Work Email field (mail icon left, placeholder `name@veridian.com`)
     - Password field (lock icon left, **eye toggle on right**, placeholder dots)
     - Inline label row above password: "Password" (left) + "Forgot password?" link (right, green, links to existing reset flow)
     - "Remember my device for 30 days" checkbox (single row)
     - **"Secure login"** primary button — full width, green, 44px tall

### Demo quick-access cards — GATING IS REQUIRED

Render the entire `Quick access for demo` block **only** when:

```ts
const SHOW_DEMO =
  import.meta.env.DEV ||
  import.meta.env.VITE_SHOW_DEMO_USERS === 'true';
```

Card structure (2-column grid, gap 10px):

- **Card 1** — JD avatar (initials in green-faint pill) + "John Doe" / "Facility Mgr" + green dot pill "Admin Role" → fills `manager@example.com` / `Test12345!`
- **Card 2** — AS avatar + "Anna Smith" / "Technician" + muted pill "Standard Role" → fills `customer@example.com` / `Test12345!`

Clicking a card prefills email + password and visually marks the card as selected (green border + faint green bg). It does **not** auto-submit.

In production builds without `VITE_SHOW_DEMO_USERS=true`, the demo block must not render at all (no empty space, no hidden DOM).

### Auth behavior — DO NOT BREAK

- Submit posts to existing login endpoint, stores tokens via existing storage layer.
- Refresh-token replacement on 401 stays as implemented.
- Logout calls the backend logout route as currently implemented.
- "Forgot password?" links to existing password-reset route — do not remove or rewire.

---

## 2. Dashboard page — 1:1 from mockup

Use the Claude design **exactly**. Composition stays as designed: enterprise console, not generic card grid.

- **Health Score / operational score:** if the mockup has it, implement it as a **deterministic** function of the existing ticket list. Document the formula in code comments. Do not display random or fake numbers. Example shape:

```ts
// TODO(backend): replace with GET /api/stats/health-score
// Deterministic UI-side score until backend endpoint exists.
// Formula: 100 - (urgent_open * 8) - (sla_breached * 5) - (overdue * 3), clamped [0,100].
export function deriveHealthScore(tickets: Ticket[]): { score: number; breakdown: ... } { ... }
```

- All other dashboard widgets (queue counts, SLA panels, recent activity, etc.) must source from existing API data. If a widget genuinely has no data source, render it with a clear "—" or empty state — do not fabricate values.

---

## 3. Ticket detail page — 1:1 from mockup

Preserve the layout exactly: ticket header, priority/status badges, timeline, internal notes, attachments, assignment panel, ticket details, SLA/response panel.

**Functional requirements that must keep working:**
- Status transitions (with existing permission checks)
- Assignment changes
- Messages / internal notes (including `internal: true` flag)
- Attachments — including hidden/internal attachment visibility rules
- Permission checks unchanged

---

## 4. Create ticket page — 1:1 from mockup

Preserve current create-ticket functionality: category, location, title, description, priority, attachments. Do not change the API payload shape unless the existing API requires a mapping — if you add a mapping, isolate it in `api/client.ts` with a comment explaining why.

---

## 5. Sidebar / AppShell — 1:1 from mockup

Use the enterprise console shell exactly. Keep nav consistent across Dashboard, New Ticket, Ticket Detail. Disabled / future links may stay visually present but **must not** route to broken pages — wire them to a 404 / coming-soon component or omit the `<Link>`.

---

## 6. Code-quality expectations

- Components readable; extract small presentational components where it helps maintainability.
- No giant untyped objects; type everything.
- Icons from `lucide-react` only.
- No new heavy UI library.
- `npm run build` must pass with strict TS.

---

## Deliverable

```bash
cd frontend
npm run build
```

Then report:
- Files changed
- Any `// TODO(backend): ...` comments added (with the endpoint they want)
- Any place where the mockup couldn't be matched 1:1 and why

---

## Mockup reference

Open `claude-design-reference.html` in a browser and use the demo nav (or `showPage('login' | 'dashboard' | 'create' | 'detail')` in the console) to step through each screen. The mockup's HTML/CSS is the visual source of truth — port classes / layout / spacing values directly into your component styles (Tailwind, CSS modules, or whatever the existing project uses).
