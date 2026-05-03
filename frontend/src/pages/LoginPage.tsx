import type { FormEvent } from "react";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { getApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

const DEMO_USERS = [
  { label: "Super admin", email: "admin@example.com", password: "Admin12345!" },
  { label: "Company admin", email: "companyadmin@example.com", password: "Test12345!" },
  { label: "Manager", email: "manager@example.com", password: "Test12345!" },
  { label: "Customer", email: "customer@example.com", password: "Test12345!" },
];

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
    <main className="auth-page">
      <section className="auth-card">
        <div>
          <p className="eyebrow">Cleaning Ticket System</p>
          <h1>Sign in</h1>
          <p className="muted">
            Use your operations console credentials to continue.
          </p>
        </div>

        <div className="demo-login-panel">
          <div>
            <p className="demo-title">Local demo users</p>
            <p className="muted small">Click one user, then sign in.</p>
          </div>
          <div className="demo-user-grid">
            {DEMO_USERS.map((user) => (
              <button
                type="button"
                className="demo-user-button"
                key={user.email}
                onClick={() => fillDemoUser(user.email, user.password)}
              >
                <span>{user.label}</span>
                <small>{user.email}</small>
              </button>
            ))}
          </div>
        </div>

        <form onSubmit={handleSubmit} className="form">
          <label>
            <span>Email</span>
            <input
              type="email"
              autoComplete="email"
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
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>

          {error && <div className="error">{error}</div>}

          <button disabled={submitting || !email || !password}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
