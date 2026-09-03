import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { BellRing, Check, Save, ShieldCheck, UserCircle2 } from "lucide-react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ImageUploadField } from "../components/ImageUploadField";
import { formatDate, useLocaleCode } from "../lib/intl";
import { deleteProfilePhoto, uploadProfilePhoto } from "../api/media";
import { isCustomerUser, roleLabelKeyNs } from "../auth/permissions";
import { Toggle } from "../components/Toggle";
import type {
  NotificationEventType,
  NotificationPreferenceEntry,
  NotificationPreferencesResponse,
} from "../api/types";

// The user-mutable event types map to settings.json keys. The API
// response also carries a label, but we override with the locale-specific
// translation so the toggle list matches the rest of the UI. The two
// *_MESSAGE entries are the IA 2026-06-25 in-app feed toggles — their
// labels spell out the default-off ("also show ... in Notifications").
const EVENT_LABEL_KEYS: Record<NotificationEventType, string> = {
  TICKET_CREATED: "event_ticket_created",
  TICKET_STATUS_CHANGED: "event_ticket_status_changed",
  TICKET_ASSIGNED: "event_ticket_assigned",
  TICKET_UNASSIGNED: "event_ticket_unassigned",
  TICKET_MESSAGE: "event_ticket_message_feed",
  EXTRA_WORK_MESSAGE: "event_extra_work_message_feed",
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


export function SettingsPage() {
  const { me, reloadMe } = useAuth();
  const { t } = useTranslation(["settings", "common"]);
  const locale = useLocaleCode();

  // P-8R D — the header's third fact: "3 bedrijven · 12 gebouwen". Counts
  // only, from the id sets /api/auth/me/ already carries; a role with no
  // scope rows reads "—" rather than a claim.
  const accessSummary = me
    ? (
        [
          [me.company_ids.length, "common:account.companies"],
          [me.building_ids.length, "common:account.buildings"],
          [me.customer_ids.length, "common:account.customers"],
        ] as const
      )
        .filter(([count]) => count > 0)
        .map(([count, key]) => `${count} ${t(key, { count })}`)
        .join(" · ")
    : "";

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
      {/* P-7 S7 / P-8R D — the profile is a HORIZONTAL header band at
          every width: the avatar (its pencil badge opens the photo
          upload, the remove link sits under it), the name, the email
          and the role on one line, ONE quiet meta row under it (member
          since · access — P-9 dropped "last sign-in", which the token
          door never records). The forms fill the width below in a
          two-column grid of equal-height cards. */}
      <div className="page-header">
        <div>
          <div className="eyebrow">{t("eyebrow")}</div>
          <h2 className="page-title">{t("title")}</h2>
          <p className="page-sub">{t("subtitle")}</p>
        </div>
      </div>

      {me && (
        <section className="card account-header" data-testid="settings-account-header">
          {/* RF-1 — own profile photo (always self-service). */}
          <ImageUploadField
            variant="badge"
            imageUrl={me.profile_photo_url}
            name={me.full_name || me.email}
            size={64}
            testId="profile-photo-upload"
            onUpload={async (file) => {
              await uploadProfilePhoto(me.id, file);
              await reloadMe();
            }}
            onRemove={async () => {
              await deleteProfilePhoto(me.id);
              await reloadMe();
            }}
          />
          <div className="account-header-main">
            <div className="account-header-identity">
              {me.full_name?.trim() && (
                <span className="account-name">{me.full_name}</span>
              )}
              <span className="account-email">{me.email}</span>
              {me.role && (
                <span className="account-role-pill">{t(roleLabelKeyNs(me.role))}</span>
              )}
            </div>
            <dl className="account-header-facts" data-testid="settings-account-facts">
              <div className="account-header-fact">
                <dt>{t("common:account.member_since")}</dt>
                <dd>{formatDate(me.date_joined, locale)}</dd>
              </div>
              {/* P-9 G (SS D.20 ruling 12(c)) — no "last sign-in" row: the
                  JWT token door does not record `last_login`
                  (`SIMPLE_JWT` sets no `UPDATE_LAST_LOGIN`), and a fact
                  the system does not know is not shown. */}
              <div className="account-header-fact">
                <dt>{t("common:account.access")}</dt>
                <dd>{accessSummary || "—"}</dd>
              </div>
            </dl>
          </div>
        </section>
      )}

      {/* P-8R D — Profile and Password side by side, Notifications
          spanning the full width under them; one column at laptop
          widths and below (see .settings-layout in index.css). */}
      <div className="settings-layout">
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
                aria-describedby="settings-new-password-hint"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
              />
              <div
                id="settings-new-password-hint"
                className="field-hint"
                style={{
                  marginTop: 4,
                  fontSize: 12,
                  color: "var(--text-muted)",
                  lineHeight: 1.4,
                }}
              >
                {t("password_requirements_hint")}
              </div>
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

        <form
          className="card settings-span"
          onSubmit={handlePreferencesSubmit}
          noValidate
        >
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
              <div className="notification-rows">
                {preferences.map((entry) => {
                  const checked = !entry.muted;
                  // Frontend translation overrides the API-provided label so
                  // the toggle list switches language with the rest of the
                  // page. The API label remains as a fallback if the key is
                  // absent (defensive — all four are populated).
                  const labelKey = EVENT_LABEL_KEYS[entry.event_type];
                  // P-15 (P-14's S3 finding, §D.2) — a customer never
                  // sees the word "ticket"; their portal calls it a
                  // MELDING. Same keys with the `_customer` suffix,
                  // picked by the viewer's side.
                  const label = labelKey
                    ? t(
                        isCustomerUser(me?.role)
                          ? `${labelKey}_customer`
                          : labelKey,
                      )
                    : entry.label;
                  return (
                    <label
                      key={entry.event_type}
                      className="notification-row"
                    >
                      <span className="notification-row-label">{label}</span>
                      <Toggle
                        checked={checked}
                        onChange={() => togglePreference(entry.event_type)}
                      />
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
  );
}
