/**
 * Sprint 28 Batch 15.1 — topbar user menu.
 *
 * Replaces the inline `<userName><userEmail><roleLabel><Sign out>`
 * block in the AppShell topbar. Premium SaaS pattern: avatar
 * trigger → dropdown with identity + language toggle + settings +
 * sign-out.
 *
 * Why a language toggle here:
 *   The only previous way to switch language was Settings →
 *   Profile → save, three clicks deep. The user has to round-trip
 *   to the backend anyway (preference is stored on the User row),
 *   so the toggle PATCH /auth/me/ + reloadMe(); the existing
 *   useLanguageSync hook then flips i18next on the next render.
 *   We also call i18n.changeLanguage immediately for instant
 *   feedback in case the PATCH is slow — useLanguageSync is
 *   idempotent.
 *
 * The trigger and panel are intentionally CSS-class-based (no
 * portal, no popper). The whole shell is small enough that
 * positioning is trivial and we avoid hauling in another
 * dependency.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ChevronDown, LogOut, Settings as SettingsIcon } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/client";
import { getInitials } from "../lib/initials";
import { RoleBadge } from "./RoleBadge";
import type { Role } from "../api/types";

interface UserMenuProps {
  /** Test id attached to the trigger button. */
  testId?: string;
}

export function UserMenu({ testId }: UserMenuProps) {
  const { me, logout, reloadMe } = useAuth();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation("common");
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [pendingLang, setPendingLang] = useState<"nl" | "en" | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  const userName = useMemo(
    () => me?.full_name?.trim() || me?.email || t("topbar.user_fallback"),
    [me?.full_name, me?.email, t],
  );
  const userEmail = me?.email ?? "";
  const role: Role | null = me?.role ?? null;
  const currentLang: "nl" | "en" = i18n.language === "en" ? "en" : "nl";

  // Close on click outside.
  useEffect(() => {
    if (!open) return;
    function handlePointer(event: MouseEvent) {
      const root = wrapRef.current;
      if (!root) return;
      if (event.target instanceof Node && !root.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handlePointer);
    return () => document.removeEventListener("mousedown", handlePointer);
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  const handleLogout = useCallback(() => {
    setOpen(false);
    logout();
    navigate("/login", { replace: true });
  }, [logout, navigate]);

  const handleSettings = useCallback(() => {
    setOpen(false);
    navigate("/settings");
  }, [navigate]);

  const handleLanguage = useCallback(
    async (lang: "nl" | "en") => {
      if (lang === currentLang) return;
      // Instant feedback — useLanguageSync will reconcile after reloadMe.
      i18n.changeLanguage(lang);
      setPendingLang(lang);
      try {
        await api.patch("/auth/me/", { language: lang });
        await reloadMe();
      } catch {
        // Roll back the visual switch on persistence failure so the
        // sidebar doesn't drift away from the server-side preference.
        i18n.changeLanguage(currentLang);
      } finally {
        setPendingLang(null);
      }
    },
    [currentLang, i18n, reloadMe],
  );

  return (
    <div className="user-menu" ref={wrapRef}>
      <button
        type="button"
        ref={triggerRef}
        className="user-menu-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={open ? t("user_menu.close") : t("user_menu.open")}
        onClick={() => setOpen((value) => !value)}
        data-testid={testId ?? "user-menu-trigger"}
      >
        <span className="user-menu-avatar">{getInitials(userName)}</span>
        <span className="user-menu-chevron" aria-hidden="true">
          <ChevronDown size={14} strokeWidth={2.2} />
        </span>
      </button>

      {open && (
        <div
          id={panelId}
          role="menu"
          className="user-menu-panel"
          data-testid="user-menu-panel"
        >
          <div className="user-menu-header">
            <div className="user-menu-name">{userName}</div>
            {userEmail && <div className="user-menu-email">{userEmail}</div>}
            {role && (
              <div className="user-menu-role">
                <RoleBadge role={role} compact />
              </div>
            )}
          </div>

          <div className="user-menu-divider" role="separator" />

          <div className="user-menu-section" role="none">
            <div className="user-menu-section-label">
              {t("user_menu.language_label")}
            </div>
            <div className="user-menu-lang-toggle" role="radiogroup">
              <button
                type="button"
                role="radio"
                aria-checked={currentLang === "nl"}
                className={`user-menu-lang-option${
                  currentLang === "nl" ? " user-menu-lang-option-active" : ""
                }`}
                onClick={() => handleLanguage("nl")}
                disabled={pendingLang !== null}
              >
                {t("user_menu.lang_nl")}
              </button>
              <button
                type="button"
                role="radio"
                aria-checked={currentLang === "en"}
                className={`user-menu-lang-option${
                  currentLang === "en" ? " user-menu-lang-option-active" : ""
                }`}
                onClick={() => handleLanguage("en")}
                disabled={pendingLang !== null}
              >
                {t("user_menu.lang_en")}
              </button>
            </div>
          </div>

          <div className="user-menu-divider" role="separator" />

          <button
            type="button"
            role="menuitem"
            className="user-menu-item"
            onClick={handleSettings}
          >
            <span className="user-menu-item-icon" aria-hidden="true">
              <SettingsIcon size={15} strokeWidth={2} />
            </span>
            {t("nav_settings")}
          </button>

          <button
            type="button"
            role="menuitem"
            className="user-menu-item user-menu-item-danger"
            onClick={handleLogout}
          >
            <span className="user-menu-item-icon" aria-hidden="true">
              <LogOut size={15} strokeWidth={2} />
            </span>
            {t("sign_out")}
          </button>
        </div>
      )}
    </div>
  );
}

