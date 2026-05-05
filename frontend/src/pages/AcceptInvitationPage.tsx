import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Building2, Eye, EyeOff, LockKeyhole } from "lucide-react";
import { api, getApiError } from "../api/client";
import type { InvitationPreview, Role } from "../api/types";

const ROLE_LABEL: Record<Role, string> = {
  SUPER_ADMIN: "Super admin",
  COMPANY_ADMIN: "Company admin",
  BUILDING_MANAGER: "Building manager",
  CUSTOMER_USER: "Customer user",
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

function scopeSummary(preview: InvitationPreview): string {
  const parts: string[] = [];
  if (preview.company_names.length > 0) {
    parts.push(`Company: ${preview.company_names.join(", ")}`);
  }
  if (preview.building_names.length > 0) {
    parts.push(`Buildings: ${preview.building_names.join(", ")}`);
  }
  if (preview.customer_names.length > 0) {
    parts.push(`Customers: ${preview.customer_names.join(", ")}`);
  }
  return parts.join(" · ");
}

export function AcceptInvitationPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";

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

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneralError("");
    setFieldErrors({});

    if (password.length === 0) {
      setFieldErrors({ new_password: "Choose a password." });
      return;
    }
    if (password !== confirmPassword) {
      setFieldErrors({ new_password: "The two passwords do not match." });
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
            <h2 className="login-welcome-title">Loading invitation</h2>
            <p className="login-welcome-sub">One moment.</p>
          </div>
        )}

        {loadState.kind === "missing-token" && (
          <>
            <div className="login-welcome">
              <h2 className="login-welcome-title">Invitation link is incomplete</h2>
              <p className="login-welcome-sub">
                The link in your email did not include a token. Open the email and click the link again, or ask the person who invited you for a fresh invitation.
              </p>
            </div>
            <div style={{ marginTop: 24, fontSize: 13 }}>
              <Link className="login-field-link" to="/login">
                Back to sign in
              </Link>
            </div>
          </>
        )}

        {loadState.kind === "not-found" && (
          <>
            <div className="login-welcome">
              <h2 className="login-welcome-title">Invitation not found</h2>
              <p className="login-welcome-sub">
                The invitation token does not match anything on file. It may have already been used or revoked.
              </p>
            </div>
            <div style={{ marginTop: 24, fontSize: 13 }}>
              <Link className="login-field-link" to="/login">
                Back to sign in
              </Link>
            </div>
          </>
        )}

        {loadState.kind === "gone" && (
          <>
            <div className="login-welcome">
              <h2 className="login-welcome-title">Invitation no longer valid</h2>
              <p className="login-welcome-sub">
                This invitation is {loadState.status?.toLowerCase() || "no longer active"}. Ask the person who invited you to send a new one.
              </p>
            </div>
            <div style={{ marginTop: 24, fontSize: 13 }}>
              <Link className="login-field-link" to="/login">
                Back to sign in
              </Link>
            </div>
          </>
        )}

        {loadState.kind === "error" && (
          <>
            <div className="login-welcome">
              <h2 className="login-welcome-title">Could not load invitation</h2>
              <p className="login-welcome-sub">{loadState.message}</p>
            </div>
            <div style={{ marginTop: 24, fontSize: 13 }}>
              <Link className="login-field-link" to="/login">
                Back to sign in
              </Link>
            </div>
          </>
        )}

        {loadState.kind === "ready" && (
          <>
            <div className="login-welcome">
              <h2 className="login-welcome-title">Accept your invitation</h2>
              <p className="login-welcome-sub">
                {inviterName} invited you to join CleanOps as{" "}
                {ROLE_LABEL[loadState.preview.role] || loadState.preview.role}.
                {scopeSummary(loadState.preview) && (
                  <>
                    <br />
                    {scopeSummary(loadState.preview)}
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
                    Choose a password
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
                    aria-label={showPassword ? "Hide password" : "Show password"}
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
                    Confirm password
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
                {submitting ? "Creating account…" : "Accept and create account"}
              </button>
            </form>

            <div style={{ marginTop: 24, fontSize: 13 }}>
              <Link className="login-field-link" to="/login">
                Back to sign in
              </Link>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
