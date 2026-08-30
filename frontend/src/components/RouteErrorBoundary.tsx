/**
 * P-4 (Part F) — NO PAGE MAY EVER RENDER SILENT WHITE.
 *
 * The root `ErrorBoundary` (main.tsx) catches a render crash for the
 * whole app and replaces everything — shell included — with a reload
 * screen. Inside the shell a single page that throws should not take
 * the sidebar with it, and a page that has nothing to show must SAY so.
 * This boundary wraps the routed page only, resets on every route
 * change (keyed by pathname in `AppShell`), and renders a plain card:
 * what happened, and the two ways out. The error still reaches the
 * console and Sentry through the same hook the root boundary uses.
 */
import * as Sentry from "@sentry/react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export class RouteErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): Partial<State> {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error("RouteErrorBoundary caught:", error, errorInfo);
    Sentry.captureException(error, {
      contexts: { react: { componentStack: errorInfo.componentStack ?? "" } },
    });
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return <RouteErrorCard />;
  }
}

function RouteErrorCard() {
  const { t } = useTranslation("common");
  return (
    <section className="card" role="alert" data-testid="route-error-card" style={{ padding: 22, maxWidth: 560 }}>
      <div className="section-head-title">{t("route_error.title")}</div>
      <p className="muted" style={{ marginTop: 6 }}>
        {t("route_error.body")}
      </p>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => window.location.reload()}>
          {t("route_error.reload")}
        </button>
        <Link to="/" className="btn btn-secondary btn-sm">
          {t("route_error.home")}
        </Link>
      </div>
    </section>
  );
}
