import { request } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD } from "./demoUsers";

/**
 * Sprint 29 Batch 29.5 — shared `apiAs` test helper.
 *
 * Builds an authenticated `APIRequestContext` against the backend
 * under test. Previously each spec inlined an identical 17-line
 * helper, which had two issues:
 *
 *   1. Code duplication across `sprint29_batch29_{2,3,4}_*.spec.ts`.
 *   2. Bulk regression runs hammer `/api/auth/token/` in quick
 *      succession and trip the auth-endpoint rate limiter (HTTP
 *      429). The bare `expect(status).toBe(200)` raised false
 *      failures that always passed after a cooldown — there was no
 *      retry. This helper retries up to 4 times on 429 with
 *      exponential backoff (500ms, 1s, 2s, 4s), and throws
 *      eagerly on any other non-200 status.
 *
 * The login context is disposed before the authenticated context
 * is returned, so callers only need to dispose what they receive.
 */
const API_BASE =
  process.env.PLAYWRIGHT_API_BASE_URL ?? "http://localhost:8000";

const BACKOFFS_MS = [500, 1_000, 2_000, 4_000];

export async function apiAs(
  email: string,
  password: string = DEMO_PASSWORD,
): Promise<APIRequestContext> {
  const loginCtx = await request.newContext({
    baseURL: API_BASE,
    ignoreHTTPSErrors: true,
  });
  try {
    let lastStatus = 0;
    let lastBodyText = "";
    for (let attempt = 0; attempt < BACKOFFS_MS.length; attempt += 1) {
      const tokenResponse = await loginCtx.post("/api/auth/token/", {
        data: { email, password },
      });
      lastStatus = tokenResponse.status();
      if (lastStatus === 200) {
        const body = (await tokenResponse.json()) as { access: string };
        return await request.newContext({
          baseURL: API_BASE,
          ignoreHTTPSErrors: true,
          extraHTTPHeaders: { Authorization: `Bearer ${body.access}` },
        });
      }
      if (lastStatus !== 429) {
        lastBodyText = await tokenResponse.text().catch(() => "");
        throw new Error(
          `apiAs(${email}) failed: HTTP ${lastStatus} ${lastBodyText}`,
        );
      }
      // 429 — back off and retry.
      const delay = BACKOFFS_MS[attempt];
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
    throw new Error(
      `apiAs(${email}) failed: HTTP ${lastStatus} after ${BACKOFFS_MS.length} attempts (rate-limit). Last body: ${lastBodyText}`,
    );
  } finally {
    await loginCtx.dispose();
  }
}
