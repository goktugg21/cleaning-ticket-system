import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { Building2, Eye, EyeOff, LockKeyhole, Mail } from "lucide-react";
import { useTranslation } from "react-i18next";
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
  // role and pillLabel resolve through i18n keys at render time so the demo
  // cards switch language with the rest of the page. The DEMO_USERS fixture
  // only stores the key; the t() call decides the displayed string.
  roleKey: "demo_role_manager" | "demo_role_customer";
  pillKey: "demo_pill_manager" | "demo_pill_customer";
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
    roleKey: "demo_role_manager",
    pillKey: "demo_pill_manager",
    pillVariant: "primary",
  },
  {
    id: "customer",
    email: "anna@example.com",
    password: "Anna12345",
    initials: "AS",
    avatarVariant: "mint",
    name: "Anna Smith",
    roleKey: "demo_role_customer",
    pillKey: "demo_pill_customer",
    pillVariant: "muted",
  },
];

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { me, login } = useAuth();
  const { t } = useTranslation("login");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [selectedDemo, setSelectedDemo] = useState<string | null>(null);
  const [resetBusy, setResetBusy] = useState(false);

  useEffect(() => {
    if (searchParams.get("reset") === "ok") {
      setInfo(t("info_password_reset"));
      const next = new URLSearchParams(searchParams);
      next.delete("reset");
      setSearchParams(next, { replace: true });
    } else if (searchParams.get("invited") === "ok") {
      setInfo(t("info_invited"));
      const next = new URLSearchParams(searchParams);
      next.delete("invited");
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams, t]);

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
      // API errors are passed through verbatim; per-language API errors land
      // in a later i18n batch via a DRF exception handler.
      setError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleForgotPassword() {
    setError("");
    setInfo("");

    if (!email.trim()) {
      setError(t("error_email_required"));
      return;
    }

    setResetBusy(true);
    try {
      await api.post("/auth/password/reset/", { email: email.trim() });
      setInfo(t("info_reset_sent"));
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
            {t("tagline_line1")}
            <br />
            {t("tagline_line2")}
          </h1>
          <p>{t("tagline_body")}</p>
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
            <h2 className="login-welcome-title">{t("welcome_title")}</h2>
            <p className="login-welcome-sub">{t("welcome_sub")}</p>
          </div>

          {SHOW_DEMO_USERS && (
            <div className="qa-section">
              <div className="qa-label">{t("demo_label")}</div>
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
                        <div className="qa-title">{t(user.roleKey)}</div>
                      </div>
                    </div>
                    <span
                      className={`qa-role-pill ${user.pillVariant === "muted" ? "muted" : ""}`}
                    >
                      {t(user.pillKey)}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="login-divider">
            <span className="login-divider-label">{t("divider")}</span>
          </div>

          <form className="login-form" onSubmit={handleSubmit} noValidate>
            <div className="login-field">
              <div className="login-field-row">
                <label className="login-field-label" htmlFor="login-email">
                  {t("email_label")}
                </label>
              </div>
              <div className="login-field-wrap">
                <Mail className="login-field-icon" size={18} strokeWidth={2} />
                <input
                  id="login-email"
                  className="login-field-input"
                  type="email"
                  placeholder={t("email_placeholder")}
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
                  {t("password_label")}
                </label>
                <button
                  type="button"
                  className="login-field-link"
                  onClick={handleForgotPassword}
                  disabled={resetBusy}
                >
                  {resetBusy ? t("sending") : t("forgot_password")}
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
                    showPassword ? t("hide_password") : t("show_password")
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
              <span>{t("remember_me")}</span>
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
              {submitting ? t("signing_in") : t("submit")}
            </button>
          </form>
        </div>
      </section>
    </main>
  );
}
