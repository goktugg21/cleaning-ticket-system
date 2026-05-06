import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { BellRing, Save, ShieldCheck, UserCircle2 } from "lucide-react";
import axios from "axios";
import { api, getApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type {
  NotificationPreferenceEntry,
  NotificationPreferencesResponse,
} from "../api/types";

const LANGUAGE_OPTIONS = [
  { value: "nl", label: "Nederlands (nl)" },
  { value: "en", label: "English (en)" },
];

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
      setProfileFieldErrors({ full_name: "Full name cannot be empty." });
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
      local.current_password = "Current password is required.";
    }
    if (!newPassword) {
      local.new_password = "New password is required.";
    } else if (newPassword.length < 8) {
      local.new_password = "New password must be at least 8 characters.";
    }
    if (newPassword && newPassword !== confirmPassword) {
      local.confirm_password = "Passwords do not match.";
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
          <div className="eyebrow">Account</div>
          <h2 className="page-title">Settings</h2>
          <p className="page-sub">
            Update your profile, password, and notification preferences.
          </p>
        </div>
      </div>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          maxWidth: 720,
        }}
      >
        <form className="card" onSubmit={handleProfileSubmit} noValidate>
          <div className="form-section">
            <div
              className="form-section-title"
              style={{ display: "flex", alignItems: "center", gap: 8 }}
            >
              <UserCircle2 size={16} strokeWidth={2} />
              Profile
            </div>
            <div className="form-section-helper">
              Your name and preferred language.
            </div>

            <div className="field">
              <label className="field-label" htmlFor="settings-email">
                Email
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
                Full name
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
                Language
              </label>
              <select
                id="settings-language"
                className="field-select"
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
              >
                {LANGUAGE_OPTIONS.map((option) => (
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

            {profileSaved && (
              <div className="alert-info" role="status">
                Profile saved.
              </div>
            )}
            {profileError && (
              <div className="alert-error" role="alert">
                {profileError}
              </div>
            )}
          </div>
          <div className="form-actions">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={profileSaving}
            >
              <Save size={14} strokeWidth={2.5} />
              {profileSaving ? "Saving…" : "Save profile"}
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
              Password
            </div>
            <div className="form-section-helper">
              Use a strong password. Your existing session stays signed in
              after the change.
            </div>

            <div className="field">
              <label className="field-label" htmlFor="settings-current-password">
                Current password
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
                New password
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
                Confirm new password
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

            {passwordSaved && (
              <div className="alert-info" role="status">
                Password updated.
              </div>
            )}
            {passwordError && (
              <div className="alert-error" role="alert">
                {passwordError}
              </div>
            )}
          </div>
          <div className="form-actions">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={passwordSaving}
            >
              <Save size={14} strokeWidth={2.5} />
              {passwordSaving ? "Saving…" : "Update password"}
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
              Notification preferences
            </div>
            <div className="form-section-helper">
              Choose which events trigger an email to you. Security and
              onboarding emails are always sent.
            </div>

            {preferencesLoading ? (
              <div className="loading-bar">
                <div className="loading-bar-fill" />
              </div>
            ) : (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                }}
              >
                {preferences.map((entry) => {
                  const checked = !entry.muted;
                  const inputId = `pref-${entry.event_type}`;
                  return (
                    <label
                      key={entry.event_type}
                      htmlFor={inputId}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "10px 12px",
                        border: "1px solid var(--border-soft)",
                        borderRadius: "var(--r)",
                        cursor: "pointer",
                        gap: 12,
                      }}
                    >
                      <span style={{ fontSize: 13, fontWeight: 600 }}>
                        {entry.label}
                      </span>
                      <span
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                        }}
                      >
                        <span
                          style={{
                            fontSize: 12,
                            fontWeight: 700,
                            color: checked
                              ? "var(--green)"
                              : "var(--text-faint)",
                            minWidth: 28,
                            textAlign: "right",
                          }}
                        >
                          {checked ? "On" : "Off"}
                        </span>
                        <input
                          id={inputId}
                          type="checkbox"
                          checked={checked}
                          onChange={() => togglePreference(entry.event_type)}
                          style={{
                            width: 16,
                            height: 16,
                            cursor: "pointer",
                            accentColor: "var(--green)",
                          }}
                        />
                      </span>
                    </label>
                  );
                })}
              </div>
            )}

            {preferencesSaved && (
              <div className="alert-info" role="status">
                Notification preferences saved.
              </div>
            )}
            {preferencesError && (
              <div className="alert-error" role="alert">
                {preferencesError}
              </div>
            )}
          </div>
          <div className="form-actions">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={preferencesSaving || preferencesLoading}
            >
              <Save size={14} strokeWidth={2.5} />
              {preferencesSaving ? "Saving…" : "Save preferences"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
