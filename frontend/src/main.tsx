import * as Sentry from "@sentry/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./index.css";
import "./i18n";

// Sentry init runs before createRoot.render so exceptions thrown during
// the first render pass (lazy chunk load failures, AuthProvider
// construction, axios interceptors firing on bootstrap) are still
// captured. The empty-DSN guard means the SDK is a complete no-op when
// Sentry is not configured — safe to merge with VITE_SENTRY_DSN unset
// and turn on later via .env.
if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT ?? "development",
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: parseFloat(
      import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE ?? "0",
    ),
    release: import.meta.env.VITE_SENTRY_RELEASE,
    sendDefaultPii: false,
  });
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>
);
