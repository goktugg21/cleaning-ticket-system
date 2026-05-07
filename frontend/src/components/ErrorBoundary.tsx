import { Component, type ErrorInfo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

/**
 * Top-level error boundary. Catches render-time exceptions in the entire
 * subtree and shows a recovery UI instead of a blank white screen.
 *
 * In development we surface the stack trace inline so engineers can debug
 * fast. In production the stack is hidden — only a generic translated
 * message and a reload button. (Sentry integration in Sprint 1.3 will
 * ship the stack to the server so we still have it for triage.)
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error("ErrorBoundary caught:", error, errorInfo);
    this.setState({ errorInfo });
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return <ErrorFallback error={this.state.error} errorInfo={this.state.errorInfo} />;
  }
}

interface ErrorFallbackProps {
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

function ErrorFallback({ error, errorInfo }: ErrorFallbackProps) {
  const { t } = useTranslation("common");
  const isDev = import.meta.env.DEV;

  const handleReload = () => {
    window.location.assign("/");
  };

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "40px 24px",
        background: "var(--surface, #FAFAF7)",
      }}
    >
      <div className="card" style={{ maxWidth: 560, width: "100%", padding: 28 }}>
        <h1
          style={{
            fontSize: 19,
            fontWeight: 800,
            margin: 0,
            marginBottom: 20,
            letterSpacing: "-0.02em",
          }}
        >
          CleanOps
        </h1>

        <div className="alert-error" role="alert" style={{ flexDirection: "column", gap: 8 }}>
          <strong style={{ fontSize: 15 }}>{t("error_boundary.title")}</strong>
          <span style={{ fontWeight: 500, lineHeight: 1.5 }}>
            {t("error_boundary.description")}
          </span>
        </div>

        <div style={{ marginTop: 20, display: "flex", gap: 10 }}>
          <button type="button" className="btn btn-primary" onClick={handleReload}>
            {t("error_boundary.reload")}
          </button>
        </div>

        {isDev && error && (
          <details style={{ marginTop: 28, fontSize: 12, color: "var(--text-2, #555)" }}>
            <summary style={{ cursor: "pointer", marginBottom: 8 }}>
              Developer details (only visible in dev)
            </summary>
            <div
              style={{
                fontFamily: "monospace",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                background: "var(--surface-2, #F2F2EE)",
                padding: 12,
                borderRadius: 6,
                marginTop: 8,
              }}
            >
              <strong>
                {error.name}: {error.message}
              </strong>
              {error.stack && (
                <>
                  {"\n\n"}
                  {error.stack}
                </>
              )}
              {errorInfo?.componentStack && (
                <>
                  {"\n\n"}
                  <strong>Component stack:</strong>
                  {errorInfo.componentStack}
                </>
              )}
            </div>
          </details>
        )}
      </div>
    </main>
  );
}
