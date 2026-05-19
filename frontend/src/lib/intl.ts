/**
 * Sprint 28 Batch 15.1 — centralised intl helpers.
 *
 * ~12 ad-hoc `formatDate` implementations exist across pages and
 * each one re-derives the BCP-47 locale via
 *   `i18n.language === "nl" ? "nl-NL" : "en-US"`.
 * Pages did slightly different things (some pass undefined to
 * toLocaleDateString, some use Intl.DateTimeFormat directly, some
 * include the year, some don't). The result is inconsistent dates
 * across screens.
 *
 * This module is the one place dates, currencies, and numbers get
 * formatted. New code calls these helpers; the existing per-page
 * implementations stay until later batches migrate them — that work
 * is intentionally out of scope for Batch 15.1.
 *
 * Every helper:
 *   - accepts `string | Date | null | undefined`,
 *   - returns `"—"` for empty/invalid input,
 *   - catches any RangeError / TypeError from Intl and falls back
 *     to "—" rather than throwing into the React tree.
 */
import i18next from "i18next";
import { useTranslation } from "react-i18next";

const DASH = "—";

function resolveLocale(locale?: string, fallback?: string): string {
  if (locale && locale.length > 0) {
    return locale;
  }
  if (fallback && fallback.length > 0) {
    return fallback;
  }
  return localeCode();
}

function parseDate(value: string | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * Hook variant — returns the BCP-47 locale string matching the
 * currently-active i18n language. Use inside React components.
 */
export function useLocaleCode(): string {
  const { i18n } = useTranslation();
  return i18n.language === "nl" ? "nl-NL" : "en-US";
}

/**
 * Non-hook variant — for utility code that runs outside a component
 * (e.g. PDF export helpers, axios interceptors).
 */
export function localeCode(): string {
  return i18next.language === "nl" ? "nl-NL" : "en-US";
}

/**
 * "15 May 2026" — no time component. Empty/invalid input returns "—".
 */
export function formatDate(
  value: string | Date | null | undefined,
  locale?: string,
): string {
  const date = parseDate(value);
  if (!date) return DASH;
  try {
    return new Intl.DateTimeFormat(resolveLocale(locale), {
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(date);
  } catch {
    return DASH;
  }
}

/**
 * "15 May 2026, 17:49" — with time. Empty returns "—".
 */
export function formatDateTime(
  value: string | Date | null | undefined,
  locale?: string,
): string {
  const date = parseDate(value);
  if (!date) return DASH;
  try {
    return new Intl.DateTimeFormat(resolveLocale(locale), {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  } catch {
    return DASH;
  }
}

/**
 * "yesterday" / "in 3 days" — when the value is within ±30 days of
 * now. Otherwise falls back to the absolute date format. Empty
 * returns "—".
 */
export function formatRelative(
  value: string | Date | null | undefined,
  locale?: string,
): string {
  const date = parseDate(value);
  if (!date) return DASH;
  const resolved = resolveLocale(locale);
  const now = Date.now();
  const diffMs = date.getTime() - now;
  const diffDays = Math.round(diffMs / 86_400_000);

  if (Math.abs(diffDays) <= 30) {
    try {
      const rtf = new Intl.RelativeTimeFormat(resolved, { numeric: "auto" });
      const diffHours = Math.round(diffMs / 3_600_000);
      const diffMinutes = Math.round(diffMs / 60_000);
      if (Math.abs(diffMinutes) < 60) {
        return rtf.format(diffMinutes, "minute");
      }
      if (Math.abs(diffHours) < 24) {
        return rtf.format(diffHours, "hour");
      }
      return rtf.format(diffDays, "day");
    } catch {
      // Fall through to absolute formatting on RangeError etc.
    }
  }

  return formatDate(date, resolved);
}

export interface FormatMoneyOptions {
  locale?: string;
  currency?: string;
}

/**
 * "€ 1.470,15" (nl) or "€1,470.15" (en). Defaults to EUR. Accepts
 * decimal strings from the backend (Django Decimal serializer emits
 * strings like "1470.15") as well as numbers. Returns "—" on empty
 * or non-parseable input.
 */
export function formatMoney(
  value: string | number | null | undefined,
  options: FormatMoneyOptions = {},
): string {
  if (value === null || value === undefined || value === "") {
    return DASH;
  }
  const numeric =
    typeof value === "number" ? value : Number.parseFloat(String(value));
  if (!Number.isFinite(numeric)) {
    return DASH;
  }
  try {
    return new Intl.NumberFormat(resolveLocale(options.locale), {
      style: "currency",
      currency: options.currency ?? "EUR",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(numeric);
  } catch {
    return DASH;
  }
}

export interface FormatNumberOptions {
  locale?: string;
  minimumFractionDigits?: number;
  maximumFractionDigits?: number;
}

/**
 * "1.234,5" (nl) or "1,234.5" (en). For non-currency numbers
 * (square meters, hours, line item quantities). Callers append the
 * unit suffix.
 */
export function formatNumber(
  value: string | number | null | undefined,
  options: FormatNumberOptions = {},
): string {
  if (value === null || value === undefined || value === "") {
    return DASH;
  }
  const numeric =
    typeof value === "number" ? value : Number.parseFloat(String(value));
  if (!Number.isFinite(numeric)) {
    return DASH;
  }
  try {
    return new Intl.NumberFormat(resolveLocale(options.locale), {
      minimumFractionDigits: options.minimumFractionDigits,
      maximumFractionDigits: options.maximumFractionDigits,
    }).format(numeric);
  } catch {
    return DASH;
  }
}

