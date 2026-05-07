import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { BellRing, Check, Save, ShieldCheck, UserCircle2 } from "lucide-react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  NotificationEventType,
  NotificationPreferenceEntry,
  NotificationPreferencesResponse,
} from "../api/types";

// The four user-mutable event types map to settings.json keys. The API
// response also carries a label, but we override with the locale-specific
// translation so the toggle list matches the rest of the UI.
const EVENT_LABEL_KEYS: Record<NotificationEventType, string> = {
  TICKET_CREATED: "event_ticket_created",
  TICKET_STATUS_CHANGED: "event_ticket_status_changed",
  TICKET_ASSIGNED: "event_ticket_assigned",
  TICKET_UNASSIGNED: "event_ticket_unassigned",
};

type FieldErrors = Record<string, string | undefined>;

const fieldErrorStyle: React.CSSProperties = {
  marginTop: 6,
  fontSize: 12,
  fontWeight: 600,
  color: "var(--red)",
};

function fieldError(data: unknown, key: string): string | undefined {
  if (!data || typeof data !== "object") return undefined;
  const value = (data as Record<string, unknown>)[key];
  if (Array.isArray(value) && value.length > 0) return String(value[0]);
  if (typeof value === "string") return value;
  return undefined;
}

function errorPayload(err: unknown): unknown {
  if (axios.isAxiosError(err)) return err.response?.data;
  return undefined;
}

const ROLE_KEYS: Record<string, string> = {
  SUPER_ADMIN: "common:roles.super_admin",
  COMPANY_ADMIN: "common:roles.company_admin",
  BUILDING_MANAGER: "common:roles.building_manager",
  CUSTOMER_USER: "common:roles.customer_user",
};

function getInitials(fullName: string, email: string): string {
  const cleaned = (fullName || "").trim();
  if (cleaned) {
    const parts = cleaned.split(/\s+/);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return parts[0].slice(0, 2).toUpperCase();
  }
  return (email.split("@")[0] || "?").slice(0, 2).toUpperCase();
}

function formatJoinDate(iso: string, lang: string): string {
  try {
    return new Intl.DateTimeFormat(lang === "nl" ? "nl-NL" : "en-US", {
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

// Returns a translated "X minutes ago" / "X hours ago" / "X days ago"
// string for recent timestamps; falls back to an absolute date once the
// gap exceeds 7 days. Plurals via i18next count interpolation.
function formatLastSignIn(
  iso: string | null,
  lang: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: (key: string, opts?: any) => string,
): string {
  if (!iso) return t("common:account.never_signed_in");
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return iso;
  const diffMs = Date.now() - then.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHr = Math.floor(diffMs / 3600000);
  const diffDay = Math.floor(diffMs / 86400000);
  if (diffMin < 1) return t("common:time.just_now");
  if (diffMin < 60) return t("common:time.minutes_ago", { count: diffMin });
  if (diffHr < 24) return t("common:time.hours_ago", { count: diffHr });
  if (diffDay < 7) return t("common:time.days_ago", { count: diffDay });
  return formatJoinDate(iso, lang);
}

export function SettingsPage() {
  const { me, reloadMe } = useAuth();
  const { t, i18n } = useTranslation(["settings", "common"]);

  const languageOptions = [
    { value: "nl", label: `${t("common:language_dutch")} (nl)` },
    { value: "en", label: `${t("common:language_english")} (en)` },
  ];

  const [fullName, setFullName] = useState(me?.full_name ?? "");
  const [language, setLanguage] = useState(me?.language ?? "nl");
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileSaved, setProfileSaved] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [profileFieldErrors, setProfileFieldErrors] = useState<FieldErrors>({});

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordSaved, setPasswordSaved] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [passwordFieldErrors, setPasswordFieldErrors] =
    useState<FieldErrors>({});

  const [preferences, setPreferences] = useState<NotificationPreferenceEntry[]>(
    [],
  );
  const [preferencesLoading, setPreferencesLoading] = useState(true);
  const [preferencesSaving, setPreferencesSaving] = useState(false);
  const [preferencesSaved, setPreferencesSaved] = useState(false);
  const [preferencesError, setPreferencesError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .get<NotificationPreferencesResponse>("/auth/notification-preferences/")
      .then((response) => {
        if (cancelled) return;
        setPreferences(response.data.preferences);
      })
      .catch((err) => {
        if (cancelled) return;
        setPreferencesError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setPreferencesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function togglePreference(eventType: string) {
    setPreferencesSaved(false);
    setPreferences((current) =>
      current.map((entry) =>
        entry.event_type === eventType
          ? { ...entry, muted: !entry.muted }
          : entry,
      ),
    );
  }

  async function handlePreferencesSubmit(event: FormEvent) {
    event.preventDefault();
    setPreferencesSaved(false);
    setPreferencesError("");
    setPreferencesSaving(true);

    try {
      const response = await api.patch<NotificationPreferencesResponse>(
        "/auth/notification-preferences/",
        {
          preferences: preferences.map((entry) => ({
            event_type: entry.event_type,
            muted: entry.muted,
          })),
        },
      );
      setPreferences(response.data.preferences);
      setPreferencesSaved(true);
    } catch (err) {
      setPreferencesError(getApiError(err));
    } finally {
      setPreferencesSaving(false);
    }
  }

  async function handleProfileSubmit(event: FormEvent) {
    event.preventDefault();
    setProfileSaved(false);
    setProfileError("");
    setProfileFieldErrors({});

    const trimmed = fullName.trim();
    if (!trimmed) {
      setProfileFieldErrors({ full_name: t("full_name_empty") });
      return;
    }

    setProfileSaving(true);
    try {
      await api.patch("/auth/me/", { full_name: trimmed, language });
      await reloadMe();
      setProfileSaved(true);
    } catch (err) {
      const data = errorPayload(err);
      const next: FieldErrors = {
        full_name: fieldError(data, "full_name"),
        language: fieldError(data, "language"),
      };
      setProfileFieldErrors(next);
      if (!next.full_name && !next.language) {
        setProfileError(getApiError(err));
      }
    } finally {
      setProfileSaving(false);
    }
  }

  async function handlePasswordSubmit(event: FormEvent) {
    event.preventDefault();
    setPasswordSaved(false);
    setPasswordError("");
    setPasswordFieldErrors({});

    // Client-side guards mirror Django's default validators where they map
    // cleanly: required + 8-char minimum + confirm-must-match. Anything
    // stronger (common-password, all-numeric) round-trips to the server.
    const local: FieldErrors = {};
    if (!currentPassword) {
      local.current_password = t("current_password_required");
    }
    if (!newPassword) {
      local.new_password = t("new_password_required");
    } else if (newPassword.length < 8) {
      local.new_password = t("new_password_too_short");
    }
    if (newPassword && newPassword !== confirmPassword) {
      local.confirm_password = t("confirm_password_mismatch");
    }
    if (Object.keys(local).length > 0) {
      setPasswordFieldErrors(local);
      return;
    }

    setPasswordSaving(true);
    try {
      await api.post("/auth/password/change/", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordSaved(true);
    } catch (err) {
      const data = errorPayload(err);
      const next: FieldErrors = {
        current_password: fieldError(data, "current_password"),
        new_password: fieldError(data, "new_password"),
      };
      setPasswordFieldErrors(next);
      if (!next.current_password && !next.new_password) {
        setPasswordError(getApiError(err));
      }
    } finally {
      setPasswordSaving(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow">{t("eyebrow")}</div>
          <h2 className="page-title">{t("title")}</h2>
          <p className="page-sub">{t("subtitle")}</p>
        </div>
      </div>

      <div className="settings-layout">
        <aside>
          {me && (
            <section className="card account-overview">
              <div className="account-overview-header">
                <div className="account-avatar">
                  {getInitials(me.full_name, me.email)}
                </div>
                <div className="account-identity">
                  {me.full_name?.trim() && (
                    <div className="account-name">{me.full_name}</div>
                  )}
                  <div className="account-email">{me.email}</div>
                  {me.role && (
                    <span className="account-role-pill">
                      {t(ROLE_KEYS[me.role] ?? "common:roles.fallback")}
                    </span>
                  )}
                </div>
              </div>

              <div className="account-overview-divider" />

              <div className="account-meta">
                <div className="account-meta-row">
                  <div className="account-meta-label">
                    {t("common:account.member_since")}
                  </div>
                  <div className="account-meta-value">
                    {me.date_joined
                      ? formatJoinDate(me.date_joined, i18n.language)
                      : "—"}
                  </div>
                </div>
                <div className="account-meta-row">
                  <div className="account-meta-label">
                    {t("common:account.last_sign_in")}
                  </div>
                  <div className="account-meta-value">
                    {formatLastSignIn(me.last_login, i18n.language, t)}
                  </div>
                </div>
              </div>

              {(me.company_ids.length > 0 ||
                me.building_ids.length > 0 ||
                me.customer_ids.length > 0) && (
                <>
                  <div className="account-overview-divider" />
                  <div className="account-access">
                    <div className="account-access-label">
                      {t("common:account.access")}
                    </div>
                    {me.company_ids.length > 0 && (
                      <div className="account-access-row">
                        <span className="account-access-count">
                          {me.company_ids.length}
                        </span>
                        <span className="account-access-name">
                          {t("common:account.companies", {
                            count: me.company_ids.length,
                          })}
                        </span>
                      </div>
                    )}
                    {me.building_ids.length > 0 && (
                      <div className="account-access-row">
                        <span className="account-access-count">
                          {me.building_ids.length}
                        </span>
                        <span className="account-access-name">
                          {t("common:account.buildings", {
                            count: me.building_ids.length,
                          })}
                        </span>
                      </div>
                    )}
                    {me.customer_ids.length > 0 && (
                      <div className="account-access-row">
                        <span className="account-access-count">
                          {me.customer_ids.length}
                        </span>
                        <span className="account-access-name">
                          {t("common:account.customers", {
                            count: me.customer_ids.length,
                          })}
                        </span>
                      </div>
                    )}
                  </div>
                </>
              )}
            </section>
          )}
        </aside>

        <div className="settings-main">
        <form className="card" onSubmit={handleProfileSubmit} noValidate>
          <div className="form-section">
            <div
              className="form-section-title"
              style={{ display: "flex", alignItems: "center", gap: 8 }}
            >
              <UserCircle2 size={16} strokeWidth={2} />
              {t("profile_title")}
            </div>
            <div className="form-section-helper">{t("profile_helper")}</div>

            <div className="field">
              <label className="field-label" htmlFor="settings-email">
                {t("email_label")}
              </label>
              <input
                id="settings-email"
                className="field-input"
                type="email"
                value={me?.email ?? ""}
                disabled
                readOnly
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="settings-full-name">
                {t("full_name_label")}
              </label>
              <input
                id="settings-full-name"
                className="field-input"
                type="text"
                maxLength={255}
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
              />
              {profileFieldErrors.full_name && (
                <div style={fieldErrorStyle} role="alert">
                  {profileFieldErrors.full_name}
                </div>
              )}
            </div>

            <div className="field">
              <label className="field-label" htmlFor="settings-language">
                {t("language_label")}
              </label>
              <select
                id="settings-language"
                className="field-select"
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
              >
                {languageOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              {profileFieldErrors.language && (
                <div style={fieldErrorStyle} role="alert">
                  {profileFieldErrors.language}
                </div>
              )}
            </div>

            {profileError && (
              <div className="alert-error" role="alert">
                {profileError}
              </div>
            )}
          </div>
          <div className="form-actions">
            {profileSaved && (
              <span className="form-saved-indicator" role="status">
                <Check size={13} strokeWidth={2.5} />
                {t("profile_saved")}
              </span>
            )}
            <button
              type="submit"
              className="btn btn-primary"
              disabled={profileSaving}
            >
              <Save size={14} strokeWidth={2.5} />
              {profileSaving ? t("profile_saving") : t("profile_save")}
            </button>
          </div>
        </form>

        <form className="card" onSubmit={handlePasswordSubmit} noValidate>
          <div className="form-section">
            <div
              className="form-section-title"
              style={{ display: "flex", alignItems: "center", gap: 8 }}
            >
              <ShieldCheck size={16} strokeWidth={2} />
              {t("password_title")}
            </div>
            <div className="form-section-helper">{t("password_helper")}</div>

            <div className="field">
              <label className="field-label" htmlFor="settings-current-password">
                {t("current_password_label")}
              </label>
              <input
                id="settings-current-password"
                className="field-input"
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
              />
              {passwordFieldErrors.current_password && (
                <div style={fieldErrorStyle} role="alert">
                  {passwordFieldErrors.current_password}
                </div>
              )}
            </div>

            <div className="field">
              <label className="field-label" htmlFor="settings-new-password">
                {t("new_password_label")}
              </label>
              <input
                id="settings-new-password"
                className="field-input"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
              />
              {passwordFieldErrors.new_password && (
                <div style={fieldErrorStyle} role="alert">
                  {passwordFieldErrors.new_password}
                </div>
              )}
            </div>

            <div className="field">
              <label
                className="field-label"
                htmlFor="settings-confirm-password"
              >
                {t("confirm_password_label")}
              </label>
              <input
                id="settings-confirm-password"
                className="field-input"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
              />
              {passwordFieldErrors.confirm_password && (
                <div style={fieldErrorStyle} role="alert">
                  {passwordFieldErrors.confirm_password}
                </div>
              )}
            </div>

            {passwordError && (
              <div className="alert-error" role="alert">
                {passwordError}
              </div>
            )}
          </div>
          <div className="form-actions">
            {passwordSaved && (
              <span className="form-saved-indicator" role="status">
                <Check size={13} strokeWidth={2.5} />
                {t("password_saved")}
              </span>
            )}
            <button
              type="submit"
              className="btn btn-primary"
              disabled={passwordSaving}
            >
              <Save size={14} strokeWidth={2.5} />
              {passwordSaving ? t("password_saving") : t("password_save")}
            </button>
          </div>
        </form>

        <form className="card" onSubmit={handlePreferencesSubmit} noValidate>
          <div className="form-section">
            <div
              className="form-section-title"
              style={{ display: "flex", alignItems: "center", gap: 8 }}
            >
              <BellRing size={16} strokeWidth={2} />
              {t("notifications_title")}
            </div>
            <div className="form-section-helper">
              {t("notifications_helper")}
            </div>

            {preferencesLoading ? (
              <div className="loading-bar">
                <div className="loading-bar-fill" />
              </div>
            ) : (
              <div>
                {preferences.map((entry) => {
                  const checked = !entry.muted;
                  // Frontend translation overrides the API-provided label so
                  // the toggle list switches language with the rest of the
                  // page. The API label remains as a fallback if the key is
                  // absent (defensive — all four are populated).
                  const labelKey = EVENT_LABEL_KEYS[entry.event_type];
                  const label = labelKey ? t(labelKey) : entry.label;
                  return (
                    <label
                      key={entry.event_type}
                      className="notification-row"
                    >
                      <span className="notification-row-label">{label}</span>
                      <span className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => togglePreference(entry.event_type)}
                        />
                        <span className="toggle-switch-slider" />
                      </span>
                    </label>
                  );
                })}
              </div>
            )}

            {preferencesError && (
              <div className="alert-error" role="alert">
                {preferencesError}
              </div>
            )}
          </div>
          <div className="form-actions">
            {preferencesSaved && (
              <span className="form-saved-indicator" role="status">
                <Check size={13} strokeWidth={2.5} />
                {t("notifications_saved")}
              </span>
            )}
            <button
              type="submit"
              className="btn btn-primary"
              disabled={preferencesSaving || preferencesLoading}
            >
              <Save size={14} strokeWidth={2.5} />
              {preferencesSaving
                ? t("notifications_saving")
                : t("notifications_save")}
            </button>
          </div>
        </form>
        </div>
      </div>
    </div>
  );
}
