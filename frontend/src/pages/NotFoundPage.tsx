import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

/**
 * P-5 S4.1 — AN HONEST 404.
 *
 * The catch-all route used to `Navigate` to "/", so a mistyped or stale
 * address rendered the Dashboard silently — the reader could not tell
 * that the page they asked for does not exist. The `RouteErrorBoundary`
 * (P-4) covers a page that CRASHES; this covers a page that is not
 * there: it says so, in a sentence, and offers the way home.
 */
export function NotFoundPage() {
  const { t } = useTranslation("common");
  return (
    <div className="card" style={{ padding: 24, maxWidth: 560 }} data-testid="not-found-page">
      <h1 className="section-title" style={{ marginTop: 0 }}>
        {t("not_found.title")}
      </h1>
      <p className="muted" style={{ margin: "8px 0 16px" }}>
        {t("not_found.body")}
      </p>
      <Link to="/" className="btn btn-primary btn-sm" data-testid="not-found-home">
        {t("not_found.home")}
      </Link>
    </div>
  );
}
