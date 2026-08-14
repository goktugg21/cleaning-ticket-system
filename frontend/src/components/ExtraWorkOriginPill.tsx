import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { Layers } from "lucide-react";
import { useTranslation } from "react-i18next";

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
  return (
    <Link
      to={`/extra-work/${ewId}`}
      className="work-type-pill work-type-pill-extra-work work-type-pill-link"
      title={t("chargeable_work.pill_title")}
      data-testid={testId}
      style={style}
      onClick={(event) => event.stopPropagation()}
    >
      <Layers size={12} strokeWidth={2.5} aria-hidden />
      {t("chargeable_work.pill")}
    </Link>
  );
}
