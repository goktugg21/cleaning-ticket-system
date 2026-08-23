import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { Layers } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/AuthContext";
import { canAccessExtraWork } from "../auth/permissions";

/**
 * SoT (Osius_Source_of_Truth_FINAL_2026-05-30) §1.4 + §7.1 — an Extra
 * Work-origin ticket "must not disappear into the normal ticket list"
 * and the dashboard "must make Extra Work origin impossible to miss".
 *
 * Sprint 180 §3 — lifted out of `DashboardPage.tsx`, where it had been
 * a local function component since the dashboard rework. The dashboard
 * ticket table and its phone-width card mirror already rendered it;
 * every OTHER list of tickets did not, so the same ticket announced its
 * origin on one screen and hid it on the next. It is a shared component
 * now, used by the ticket list, the manager agenda and the customer's
 * meldingen list, so the pill cannot drift between them.
 *
 * The translations stay in the `dashboard` namespace — moving the keys
 * would break the nl/en lockstep pair for no gain, and i18next
 * namespaces are global, so a component declaring its own namespace
 * resolves them wherever it is mounted.
 *
 * `stopPropagation` keeps the click from also triggering the enclosing
 * row/card's own navigation to the ticket: the pill goes to the PARENT
 * Extra Work, which is the whole point of it being a link.
 *
 * W15 §2 — FOR STAFF IT IS A LABEL, NOT A LINK, AND IT ALWAYS SHOULD
 * HAVE BEEN.
 *
 * `scope_extra_work_for` returns `.none()` for STAFF (the P0
 * staff-privacy fix), so this `<Link>` has been a door to a hard 404
 * for that role on every screen it appears on. Measured on the dev API:
 * `GET /api/extra-work/6/` as STAFF answers
 * `404 {"detail":"No ExtraWorkRequest matches the given query."}`,
 * while `GET /api/tickets/?is_extra_work=true` serves them all 5 rows
 * with `extra_work_origin` populated — so the pill rendered, and broke,
 * every time.
 *
 * The ORIGIN FACT stays visible: SoT §1.4 / §7.1 require that an
 * extra-work ticket "must not disappear into the normal ticket list",
 * and that is true for a worker as much as for a manager. What goes is
 * the navigation, because rule 6 is that a role which cannot use
 * something does not get offered it. Same pill, same words, same
 * colour; a `<span>` instead of an `<a>`, without the `-link` modifier
 * that supplies the pointer cursor and the hover state.
 *
 * The predicate is read HERE rather than passed in by each of the four
 * consumers (ticket list, dashboard card mirror, manager agenda,
 * customer meldingen list). One owner: a fifth consumer cannot forget
 * it, and the four existing ones cannot drift apart.
 */
export function ExtraWorkOriginPill({
  ewId,
  testId,
  style,
}: {
  ewId: number;
  testId: string;
  style?: CSSProperties;
}) {
  // Sprint 181 §5 — the pill says the NAME, from `common`, which is the
  // same string the nav entry, the sub-page title and the Extra Work
  // list's second tab render. It used to read `ops_type_extra_work` out
  // of the `dashboard` namespace: a third spelling of one concept
  // ("extra work origin" / "spawned from extra work" / "Extra work"),
  // which is the drift §5 exists to end.
  const { t } = useTranslation("common");
  const { me } = useAuth();

  const label = (
    <>
      <Layers size={12} strokeWidth={2.5} aria-hidden />
      {t("chargeable_work.pill")}
    </>
  );

  if (!canAccessExtraWork(me?.role)) {
    return (
      <span
        className="work-type-pill work-type-pill-extra-work"
        data-testid={testId}
        style={style}
      >
        {label}
      </span>
    );
  }

  return (
    <Link
      to={`/extra-work/${ewId}`}
      className="work-type-pill work-type-pill-extra-work work-type-pill-link"
      title={t("chargeable_work.pill_title")}
      data-testid={testId}
      style={style}
      onClick={(event) => event.stopPropagation()}
    >
      {label}
    </Link>
  );
}
