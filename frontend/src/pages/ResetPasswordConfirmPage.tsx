import type { FormEvent } from "react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Building2, Eye, EyeOff, LockKeyhole } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";

type FieldErrors = {
  new_password?: string;
  token?: string;
  uid?: string;
  detail?: string;
};

function extractFieldErrors(error: unknown): FieldErrors {
  const fallback: FieldErrors = {};
  if (typeof error !== "object" || error === null) {
    return fallback;
  }

  const maybeAxios = error as {
    response?: { data?: unknown };
    isAxiosError?: boolean;
  };
  const data = maybeAxios.response?.data;
  if (!data || typeof data !== "object") {
    return fallback;
  }

  const result: FieldErrors = {};
  for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
    if (key !== "new_password" && key !== "token" && key !== "uid" && key !== "detail") {
      continue;
    }
    if (Array.isArray(value)) {
      result[key as keyof FieldErrors] = String(value[0] ?? "");
    } else if (value !== null && value !== undefined) {
      result[key as keyof FieldErrors] = String(value);
    }
  }
  return result;
}

export function ResetPasswordConfirmPage() {
  const { t } = useTranslation("login");
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const uid = params.get("uid") ?? "";
  const token = params.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [generalError, setGeneralError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});

  const missingTokenInfo = useMemo(
    () => (!uid || !token ? t("reset_link_incomplete") : ""),
    [uid, token, t],
  );

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneralError("");
    setFieldErrors({});

    if (password.length === 0) {
      setFieldErrors({ new_password: t("reset_error_choose_password") });
      return;
    }
    if (password !== confirmPassword) {
      setFieldErrors({ new_password: t("reset_error_passwords_dont_match") });
      return;
    }

    setSubmitting(true);
    try {
      await api.post("/auth/password/reset/confirm/", {
        uid,
        token,
        new_password: password,
      });
      navigate("/login?reset=ok", { replace: true });
    } catch (err) {
      const fields = extractFieldErrors(err);
      if (Object.keys(fields).length > 0) {
        setFieldErrors(fields);
      } else {
        setGeneralError(getApiError(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main
      className="login-panel"
      style={{ minHeight: "100vh", padding: "40px 24px" }}
    >
      <div className="login-content">
        <div className="login-brand-row">
          <div className="login-brand-row-icon">
            <Building2 size={20} strokeWidth={2} />
          </div>
          <div className="login-brand-row-name">CleanOps</div>
        </div>

        <div className="login-welcome">
          <h2 className="login-welcome-title">{t("reset_title")}</h2>
          <p className="login-welcome-sub">{t("reset_subtitle")}</p>
        </div>

        {missingTokenInfo && (
          <div className="alert-error login-error" role="alert">
            {missingTokenInfo}
          </div>
        )}

        {generalError && (
          <div className="alert-error login-error" role="alert">
            {generalError}
          </div>
        )}

        {fieldErrors.token && (
          <div className="alert-error login-error" role="alert">
            {fieldErrors.token}
          </div>
        )}

        {fieldErrors.detail && (
          <div className="alert-error login-error" role="alert">
            {fieldErrors.detail}
          </div>
        )}

        <form className="login-form" onSubmit={handleSubmit} noValidate>
          <div className="login-field">
            <div className="login-field-row">
              <label className="login-field-label" htmlFor="reset-new-password">
                {t("reset_field_new_password")}
              </label>
            </div>
            <div className="login-field-wrap">
              <LockKeyhole
                className="login-field-icon"
                size={18}
                strokeWidth={2}
              />
              <input
                id="reset-new-password"
                className="login-field-input has-toggle"
                type={showPassword ? "text" : "password"}
                placeholder="••••••••"
                autoComplete="new-password"
                aria-describedby="reset-new-password-hint"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              <button
                type="button"
                className="login-field-toggle"
                aria-label={showPassword ? t("hide_password") : t("show_password")}
                onClick={() => setShowPassword((value) => !value)}
              >
                {showPassword ? (
                  <EyeOff size={16} strokeWidth={2} />
                ) : (
                  <Eye size={16} strokeWidth={2} />
                )}
              </button>
            </div>
            <div
              id="reset-new-password-hint"
              style={{
                marginTop: 6,
                fontSize: 12,
                color: "var(--text-muted)",
                lineHeight: 1.4,
              }}
            >
              {t("reset_password_requirements_hint")}
            </div>
            {fieldErrors.new_password && (
              <div className="alert-error login-error" role="alert">
                {fieldErrors.new_password}
              </div>
            )}
          </div>

          <div className="login-field">
            <div className="login-field-row">
              <label className="login-field-label" htmlFor="reset-confirm-password">
                {t("reset_field_confirm_password")}
              </label>
            </div>
            <div className="login-field-wrap">
              <LockKeyhole
                className="login-field-icon"
                size={18}
                strokeWidth={2}
              />
              <input
                id="reset-confirm-password"
                className="login-field-input"
                type={showPassword ? "text" : "password"}
                placeholder="••••••••"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                required
              />
            </div>
          </div>

          <button
            type="submit"
            className="login-submit"
            disabled={submitting || !uid || !token || !password || !confirmPassword}
          >
            {submitting ? t("reset_saving") : t("reset_submit")}
          </button>
        </form>

        <div style={{ marginTop: 24, fontSize: 13 }}>
          <Link className="login-field-link" to="/login">
            {t("reset_back_to_signin")}
          </Link>
        </div>
      </div>
    </main>
  );
}
