import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";

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

export function getApiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data;

    if (typeof data === "string") return data;
    if (data?.detail) return String(data.detail);
    if (data?.code) return String(data.code);

    if (data && typeof data === "object") {
      const firstKey = Object.keys(data)[0];
      const firstValue = firstKey ? data[firstKey] : null;

      if (Array.isArray(firstValue)) {
        return String(firstValue[0]);
      }

      if (firstValue) {
        return String(firstValue);
      }
    }

    if (error.response?.status === 401) {
      return "Your session expired. Please sign in again.";
    }

    if (error.message) return error.message;
  }

  return "Unexpected error.";
}
