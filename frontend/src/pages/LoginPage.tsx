import type { FormEvent } from "react";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Building2, Eye, EyeOff, LockKeyhole, Mail } from "lucide-react";
import { api, getApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import heroImage from "../assets/login_page_photo.png";

const SHOW_DEMO_USERS =
  import.meta.env.DEV || import.meta.env.VITE_SHOW_DEMO_USERS === "true";

interface DemoUser {
  id: string;
  email: string;
  password: string;
  initials: string;
  avatarVariant: "dark" | "mint";
  name: string;
  role: string;
  pillLabel: string;
  pillVariant: "primary" | "muted";
}

const DEMO_USERS: DemoUser[] = [
  {
    id: "manager",
    email: "john@example.com",
    password: "John12345",
    initials: "JD",
    avatarVariant: "dark",
    name: "John Doe",
    role: "Building Manager",
    pillLabel: "Manager Role",
    pillVariant: "primary",
  },
  {
    id: "customer",
    email: "anna@example.com",
    password: "Anna12345",
    initials: "AS",
    avatarVariant: "mint",
    name: "Anna Smith",
    role: "Customer User",
    pillLabel: "Customer Role",
    pillVariant: "muted",
  },
];

export function LoginPage() {
  const navigate = useNavigate();
  const { me, login } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [selectedDemo, setSelectedDemo] = useState<string | null>(null);
  const [resetBusy, setResetBusy] = useState(false);

  if (me) return <Navigate to="/" replace />;

  function applyDemoUser(user: DemoUser) {
    setEmail(user.email);
    setPassword(user.password);
    setSelectedDemo(user.id);
    setError("");
    setInfo("");
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setInfo("");
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

  async function handleForgotPassword() {
    setError("");
    setInfo("");

    if (!email.trim()) {
      setError("Enter your work email above first, then click Forgot password.");
      return;
    }

    setResetBusy(true);
    try {
      await api.post("/auth/password/reset/", { email: email.trim() });
      setInfo("If an account exists for that email, a reset link has been sent.");
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setResetBusy(false);
    }
  }

  return (
    <main className="login-root">
      <section className="login-visual" aria-hidden="false">
        <img src={heroImage} alt="" className="login-visual-img" />
        <div className="login-visual-overlay" />
        <div className="login-visual-tagline">
          <h1>
            Precision. Efficiency.
            <br />
            Excellence.
          </h1>
          <p>
            Empowering facility managers with the tools to maintain pristine
            environments seamlessly.
          </p>
        </div>
      </section>

      <section className="login-panel">
        <div className="login-content">
          <div className="login-brand-row">
            <div className="login-brand-row-icon">
              <Building2 size={20} strokeWidth={2} />
            </div>
            <div className="login-brand-row-name">CleanOps</div>
          </div>

          <div className="login-welcome">
            <h2 className="login-welcome-title">Welcome Back</h2>
            <p className="login-welcome-sub">Access your CleanOps console.</p>
          </div>

          {SHOW_DEMO_USERS && (
            <div className="qa-section">
              <div className="qa-label">Quick access for demo</div>
              <div className="qa-grid">
                {DEMO_USERS.map((user) => (
                  <button
                    type="button"
                    key={user.id}
                    className={`qa-card ${selectedDemo === user.id ? "selected" : ""}`}
                    onClick={() => applyDemoUser(user)}
                  >
                    <div className="qa-card-head">
                      <div className={`qa-avatar ${user.avatarVariant}`}>
                        {user.initials}
                      </div>
                      <div className="qa-id">
                        <div className="qa-name">{user.name}</div>
                        <div className="qa-title">{user.role}</div>
                      </div>
                    </div>
                    <span
                      className={`qa-role-pill ${user.pillVariant === "muted" ? "muted" : ""}`}
                    >
                      {user.pillLabel}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="login-divider">
            <span className="login-divider-label">Or continue with email</span>
          </div>

          <form className="login-form" onSubmit={handleSubmit} noValidate>
            <div className="login-field">
              <div className="login-field-row">
                <label className="login-field-label" htmlFor="login-email">
                  Work Email
                </label>
              </div>
              <div className="login-field-wrap">
                <Mail className="login-field-icon" size={18} strokeWidth={2} />
                <input
                  id="login-email"
                  className="login-field-input"
                  type="email"
                  placeholder="name@veridian.com"
                  autoComplete="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                />
              </div>
            </div>

            <div className="login-field">
              <div className="login-field-row">
                <label className="login-field-label" htmlFor="login-password">
                  Password
                </label>
                <button
                  type="button"
                  className="login-field-link"
                  onClick={handleForgotPassword}
                  disabled={resetBusy}
                >
                  {resetBusy ? "Sending…" : "Forgot password?"}
                </button>
              </div>
              <div className="login-field-wrap">
                <LockKeyhole
                  className="login-field-icon"
                  size={18}
                  strokeWidth={2}
                />
                <input
                  id="login-password"
                  className="login-field-input has-toggle"
                  type={showPassword ? "text" : "password"}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
                <button
                  type="button"
                  className="login-field-toggle"
                  aria-label={
                    showPassword ? "Hide password" : "Show password"
                  }
                  onClick={() => setShowPassword((value) => !value)}
                >
                  {showPassword ? (
                    <EyeOff size={16} strokeWidth={2} />
                  ) : (
                    <Eye size={16} strokeWidth={2} />
                  )}
                </button>
              </div>
            </div>

            <label className="login-check">
              {/* TODO(backend): wire this checkbox to a "remember device" flag once
                  the auth API exposes one. For now it stays visual-only and does
                  not affect the existing refresh-token flow. */}
              <input
                type="checkbox"
                checked={remember}
                onChange={(event) => setRemember(event.target.checked)}
              />
              <span>Remember my device for 30 days</span>
            </label>

            {error && (
              <div className="alert-error login-error" role="alert">
                {error}
              </div>
            )}

            {info && (
              <div className="alert-info login-error" role="status">
                {info}
              </div>
            )}

            <button
              type="submit"
              className="login-submit"
              disabled={submitting || !email || !password}
            >
              {submitting ? "Signing in…" : "Secure login"}
            </button>
          </form>
        </div>
      </section>
    </main>
  );
}
