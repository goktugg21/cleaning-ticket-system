import { expect, test } from "@playwright/test";

import { DEMO_USERS } from "./fixtures/demoUsers";
import { loginAs } from "./fixtures/login";

/**
 * Sprint 17 — attachment role gating in the UI.
 *
 * The "Mark as internal" checkbox in the staged-attachment area is
 * staff-only on the frontend. Backend re-validates via
 * `TicketAttachmentSerializer.validate_is_hidden`, but the audit
 * still wants to confirm the UI gate so a customer-user cannot even
 * attempt the action by accident.
 *
 * We synthesise a tiny in-memory file via Playwright's `setInputFiles`
 * with a Buffer payload so the test does not need a checked-in
 * binary.
 */

const DEMO_TICKET_TITLE = "Pantry zeepdispenser";

async function openDemoTicket(page: import("@playwright/test").Page) {
  await page.waitForLoadState("networkidle");
  const row = page
    .locator(".data-table tbody tr", { hasText: DEMO_TICKET_TITLE })
    .first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  await row.locator("a.td-id").click();
  await page.waitForLoadState("networkidle");
}

async function stageDummyFile(page: import("@playwright/test").Page) {
  // The page renders <input type="file"> inside the .att-thumb-upload
  // label. setInputFiles accepts a buffer payload so we don't need
  // a fixture file on disk.
  const fileInput = page.locator('.att-thumb-upload input[type="file"]');
  await fileInput.setInputFiles({
    name: "audit-pixel.png",
    mimeType: "image/png",
    // 1x1 transparent PNG.
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
      "base64",
    ),
  });
  // The staged form only mounts after a file is selected; wait for it.
  await expect(page.locator(".att-thumb-staged")).toBeVisible({
    timeout: 10_000,
  });
}

test("Staff (company-admin) sees the 'internal only' checkbox on a staged attachment", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.companyAdmin);
  await openDemoTicket(page);
  await stageDummyFile(page);
  await expect(
    page.locator('.att-thumb-staged label.login-check input[type="checkbox"]'),
  ).toBeVisible({ timeout: 10_000 });
});

test("Customer-user (Amanda) does NOT see the 'internal only' checkbox", async ({
  page,
}) => {
  await loginAs(page, DEMO_USERS.customerB3);
  await openDemoTicket(page);
  await stageDummyFile(page);
  await expect(
    page.locator(".att-thumb-staged label.login-check"),
  ).toHaveCount(0);
});
