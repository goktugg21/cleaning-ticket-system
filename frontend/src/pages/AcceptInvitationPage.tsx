import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Building2, Eye, EyeOff, LockKeyhole } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";
import type { InvitationPreview, Role } from "../api/types";

const ROLE_KEYS: Record<Role, string> = {
  SUPER_ADMIN: "common:roles.super_admin",
  COMPANY_ADMIN: "common:roles.company_admin",
  BUILDING_MANAGER: "common:roles.building_manager",
  CUSTOMER_USER: "common:roles.customer_user",
};

type FieldErrors = {
  new_password?: string;
  token?: string;
  email?: string;
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
    if (key !== "new_password" && key !== "token" && key !== "email" && key !== "detail") {
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

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; preview: InvitationPreview }
  | { kind: "gone"; status?: string }
  | { kind: "missing-token" }
  | { kind: "not-found" }
  | { kind: "error"; message: string };

export function AcceptInvitationPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { t } = useTranslation("common");

  const [loadState, setLoadState] = useState<LoadState>({ kind: "loading" });
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [generalError, setGeneralError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});

  useEffect(() => {
    if (!token) {
      setLoadState({ kind: "missing-token" });
      return;
    }
    let cancelled = false;
    api
      .get<InvitationPreview>("/auth/invitations/preview/", {
        params: { token },
      })
      .then((response) => {
        if (!cancelled) {
          setLoadState({ kind: "ready", preview: response.data });
        }
      })
      .catch((err) => {
        if (cancelled) return;
        const status = (err?.response?.status as number | undefined) ?? 0;
        if (status === 410) {
          setLoadState({
            kind: "gone",
            status: (err?.response?.data?.status as string | undefined) ?? "",
          });
        } else if (status === 404) {
          setLoadState({ kind: "not-found" });
        } else {
          setLoadState({ kind: "error", message: getApiError(err) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const inviterName = useMemo(() => {
    if (loadState.kind !== "ready") return "";
    const p = loadState.preview;
    return p.inviter_full_name?.trim() || p.inviter_email;
  }, [loadState]);

  const scopeLine = useMemo(() => {
    if (loadState.kind !== "ready") return "";
    const preview = loadState.preview;
    const parts: string[] = [];
    if (preview.company_names.length > 0) {
      parts.push(`${t("accept_invitation.scope_company")}: ${preview.company_names.join(", ")}`);
    }
    if (preview.building_names.length > 0) {
      parts.push(`${t("accept_invitation.scope_buildings")}: ${preview.building_names.join(", ")}`);
    }
    if (preview.customer_names.length > 0) {
      parts.push(`${t("accept_invitation.scope_customers")}: ${preview.customer_names.join(", ")}`);
    }
    return parts.join(" · ");
  }, [loadState, t]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneralError("");
    setFieldErrors({});

    if (password.length === 0) {
      setFieldErrors({ new_password: t("accept_invitation.error_choose_password") });
      return;
    }
    if (password !== confirmPassword) {
      setFieldErrors({ new_password: t("accept_invitation.error_passwords_dont_match") });
      return;
    }

    setSubmitting(true);
    try {
      await api.post("/auth/invitations/accept/", {
        token,
        new_password: password,
      });
      navigate("/login?invited=ok", { replace: true });
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

        {loadState.kind === "loading" && (
          <div className="login-welcome">
            <h2 className="login-welcome-title">{t("accept_invitation.loading_title")}</h2>
            <p className="login-welcome-sub">{t("accept_invitation.loading_sub")}</p>
          </div>
        )}

        {loadState.kind === "missing-token" && (
          <>
            <div className="login-welcome">
              <h2 className="login-welcome-title">
                {t("accept_invitation.missing_token_title")}
              </h2>
              <p className="login-welcome-sub">
                {t("accept_invitation.missing_token_desc")}
              </p>
            </div>
            <div style={{ marginTop: 24, fontSize: 13 }}>
              <Link className="login-field-link" to="/login">
                {t("accept_invitation.back_to_signin")}
              </Link>
            </div>
          </>
        )}

        {loadState.kind === "not-found" && (
          <>
            <div className="login-welcome">
              <h2 className="login-welcome-title">{t("accept_invitation.not_found_title")}</h2>
              <p className="login-welcome-sub">
                {t("accept_invitation.not_found_desc")}
              </p>
            </div>
            <div style={{ marginTop: 24, fontSize: 13 }}>
              <Link className="login-field-link" to="/login">
                {t("accept_invitation.back_to_signin")}
              </Link>
            </div>
          </>
        )}

        {loadState.kind === "gone" && (
          <>
            <div className="login-welcome">
              <h2 className="login-welcome-title">{t("accept_invitation.gone_title")}</h2>
              <p className="login-welcome-sub">
                {t("accept_invitation.gone_desc", {
                  status:
                    loadState.status?.toLowerCase() ||
                    t("accept_invitation.gone_status_fallback"),
                })}
              </p>
            </div>
            <div style={{ marginTop: 24, fontSize: 13 }}>
              <Link className="login-field-link" to="/login">
                {t("accept_invitation.back_to_signin")}
              </Link>
            </div>
          </>
        )}

        {loadState.kind === "error" && (
          <>
            <div className="login-welcome">
              <h2 className="login-welcome-title">{t("accept_invitation.error_title")}</h2>
              <p className="login-welcome-sub">{loadState.message}</p>
            </div>
            <div style={{ marginTop: 24, fontSize: 13 }}>
              <Link className="login-field-link" to="/login">
                {t("accept_invitation.back_to_signin")}
              </Link>
            </div>
          </>
        )}

        {loadState.kind === "ready" && (
          <>
            <div className="login-welcome">
              <h2 className="login-welcome-title">{t("accept_invitation.welcome_title")}</h2>
              <p className="login-welcome-sub">
                {t("accept_invitation.welcome_lead", {
                  inviter: inviterName,
                  role: t(ROLE_KEYS[loadState.preview.role] ?? "common:roles.fallback"),
                })}
                {scopeLine && (
                  <>
                    <br />
                    {scopeLine}
                  </>
                )}
              </p>
            </div>

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

            {fieldErrors.email && (
              <div className="alert-error login-error" role="alert">
                {fieldErrors.email}
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
                  <label className="login-field-label" htmlFor="invite-new-password">
                    {t("accept_invitation.field_new_password")}
                  </label>
                </div>
                <div className="login-field-wrap">
                  <LockKeyhole
                    className="login-field-icon"
                    size={18}
                    strokeWidth={2}
                  />
                  <input
                    id="invite-new-password"
                    className="login-field-input has-toggle"
                    type={showPassword ? "text" : "password"}
                    placeholder="••••••••"
                    autoComplete="new-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                  />
                  <button
                    type="button"
                    className="login-field-toggle"
                    aria-label={
                      showPassword
                        ? t("accept_invitation.aria_hide_password")
                        : t("accept_invitation.aria_show_password")
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
                {fieldErrors.new_password && (
                  <div className="alert-error login-error" role="alert">
                    {fieldErrors.new_password}
                  </div>
                )}
              </div>

              <div className="login-field">
                <div className="login-field-row">
                  <label className="login-field-label" htmlFor="invite-confirm-password">
                    {t("accept_invitation.field_confirm_password")}
                  </label>
                </div>
                <div className="login-field-wrap">
                  <LockKeyhole
                    className="login-field-icon"
                    size={18}
                    strokeWidth={2}
                  />
                  <input
                    id="invite-confirm-password"
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
                disabled={submitting || !password || !confirmPassword}
              >
                {submitting
                  ? t("accept_invitation.creating_account")
                  : t("accept_invitation.submit")}
              </button>
            </form>

            <div style={{ marginTop: 24, fontSize: 13 }}>
              <Link className="login-field-link" to="/login">
                {t("accept_invitation.back_to_signin")}
              </Link>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
