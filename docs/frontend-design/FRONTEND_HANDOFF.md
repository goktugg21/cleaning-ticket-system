# CleanOps — Frontend Implementation Brief

**Goal:** port the Claude/Stitch design into the existing React + TypeScript + Vite frontend without changing backend/security code.

**Target app:** `~/cleaning-ticket-system/frontend/`

**Design references in repo:**

| Purpose | Path |
|---|---|
| Non-login pages source of truth | `docs/frontend-design/claude-design-reference.html` |
| Final login visual target | `docs/frontend-design/login-page/login-page-target.png` |
| Stitch login HTML reference | `docs/frontend-design/login-page/code.html` |
| Stitch design notes / tokens | `docs/frontend-design/login-page/DESIGN.md` |
| Actual login background asset used by React | `frontend/src/assets/hero.png` |

The screenshot `docs/frontend-design/login-page/login-page-target.png` is the **final login target**. The Stitch HTML is only a reference for spacing/classes. Do **not** copy the external Google image URL from `code.html`; use the local `frontend/src/assets/hero.png` asset.

---

## Hard rules

1. **Do not redesign or reinterpret the Claude-designed pages.** Copy the references as closely as possible: colors, spacing, typography, card style, layout architecture, hierarchy. Responsive adjustments only.
2. **Login page exception:** login must follow `login-page-target.png`, not the old Claude login.
3. **Do not introduce Next.js, shadcn, Material UI, Chakra, Radix, or any new heavy UI library.** Use existing dependencies and `lucide-react` icons only.
4. **Do not touch Django / backend / migrations / security code.** Frontend only.
5. **Preserve existing P0 auth changes:**
   - refresh-token replacement flow
   - backend logout call
   - password reset flow
   - demo credentials gated behind `import.meta.env.DEV || import.meta.env.VITE_SHOW_DEMO_USERS === 'true'`
6. **Keep TypeScript strict.** `npm run build` must pass.
7. **Do not invent backend endpoints.** If a UI element needs data that does not exist, derive it from existing ticket list/detail data in a typed helper and add a `// TODO(backend): replace with /api/...` comment.
8. **All text must be real DOM text.** Do not bake headings/taglines into images. The Stitch screenshot text is blurry because it is a reference render; the implementation must render sharp text in React.

---

## File targets

| Page / shell | File |
|---|---|
| Login | `frontend/src/pages/LoginPage.tsx` |
| Dashboard | `frontend/src/pages/DashboardPage.tsx` |
| Create ticket | `frontend/src/pages/CreateTicketPage.tsx` |
| Ticket detail | `frontend/src/pages/TicketDetailPage.tsx` |
| App shell / sidebar | `frontend/src/layout/AppShell.tsx` |
| API client | `frontend/src/api/client.ts` only if absolutely necessary |
| API types | `frontend/src/api/types.ts` only if absolutely necessary |
| Login background asset | `frontend/src/assets/hero.png` |

---

## 1. Login page — final target

Use `docs/frontend-design/login-page/login-page-target.png` as the visual source of truth.

### Overall layout

- Full viewport, two equal split panels on desktop.
- Left: 50% width, full-height photo panel.
- Right: 50% width, white background, form content vertically centered.
- On small screens, hide or collapse the left image panel and make the form full-width.
- Page background: white. No green solid panel.

### Left side — photographic panel

Use `frontend/src/assets/hero.png` as the background image.

Required style:

- Full-bleed background image with `object-cover`.
- Soft blur/washed look is acceptable, but do not blur the actual tagline text.
- Dark bottom overlay so the tagline is readable.
- No brand logo on the left.
- No feature cards.
- No `24/7 Monitoring` / `SLA Enforcement` copy.

Bottom-left text, real DOM text:

```text
Precision. Efficiency.
Excellence.
```

Subtitle:

```text
Empowering facility managers with the tools to maintain pristine environments seamlessly.
```

Recommended positioning:

- Container: absolute bottom-left, about `left: 60px`, `bottom: 72px` on desktop.
- Title: bold, white, around 40–44px, tight line-height.
- Subtitle: 16–18px, light gray/white, max width around 520px.

Important: `code.html` currently has empty `<h1>` and `<p>` inside the left panel. Ignore that blank HTML and implement the target screenshot text above.

### Right side — premium form layout

Match the right side from `login-page-target.png`.

Content column:

- Width around 560px max.
- Left aligned, not centered as a card.
- Vertically centered in the right half.
- No outer card around the whole form.

Vertical order:

1. Heading block
2. Demo quick-access cards, gated
3. Divider
4. Work email field
5. Password field with forgot-password link
6. Remember checkbox
7. Primary button

Heading:

- `Welcome Back`
- `Access your CleanOps console.`
- Left-aligned.
- Strong black/near-black title, muted subtitle.

### Demo quick-access cards — gating required

Render the whole `Quick access for demo` block only when:

```ts
const SHOW_DEMO =
  import.meta.env.DEV ||
  import.meta.env.VITE_SHOW_DEMO_USERS === 'true';
```

If `SHOW_DEMO` is false:

- Do not render the label.
- Do not render the cards.
- Do not leave empty vertical space.
- Do not leave hidden DOM nodes with demo credentials.

Card layout:

- Two-column grid.
- Gap around 20px.
- Each card around 112px tall.
- Rounded 8–10px.
- Light border.
- Card 1 selected style by default is acceptable if it matches the screenshot, but clicking cards must update selected state.

Card 1:

- Avatar: `JD`, dark green circle.
- Name: `John Doe`
- Role: `Facility Mgr`
- Pill: green/teal dot + `Admin Role`
- Click action: fill `manager@example.com` and `Test12345!`

Card 2:

- Avatar: `AS`, mint/teal circle.
- Name: `Anna Smith`
- Role: `Technician`
- Pill: `Standard Role`
- Click action: fill `customer@example.com` and `Test12345!`

Clicking a card must prefill email/password and visually mark the card as selected. It must **not** auto-submit.

### Divider

- Text: `OR CONTINUE WITH EMAIL`
- Uppercase, small, muted gray, semibold.
- Hairline borders left and right.
- Match screenshot spacing.

### Form fields

Email field:

- Label: `Work Email`
- Placeholder: `name@veridian.com`
- Mail icon on the left.
- Height around 56px.
- Rounded 8–10px.
- Light gray input background.

Password field:

- Label row: `Password` left, `Forgot password?` right.
- `Forgot password?` must open/use the existing password reset flow. Do not remove reset functionality.
- Lock icon on the left.
- Eye / eye-off toggle on the right.
- Placeholder dots.

Remember checkbox:

- Text: `Remember my device for 30 days`
- Keep existing behavior if implemented; otherwise visual only is acceptable, but do not break login.

Submit button:

- Text: `Secure login`
- Full width.
- Dark green.
- Around 56px high.
- Rounded 8px.
- Do not rename to plain `Sign In`.

### Login page implementation notes

- Use `lucide-react` icons: `Building2`, `Mail`, `LockKeyhole`, `Eye`, `EyeOff` if needed.
- Use the existing auth context/client. Do not replace the auth flow.
- The final screenshot has blurry text in the left image area because Stitch rendered a mock image. In React, the photo should be the background only; overlay/title/subtitle must be crisp DOM text.

---

## 2. Dashboard page — 1:1 from Claude mockup

Use `docs/frontend-design/claude-design-reference.html` as the source of truth.

- Preserve the enterprise console composition.
- Do not turn it into a generic card grid.
- Copy colors, spacing, typography, card treatment, hierarchy, and layout from the mockup.

### Health / operational score

If the mockup includes a Health Score / Operational Score, implement it deterministically from existing ticket data. Do not show a random/fake number.

Example implementation shape:

```ts
// TODO(backend): replace with GET /api/stats/health-score
// Deterministic UI-side score until backend endpoint exists.
// Formula: 100 - (openUrgent * 8) - (waitingApproval * 3) - (openHigh * 4), clamped [0, 100].
function deriveHealthScore(tickets: Ticket[]): { score: number; breakdown: string[] } {
  // typed implementation here
}
```

All other dashboard widgets must source from existing API data. If there is no real data source, render `—` or an empty state. Do not fabricate operational values.

---

## 3. Ticket detail page — 1:1 from Claude mockup

Use `docs/frontend-design/claude-design-reference.html` as the visual source of truth.

Preserve the layout exactly:

- ticket header
- priority/status badges
- timeline / activity
- internal notes
- attachments
- assignment panel
- ticket details panel
- SLA/response panel if present in the mockup

Functional requirements that must continue working:

- Status transitions with existing permission checks.
- Assignment changes.
- Messages and internal notes.
- Attachments, including hidden/internal attachment visibility rules.
- Password reset/login/logout/auth flow untouched.
- Permission checks unchanged.

---

## 4. Create ticket page — 1:1 from Claude mockup

Use `docs/frontend-design/claude-design-reference.html` as the visual source of truth.

Preserve existing create-ticket functionality:

- category/type
- building/customer/location
- title
- description
- priority
- attachments

Do not change the API payload shape unless the existing API requires a mapping. If a mapping is needed, isolate it in `api/client.ts` with a clear comment.

---

## 5. Sidebar / AppShell — 1:1 from Claude mockup

Use the enterprise console shell exactly.

- Keep nav consistent across Dashboard, New Ticket, and Ticket Detail.
- Disabled/future links may stay visually present, but must not route to broken pages.
- Either omit links for unavailable pages or route to a safe coming-soon/disabled state.

---

## 6. Stitch downloaded files review

`docs/frontend-design/login-page/code.html`:

- Use it only as a visual/layout reference.
- It uses Tailwind CDN and Google-hosted assets; do not copy those dependencies into the React app.
- It has an external `googleusercontent.com` image URL; do not use it in production.
- Its left-panel h1/p are blank; use the target screenshot text from this brief.

`docs/frontend-design/login-page/DESIGN.md`:

- Useful for design intent/tokens only.
- Not a source of truth for app architecture or auth behavior.

`docs/frontend-design/login-page/login-page-target.png`:

- Final login visual target.
- The text blur is not a problem; implementation text must be rendered as crisp React DOM text.

`frontend/src/assets/login_page_photo.png`:

- Actual background asset for the login page.
- Import this file directly from `LoginPage.tsx`.

---

## 7. Code-quality expectations

- Keep components readable.
- Extract small presentational components where it helps maintainability.
- Type everything.
- Use `lucide-react` only for icons.
- No new heavy UI library.
- No backend changes.
- `npm run build` must pass.

---

## Deliverable

Run:

```bash
cd ~/cleaning-ticket-system/frontend
npm run build
```

Then report:

- Files changed.
- Any `// TODO(backend): ...` comments added and what endpoint/data they request.
- Any place where the mockup could not be matched 1:1 and why.
