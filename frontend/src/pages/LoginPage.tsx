import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { Building2, Eye, EyeOff, LockKeyhole, Mail } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import heroImage from "../assets/login_page_photo.png";

// Sprint 16: demo helper visibility is gated on VITE_DEMO_MODE. The
// previous gate (DEV || VITE_SHOW_DEMO_USERS) accidentally surfaced
// demo cards in any frontend built with `npm run dev`. The new flag
// is opt-in and never set in the production .env.example, so a
// production build cannot leak demo credentials by accident even if
// `npm run build` was run from a developer machine that has VITE_*
// env vars exported in the shell.
const SHOW_DEMO_USERS = import.meta.env.VITE_DEMO_MODE === "true";

const DEMO_PASSWORD = "Demo12345!";

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
  roleKey:
    | "demo_role_super_admin"
    | "demo_role_company_admin"
    | "demo_role_manager"
    | "demo_role_customer";
  pillKey:
    | "demo_pill_super_admin"
    | "demo_pill_company_admin"
    | "demo_pill_manager"
    | "demo_pill_customer";
  pillVariant: "primary" | "muted";
  // Optional one-line scope hint shown under the role name (e.g.
  // "B1 / B2 / B3" for a multi-building manager). Helps the operator
  // pick the right demo account without consulting the seed.
  scopeHint?: string;
}

// Mirrors backend/accounts/management/commands/seed_demo_data.py.
// Sprint 21: two demo companies (Osius Demo + Bright Facilities) so
// the operator can demonstrate cross-company isolation in one click.
const COMPANY_A_LABEL = "Osius Demo (Amsterdam)";
const COMPANY_B_LABEL = "Bright Facilities (Rotterdam)";

const DEMO_USERS_COMPANY_A: DemoUser[] = [
  {
    id: "company-admin",
    email: "admin@cleanops.demo",
    password: DEMO_PASSWORD,
    initials: "CA",
    avatarVariant: "dark",
    name: "Company Admin",
    roleKey: "demo_role_company_admin",
    pillKey: "demo_pill_company_admin",
    pillVariant: "primary",
  },
  {
    id: "manager-all",
    email: "gokhan@cleanops.demo",
    password: DEMO_PASSWORD,
    initials: "GK",
    avatarVariant: "dark",
    name: "Gokhan Koçak",
    roleKey: "demo_role_manager",
    pillKey: "demo_pill_manager",
    pillVariant: "primary",
    scopeHint: "B1 / B2 / B3",
  },
  {
    id: "manager-b1",
    email: "murat@cleanops.demo",
    password: DEMO_PASSWORD,
    initials: "MU",
    avatarVariant: "dark",
    name: "Murat Uğurlu",
    roleKey: "demo_role_manager",
    pillKey: "demo_pill_manager",
    pillVariant: "primary",
    scopeHint: "B1 only",
  },
  {
    id: "customer-all",
    email: "tom@cleanops.demo",
    password: DEMO_PASSWORD,
    initials: "TV",
    avatarVariant: "mint",
    name: "Tom Verbeek",
    roleKey: "demo_role_customer",
    pillKey: "demo_pill_customer",
    pillVariant: "muted",
    scopeHint: "B1 / B2 / B3",
  },
  {
    id: "customer-b1-b2",
    email: "iris@cleanops.demo",
    password: DEMO_PASSWORD,
    initials: "IR",
    avatarVariant: "mint",
    name: "Iris",
    roleKey: "demo_role_customer",
    pillKey: "demo_pill_customer",
    pillVariant: "muted",
    scopeHint: "B1 / B2",
  },
  {
    id: "customer-b3",
    email: "amanda@cleanops.demo",
    password: DEMO_PASSWORD,
    initials: "AM",
    avatarVariant: "mint",
    name: "Amanda",
    roleKey: "demo_role_customer",
    pillKey: "demo_pill_customer",
    pillVariant: "muted",
    scopeHint: "B3 only",
  },
];

const DEMO_USERS_COMPANY_B: DemoUser[] = [
  {
    id: "company-admin-b",
    email: "admin-b@cleanops.demo",
    password: DEMO_PASSWORD,
    initials: "SD",
    avatarVariant: "dark",
    name: "Sophie van Dijk",
    roleKey: "demo_role_company_admin",
    pillKey: "demo_pill_company_admin",
    pillVariant: "primary",
  },
  {
    id: "manager-b",
    email: "manager-b@cleanops.demo",
    password: DEMO_PASSWORD,
    initials: "BJ",
    avatarVariant: "dark",
    name: "Bram de Jong",
    roleKey: "demo_role_manager",
    pillKey: "demo_pill_manager",
    pillVariant: "primary",
    scopeHint: "R1 / R2",
  },
  {
    id: "customer-b-co",
    email: "customer-b@cleanops.demo",
    password: DEMO_PASSWORD,
    initials: "LV",
    avatarVariant: "mint",
    name: "Lotte Visser",
    roleKey: "demo_role_customer",
    pillKey: "demo_pill_customer",
    pillVariant: "muted",
    scopeHint: "R1 / R2",
  },
];

const SUPER_ADMIN_DEMO_USER: DemoUser = {
  id: "super",
  email: "super@cleanops.demo",
  password: DEMO_PASSWORD,
  initials: "SA",
  avatarVariant: "dark",
  name: "Super Admin",
  roleKey: "demo_role_super_admin",
  pillKey: "demo_pill_super_admin",
  pillVariant: "primary",
};

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
            <div className="qa-section" data-testid="demo-cards">
              <div className="qa-label">{t("demo_label")}</div>
              <div className="qa-hint">
                {t("demo_credentials_hint", { password: DEMO_PASSWORD })}
              </div>
              <div className="qa-grid">
                {/* Super admin spans both companies — shown first. */}
                <button
                  type="button"
                  key={SUPER_ADMIN_DEMO_USER.id}
                  data-testid={`demo-card-${SUPER_ADMIN_DEMO_USER.id}`}
                  data-demo-company="both"
                  className={`qa-card ${selectedDemo === SUPER_ADMIN_DEMO_USER.id ? "selected" : ""}`}
                  onClick={() => applyDemoUser(SUPER_ADMIN_DEMO_USER)}
                >
                  <div className="qa-card-head">
                    <div className={`qa-avatar ${SUPER_ADMIN_DEMO_USER.avatarVariant}`}>
                      {SUPER_ADMIN_DEMO_USER.initials}
                    </div>
                    <div className="qa-id">
                      <div className="qa-name">{SUPER_ADMIN_DEMO_USER.name}</div>
                      <div className="qa-title">{t(SUPER_ADMIN_DEMO_USER.roleKey)}</div>
                    </div>
                  </div>
                  <span className="qa-role-pill">{t(SUPER_ADMIN_DEMO_USER.pillKey)}</span>
                </button>
              </div>

              <div
                className="qa-company-label"
                data-testid="demo-company-a-label"
              >
                {COMPANY_A_LABEL}
              </div>
              <div className="qa-grid" data-testid="demo-company-a-grid">
                {DEMO_USERS_COMPANY_A.map((user) => (
                  <button
                    type="button"
                    key={user.id}
                    data-testid={`demo-card-${user.id}`}
                    data-demo-company="A"
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
                        {user.scopeHint && (
                          <div className="qa-scope">{user.scopeHint}</div>
                        )}
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

              <div
                className="qa-company-label"
                data-testid="demo-company-b-label"
              >
                {COMPANY_B_LABEL}
              </div>
              <div className="qa-grid" data-testid="demo-company-b-grid">
                {DEMO_USERS_COMPANY_B.map((user) => (
                  <button
                    type="button"
                    key={user.id}
                    data-testid={`demo-card-${user.id}`}
                    data-demo-company="B"
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
                        {user.scopeHint && (
                          <div className="qa-scope">{user.scopeHint}</div>
                        )}
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
