import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";

import i18n from "../i18n";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

const ACCESS_TOKEN_KEY = "accessToken";
const REFRESH_TOKEN_KEY = "refreshToken";

type RetryRequestConfig = InternalAxiosRequestConfig & {
  _retry?: boolean;
};

export const api = axios.create({
  baseURL: API_BASE_URL,
});

const refreshApi = axios.create({
  baseURL: API_BASE_URL,
});

let refreshPromise: Promise<string | null> | null = null;

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setAuthTokens(access: string, refresh?: string): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, access);

  if (refresh) {
    localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
  }
}

export function clearAuthTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  window.dispatchEvent(new Event("auth:logout"));
}

export async function logoutRefreshToken(refresh: string): Promise<void> {
  await refreshApi.post("/auth/logout/", { refresh });
}

function isAuthTokenUrl(url?: string): boolean {
  if (!url) return false;
  return url.includes("/auth/token/");
}

async function refreshAccessToken(): Promise<string | null> {
  const refresh = getRefreshToken();

  if (!refresh) {
    clearAuthTokens();
    return null;
  }

  if (!refreshPromise) {
    refreshPromise = refreshApi
      .post<{ access: string; refresh?: string }>("/auth/token/refresh/", {
        refresh,
      })
      .then((response) => {
        const newAccess = response.data.access;
        const newRefresh = response.data.refresh ?? refresh;

        setAuthTokens(newAccess, newRefresh);
        return newAccess;
      })
      .catch(() => {
        clearAuthTokens();
        return null;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }

  return refreshPromise;
}

api.interceptors.request.use((config) => {
  const token = getAccessToken();

  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetryRequestConfig | undefined;

    if (
      error.response?.status !== 401 ||
      !originalRequest ||
      originalRequest._retry ||
      isAuthTokenUrl(originalRequest.url)
    ) {
      return Promise.reject(error);
    }

    originalRequest._retry = true;

    const newAccess = await refreshAccessToken();

    if (!newAccess) {
      return Promise.reject(error);
    }

    originalRequest.headers.Authorization = `Bearer ${newAccess}`;
    return api(originalRequest);
  },
);

// Sprint 22: human-friendly fallbacks per HTTP status. DRF still wins
// when it returns a useful `detail` or field-error payload (we surface
// that verbatim — it is usually the most precise message). When the
// server only returns a status code, or when we never reached it, we
// emit a translated sentence instead of raw text like "Bad Request".
function statusFallback(status: number): string {
  if (status === 401) return i18n.t("api_error.session_expired");
  if (status === 403) return i18n.t("api_error.not_allowed");
  if (status === 404) return i18n.t("api_error.not_found");
  if (status === 429) return i18n.t("api_error.too_many_requests");
  if (status >= 500) return i18n.t("api_error.server_unavailable");
  if (status >= 400) return i18n.t("api_error.invalid_input");
  return i18n.t("api_error.unexpected");
}

export function getApiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data;
    const status = error.response?.status;

    // DRF-shaped payloads first. These are usually the most precise
    // message we can show ("Email already taken", "Invalid token", …)
    // so we surface them verbatim instead of a generic status sentence.
    // Sprint 28 Batch 1: but NEVER pass through HTML — Django's DEBUG=False
    // 500 page and the dev server's debug response both arrive as
    // `text/html`. Rendering that body in the UI's error banner leaks the
    // full debug page into the customer surface and confuses operators.
    // Detect an HTML prefix (whitespace-tolerant) and drop to the
    // status-aware fallback below.
    if (typeof data === "string" && data.trim().length > 0) {
      const trimmed = data.trimStart();
      const looksLikeHtml =
        trimmed.startsWith("<!DOCTYPE") ||
        trimmed.startsWith("<!doctype") ||
        trimmed.startsWith("<html") ||
        trimmed.startsWith("<HTML");
      if (!looksLikeHtml) return data;
      // Fall through to statusFallback(status) below.
    }
    if (data && typeof data === "object") {
      const record = data as Record<string, unknown>;
      if (typeof record.detail === "string" && record.detail.trim().length > 0) {
        return record.detail;
      }
      const firstKey = Object.keys(record)[0];
      const firstValue = firstKey ? record[firstKey] : null;
      if (Array.isArray(firstValue) && firstValue.length > 0) {
        return String(firstValue[0]);
      }
      if (typeof firstValue === "string" && firstValue.trim().length > 0) {
        return firstValue;
      }
    }

    // No useful body — fall back to a status-aware sentence. Better
    // than echoing "Network Error" or "Request failed with status 403".
    if (typeof status === "number") return statusFallback(status);

    // No response at all (network error / CORS / DNS).
    if (error.code === "ERR_NETWORK" || error.message === "Network Error") {
      return i18n.t("api_error.network");
    }
  }

  return i18n.t("api_error.unexpected");
}
