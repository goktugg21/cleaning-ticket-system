import type { FormEvent } from "react";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { getApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

const SHOW_DEMO_USERS =
  import.meta.env.DEV || import.meta.env.VITE_SHOW_DEMO_USERS === "true";

const DEMO_USERS = SHOW_DEMO_USERS
  ? [
      { label: "Super admin", email: "admin@example.com", password: "Admin12345!" },
      { label: "Company admin", email: "companyadmin@example.com", password: "Test12345!" },
      { label: "Manager", email: "manager@example.com", password: "Test12345!" },
      { label: "Customer", email: "customer@example.com", password: "Test12345!" },
    ]
  : [];

export function LoginPage() {
  const navigate = useNavigate();
  const { me, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (me) return <Navigate to="/" replace />;

  function fillDemoUser(emailValue: string, passwordValue: string) {
    setEmail(emailValue);
    setPassword(passwordValue);
    setError("");
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="enterprise-login">
      <section className="login-visual">
        <div className="visual-grid"></div>
        <div className="visual-glass">
          <div className="visual-logo">FM</div>
          <p className="visual-kicker">Facility Manager</p>
          <h1>Operational excellence through precision ticketing.</h1>
          <p>
            Track cleaning requests, approvals, attachments, and service history from
            one secure operations console.
          </p>

          <div className="visual-proof-grid">
            <div>
              <strong>24/7</strong>
              <span>Service desk visibility</span>
            </div>
            <div>
              <strong>SLA</strong>
              <span>Approval-ready workflows</span>
            </div>
            <div>
              <strong>Audit</strong>
              <span>Every action recorded</span>
            </div>
          </div>
        </div>
      </section>

      <section className="login-panel">
        <div className="login-card enterprise-card">
          <div className="login-heading">
            <p className="enterprise-eyebrow">Secure access</p>
            <h2>Sign in</h2>
            <p>
              Enter your credentials to access the facility operations dashboard.
            </p>
          </div>

          {SHOW_DEMO_USERS && (
            <div className="demo-login-panel enterprise-demo-panel">
              <div>
                <p className="demo-title">Local demo users</p>
                <p className="muted small">Select a profile, then sign in.</p>
              </div>

              <div className="demo-user-grid">
                {DEMO_USERS.map((user) => (
                  <button
                    type="button"
                    className="demo-user-button enterprise-demo-user"
                    key={user.email}
                    onClick={() => fillDemoUser(user.email, user.password)}
                  >
                    <span>{user.label}</span>
                    <small>{user.email}</small>
                  </button>
                ))}
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit} className="form enterprise-form">
            <label>
              <span>Email address</span>
              <input
                type="email"
                autoComplete="email"
                placeholder="manager@facility.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>

            <label>
              <span>Password</span>
              <input
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>

            <label className="login-check">
              <input type="checkbox" />
              <span>Remember this device for 30 days</span>
            </label>

            {error && <div className="error">{error}</div>}

            <button className="login-submit" disabled={submitting || !email || !password}>
              {submitting ? "Signing in…" : "Secure login"}
              <span>→</span>
            </button>
          </form>

          <div className="login-trust-row">
            <span>Verified access</span>
            <span>Encrypted session</span>
          </div>
        </div>
      </section>
    </main>
  );
}
