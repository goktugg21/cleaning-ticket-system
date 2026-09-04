# The i18n audit — what its two numbers mean

`frontend/scripts/i18n_audit.mjs` (`npm run i18n:audit`) walks every
literal `t()` key in `frontend/src/` and resolves it against BOTH
bundles. It prints two numbers, and this file is what they mean, so a
change in either is a signal rather than noise.

**Baseline, measured on `feat/p18-after-the-merge` (2026-09-04):**

```
i18n audit: 5286 t() key references checked in nl + en
NS-FALLBACK (absent from first namespace, needs nsMode:"fallback"): 2
MISSING (absent from every bound namespace): 0
```

`--list-fallback` prints the offending keys with file and line.

## MISSING — must stay 0

The key resolves in no bound namespace, in one or both languages, so it
renders **as its own name** on screen. This is the defect the script was
written for: `archive.show`, `archive.show_working`, `period.label` and
`change.moved_to` each reached the owner's screen as raw keys. A
non-zero MISSING fails the run (exit 1).

## NS-FALLBACK — 2, and exactly which

The key is absent from the caller's FIRST bound namespace but present in
a later one, so it renders only because `i18n/index.ts` sets
`nsMode: "fallback"`. Without that line react-i18next binds
`useTranslation(["page", "common"])` to `page` ALONE and every such key
breaks at once. These are therefore the keys that measure the blast
radius of removing it.

The 2 are ONE key counted once per language:

| key | call site | first ns | lives in | verdict |
|---|---|---|---|---|
| `hours_admin.hour_unit` | [TicketDetailPage.tsx:6051](../../frontend/src/pages/TicketDetailPage.tsx#L6051) | `ticket_detail` | `common` | **by design** — a shared unit label read from the shared bundle, which the same call binds second |

**By design, not a misfiling.** `common` is the shared bundle and is
bound second in that component's `useTranslation(["ticket_detail",
"common", "staff_slots"])`. Moving the key into `ticket_detail` would
duplicate it for every other page that needs the same word.

## Why the number used to be 58 (P-18 B2)

Until P-18 this line read **58**, and it had never been investigated.
Investigating it found **no misfiled key at all** — 56 of the 58 were
the script misreading its own input.

A file may bind more than one `t`:

```ts
const { t, i18n } = useTranslation(["ticket_detail", "common", "staff_slots"]);
const { t: tCred } = useTranslation("staff_credentials");
```

The old `TCALL` regex matched any `t…(` — `tCred(` included — but
attributed **every** call in the file to `binds[0][0]`, the FIRST
`useTranslation`. So 28 `tCred("detail.yes")`-style calls in
`TicketDetailPage.tsx` and `admin/UserDetailPage.tsx`, all bound
directly to `staff_credentials` and all resolving in their own primary
namespace, were reported as fallback-dependent. They are not: they would
keep working if `nsMode: "fallback"` were deleted tomorrow.

The fix tracks the alias. `BIND` now captures the destructure as well as
the namespace argument, `aliasBindings()` maps each alias to the
namespace lists it was bound to, and each call is attributed to its own
callee. An alias bound in several places with different namespaces is
checked against the union and never reported as a fallback, because the
script cannot know which binding is in scope at that line.

`checked` stayed at **5286** across the change, which is the evidence
that no call site was dropped or double-counted — only re-attributed.

## When either number moves

- **MISSING > 0** — a real untranslated key. Fix before merge; the run
  already fails.
- **NS-FALLBACK grows** — a new key is being read from a namespace that
  is not its caller's first. Usually fine (a shared word from `common`),
  but say so in the sprint report and add the row to the table above.
- **NS-FALLBACK shrinks** — a key moved into its caller's own bundle.
  Also fine; remove the row.
- **`checked` moves a lot without a matching change in `t()` call
  count** — suspect the regexes, not the bundles.
