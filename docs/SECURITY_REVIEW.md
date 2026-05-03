# Security Review

## JWT storage strategy

Current frontend behavior:

- Access token is stored in `localStorage` as `accessToken`.
- Refresh token is stored in `localStorage` as `refreshToken`.
- API requests send the access token with the `Authorization: Bearer ...` header.
- Axios refresh logic uses `/api/auth/token/refresh/` when an access token expires.

Files reviewed:

- `frontend/src/auth/AuthContext.tsx`
- `frontend/src/api/client.ts`
- `backend/accounts/urls.py`
- `backend/accounts/views.py`
- `backend/config/settings.py`

## Risk

Storing JWTs in `localStorage` is simple and works for the current application, but it increases risk if an XSS vulnerability is introduced. JavaScript can read `localStorage`, so a successful XSS attack could steal both access and refresh tokens.

## Current mitigations

- Production Nginx security headers are enabled.
- `Permissions-Policy` disables camera, microphone, and geolocation by default.
- `X-Content-Type-Options` is enabled.
- `X-Frame-Options` is enabled.
- `Referrer-Policy` is enabled.
- API throttling is configured.
- Access token lifetime is limited.
- Role-based backend authorization and object scoping are enforced server-side.

## Production recommendation

Before a public launch, migrate refresh-token storage away from `localStorage`.

Recommended target:

- Store refresh token in an `HttpOnly`, `Secure`, `SameSite=Lax` or `SameSite=Strict` cookie.
- Keep access token short-lived.
- Prefer storing access token in memory rather than persistent browser storage.
- Add CSRF protection for cookie-based refresh/logout endpoints.
- Keep backend authorization checks as the source of truth.

## Decision

JWT storage strategy has been reviewed.

For private/internal testing, the current `localStorage` approach is acceptable with the existing mitigations.

For public production launch, cookie-based refresh token storage should be implemented before exposing the system to untrusted users.
