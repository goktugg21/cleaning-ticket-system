import { chromium, request as pwRequest } from "playwright";

const FRONTEND = process.env.FRONTEND_URL ?? "http://localhost:5173";
const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";
const ACCOUNTS = {
  super: { email: "smoke-super@example.com", password: "Test12345!" },
  companyAdmin: { email: "companyadmin@example.com", password: "Test12345!" },
  manager: { email: "manager@example.com", password: "Test12345!" },
  customer: { email: "customer@example.com", password: "Test12345!" },
};

const PASS = "PASS";
const FAIL = "FAIL";
const SKIP = "SKIP";
const results = [];
const consoleErrors = [];

function record(group, item, status, note = "") {
  results.push({ group, item, status, note });
  const tag = status === PASS ? "✓" : status === FAIL ? "✗" : "~";
  console.log(`${tag} [${group}] ${item}${note ? " — " + note : ""}`);
}

function attachConsoleSinks(page, role) {
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push({ role, url: page.url(), text: msg.text() });
    }
  });
  page.on("pageerror", (err) => {
    consoleErrors.push({ role, url: page.url(), text: `pageerror: ${err.message}` });
  });
}

async function login(page, account) {
  await page.goto(`${FRONTEND}/login`, { waitUntil: "domcontentloaded" });
  await page.locator("#login-email").fill(account.email);
  await page.locator("#login-password").fill(account.password);
  await Promise.all([
    page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 15000 }),
    page.locator("button.login-submit").click(),
  ]);
  // Wait for AppShell to render after me is loaded.
  await page.waitForSelector(".sidebar-nav", { timeout: 10000 });
}

async function expectAdminSidebar(page, group, shouldShow) {
  // Give AuthContext a beat to populate me before we assert sidebar contents.
  if (shouldShow) {
    await page.waitForSelector('a.nav-item[href="/admin/users"]', { state: "visible", timeout: 5000 })
      .catch(() => {});
  } else {
    await page.waitForTimeout(500);
  }
  const usersLink = page.locator('a.nav-item[href="/admin/users"]');
  const invitesLink = page.locator('a.nav-item[href="/admin/invitations"]');
  const isVisibleU = await usersLink.isVisible().catch(() => false);
  const isVisibleI = await invitesLink.isVisible().catch(() => false);
  const ok = (isVisibleU === shouldShow) && (isVisibleI === shouldShow);
  record(group, `Sidebar Users+Invitations ${shouldShow ? "visible" : "hidden"}`, ok ? PASS : FAIL,
    `users=${isVisibleU} invitations=${isVisibleI}`);
}

// Helper: get an authed token via API for backend cleanup actions only.
async function adminApiContext(account) {
  const ctx = await pwRequest.newContext({ baseURL: BACKEND });
  const tokenResp = await ctx.post("/api/auth/token/", {
    data: { email: account.email, password: account.password },
  });
  const { access } = await tokenResp.json();
  await ctx.dispose();
  return await pwRequest.newContext({
    baseURL: BACKEND,
    extraHTTPHeaders: { authorization: `Bearer ${access}` },
  });
}

async function runSuperAdmin(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await ctx.newPage();
  attachConsoleSinks(page, "SUPER_ADMIN");
  const G = "SUPER_ADMIN";

  await login(page, ACCOUNTS.super);
  record(G, "Login", PASS);

  await expectAdminSidebar(page, G, true);

  // 3-5: Users list + role filter
  await page.goto(`${FRONTEND}/admin/users`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("table.data-table tbody tr", { timeout: 10000 });
  const rowsBefore = await page.locator("table.data-table tbody tr").count();
  record(G, "Users list loads", rowsBefore > 0 ? PASS : FAIL, `${rowsBefore} rows`);

  await page.getByRole("button", { name: /^Building manager$/, pressed: false }).click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(300);
  const roleCells = await page.locator("table.data-table tbody tr td:nth-child(3)").allTextContents();
  const allBM = roleCells.length > 0 && roleCells.every((t) => /Building manager/i.test(t));
  record(G, "Role filter (Building manager) restricts list", allBM ? PASS : FAIL,
    `${roleCells.length} rows; roles=${[...new Set(roleCells)].join("|")}`);
  await page.getByRole("button", { name: /^Clear$/ }).click().catch(() => {});

  // 6-8: Open detail for ANOTHER user, then own user
  await page.goto(`${FRONTEND}/admin/users/3`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("input#user-email", { timeout: 10000 });
  const otherEmail = await page.locator("input#user-email").inputValue();
  record(G, "Open /admin/users/:id (other user)", /manager@example/.test(otherEmail) ? PASS : FAIL, `email=${otherEmail}`);
  const otherRoleDisabled = await page.locator("select#user-role").isDisabled();
  record(G, "Other user role select enabled (super admin)", otherRoleDisabled ? FAIL : PASS);

  await page.goto(`${FRONTEND}/admin/users/13`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("input#user-email", { timeout: 10000 });
  const selfRoleDisabled = await page.locator("select#user-role").isDisabled();
  record(G, "Own role dropdown disabled when opening self", selfRoleDisabled ? PASS : FAIL);

  // 9-11: Deactivate user 3, confirm appears in inactive view, reactivate
  await page.goto(`${FRONTEND}/admin/users/3`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("button.btn-ghost:has-text('Deactivate')", { timeout: 10000 });
  await page.locator("button.btn-ghost:has-text('Deactivate')").first().click();
  await page.waitForTimeout(300);
  await page.locator("dialog[open] button:has-text('Deactivate')").click();
  await page.waitForURL(/\/admin\/users(?:\?|$)/, { timeout: 10000 });
  record(G, "Deactivate other user", PASS);

  // Inactive view via Status filter
  await page.locator("select.filter-control").first().selectOption("false");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(400);
  const inactiveRowsText = await page.locator("table.data-table tbody tr").allTextContents();
  const inactiveHit = inactiveRowsText.some((t) => /manager@example\.com/.test(t));
  record(G, "Deactivated user appears in inactive view", inactiveHit ? PASS : FAIL);

  // Try to reactivate via UI: open detail page. UserFormPage.getUser uses
  // `/api/users/{id}/` which is filtered to is_active=True; deactivated user
  // returns 404, so the Reactivate button never shows. Record observed
  // behavior, then reactivate via the API to restore state.
  await page.goto(`${FRONTEND}/admin/users/3`, { waitUntil: "domcontentloaded" });
  const reactivateBtn = page.locator('button.btn-primary.btn-sm:has-text("Reactivate")').first();
  let canReactivateUI = false;
  try {
    await reactivateBtn.waitFor({ state: "visible", timeout: 4000 });
    canReactivateUI = true;
    await reactivateBtn.click();
    await page.waitForTimeout(300);
    await page.locator("dialog[open] button:has-text('Reactivate')").click();
    await page.waitForURL(/\/admin\/users(?:\?|$)/, { timeout: 10000 });
  } catch {
    canReactivateUI = false;
  }
  record(G, "Reactivate user from /admin/users/:id (UI)",
    canReactivateUI ? PASS : FAIL,
    canReactivateUI
      ? ""
      : "BUG: GET /api/users/3/ returns 404 for deactivated user, so Reactivate button never renders. Reactivated via API to restore state.");
  if (!canReactivateUI) {
    const apiCtx = await adminApiContext(ACCOUNTS.super);
    const r = await apiCtx.post("/api/users/3/reactivate/");
    if (!r.ok()) {
      record(G, "Cleanup: reactivate user 3 via API", FAIL, `status=${r.status()}`);
    }
    await apiCtx.dispose();
  }

  // 12-16: Invitations
  await page.goto(`${FRONTEND}/admin/invitations`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("input#invite-email", { timeout: 10000 });

  // Field-level validation via the role-specific scope requirement.
  await page.locator("input#invite-email").fill(`smoke-validate-${Date.now()}@example.com`);
  await page.locator("select#invite-role").selectOption("BUILDING_MANAGER");
  await page.waitForTimeout(200);
  // Pick a company so the buildings list loads (we still won't pick any building).
  await page.locator("select#invite-company").selectOption({ label: "Demo Cleaning Company" });
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: /Send invitation/ }).click();
  await page.waitForTimeout(300);
  const buildingFieldErr = await page.locator(".alert-error").filter({ hasText: /at least one building/i }).count();
  record("UI", "Inline field error appears next to invalid invitation field", buildingFieldErr > 0 ? PASS : FAIL);

  // Recover: send a valid invitation to confirm success banner.
  const inviteEmail = `smoke-invitee-${Date.now()}@example.com`;
  await page.locator("input#invite-email").fill(inviteEmail);
  // Pick first available building.
  const firstBuildingBtn = page.locator('section.card div.field button[aria-pressed]').first();
  await firstBuildingBtn.click();
  await page.getByRole("button", { name: /Send invitation/ }).click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(700);

  const successBanner = await page.locator(".alert-info[role='status']").count();
  record("UI", "Success banner appears on valid save", successBanner > 0 ? PASS : FAIL);

  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
  const successAfterReload = await page.locator(".alert-info[role='status']").count();
  record("UI", "Success banner does not reappear after reload", successAfterReload === 0 ? PASS : FAIL);

  // Confirm invitation appears as PENDING (post-redesign: status-pill
  // replaces cell-tag; PENDING is the default tab, no extra click needed).
  const pendingHit = await page.locator(`tr:has-text("${inviteEmail}")`).first()
    .locator(".status-pill--pending").count();
  record(G, "Invitation appears as PENDING", pendingHit > 0 ? PASS : FAIL);

  // Revoke (post-redesign: the Revoke action is a translated link-action,
  // so target by class instead of text).
  const revokeRow = page.locator(`tr:has-text("${inviteEmail}")`).first();
  await revokeRow.locator('.link-action--danger').click();
  await page.waitForTimeout(300);
  await page.locator("dialog[open] button:has-text('Revoke')").click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);

  // After revoke the row leaves the PENDING tab — REVOKED entries surface
  // only under the "All" tab in the redesigned page. Click that tab and
  // verify the row now wears the revoked status pill.
  await page.locator('[data-testid="status-tab-all"]').click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(400);
  const revokedHit = await page.locator(`tr:has-text("${inviteEmail}")`).first()
    .locator(".status-pill--revoked").count();
  record(G, "Invitation becomes REVOKED", revokedHit > 0 ? PASS : FAIL);

  // 17-20: /admin/companies/:id Admins section
  await page.goto(`${FRONTEND}/admin/companies/1`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("select#add-company-admin", { timeout: 10000 });
  // Wait until the add select has at least one option (excluding placeholder).
  await page.waitForFunction(
    () => {
      const sel = document.querySelector("#add-company-admin");
      return sel && sel.querySelectorAll("option").length > 1;
    },
    { timeout: 10000 },
  );
  const existingMembersCount = await page.locator("section.card:has-text('Admins') table tbody tr").count();

  let pickedCompanyAdminEmail = null;
  const opts = await page.locator("select#add-company-admin option").all();
  for (const o of opts) {
    const t = ((await o.textContent()) || "").trim();
    if (/^companyadmin2@example\.com/.test(t) || /^notification-company-admin/.test(t)) {
      const value = await o.getAttribute("value");
      await page.locator("select#add-company-admin").selectOption(value);
      pickedCompanyAdminEmail = t.split(" ")[0];
      break;
    }
  }
  await page.locator("section.card:has-text('Admins') button:has-text('Add')").click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
  const newMembersCount = await page.locator("section.card:has-text('Admins') table tbody tr").count();
  record(G, "Add company admin refreshes list immediately",
    newMembersCount === existingMembersCount + 1 ? PASS : FAIL,
    `${existingMembersCount} -> ${newMembersCount}; picked=${pickedCompanyAdminEmail}`);

  // Remove
  const newRow = page.locator(`section.card:has-text('Admins') tr:has-text("${pickedCompanyAdminEmail}")`).first();
  await newRow.locator('button:has-text("Remove")').click();
  await page.waitForTimeout(300);
  await page.locator("dialog[open] button:has-text('Remove')").click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(400);
  const afterRemoveCount = await page.locator("section.card:has-text('Admins') table tbody tr").count();
  record(G, "Remove company admin refreshes list",
    afterRemoveCount === existingMembersCount ? PASS : FAIL,
    `${newMembersCount} -> ${afterRemoveCount}`);

  // 21-24: /admin/buildings/:id Managers section
  await page.goto(`${FRONTEND}/admin/buildings/1`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("section.card:has-text('Managers')", { timeout: 10000 });
  await page.waitForTimeout(500);
  const bMembersBefore = await page.locator("section.card:has-text('Managers') table tbody tr").count();
  let pickedManagerEmail = null;
  const bOpts = await page.locator("section.card:has-text('Managers') select option").all();
  for (const o of bOpts) {
    const t = ((await o.textContent()) || "").trim();
    if (/^manager2@example\.com/.test(t) || /^assignment-other-manager@example\.com/.test(t)) {
      const value = await o.getAttribute("value");
      await page.locator("section.card:has-text('Managers') select").selectOption(value);
      pickedManagerEmail = t.split(" ")[0];
      break;
    }
  }
  await page.locator("section.card:has-text('Managers') button:has-text('Add')").click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
  const bMembersAfterAdd = await page.locator("section.card:has-text('Managers') table tbody tr").count();
  record(G, "Add building manager refreshes list",
    bMembersAfterAdd === bMembersBefore + 1 ? PASS : FAIL,
    `${bMembersBefore} -> ${bMembersAfterAdd}; picked=${pickedManagerEmail}`);

  const bAddedRow = page.locator(`section.card:has-text('Managers') tr:has-text("${pickedManagerEmail}")`).first();
  await bAddedRow.locator('button:has-text("Remove")').click();
  await page.waitForTimeout(300);
  await page.locator("dialog[open] button:has-text('Remove')").click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(400);
  const bMembersAfterRm = await page.locator("section.card:has-text('Managers') table tbody tr").count();
  record(G, "Remove building manager refreshes list",
    bMembersAfterRm === bMembersBefore ? PASS : FAIL,
    `${bMembersAfterAdd} -> ${bMembersAfterRm}`);

  // 25-28: /admin/customers/:id Users section
  await page.goto(`${FRONTEND}/admin/customers/1`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("section.card:has-text('Users')", { timeout: 10000 });
  await page.waitForTimeout(500);
  const cMembersBefore = await page.locator("section.card:has-text('Users') table tbody tr").count();
  let pickedCustomerUserEmail = null;
  const cOpts = await page.locator("section.card:has-text('Users') select option").all();
  for (const o of cOpts) {
    const t = ((await o.textContent()) || "").trim();
    if (/^customer2@example\.com/.test(t) || /^notification-customer-user@example\.com/.test(t)) {
      const value = await o.getAttribute("value");
      await page.locator("section.card:has-text('Users') select").selectOption(value);
      pickedCustomerUserEmail = t.split(" ")[0];
      break;
    }
  }
  await page.locator("section.card:has-text('Users') button:has-text('Add')").click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
  const cMembersAfterAdd = await page.locator("section.card:has-text('Users') table tbody tr").count();
  record(G, "Add customer user refreshes list",
    cMembersAfterAdd === cMembersBefore + 1 ? PASS : FAIL,
    `${cMembersBefore} -> ${cMembersAfterAdd}; picked=${pickedCustomerUserEmail}`);

  const cAddedRow = page.locator(`section.card:has-text('Users') tr:has-text("${pickedCustomerUserEmail}")`).first();
  await cAddedRow.locator('button:has-text("Remove")').click();
  await page.waitForTimeout(300);
  await page.locator("dialog[open] button:has-text('Remove')").click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(400);
  const cMembersAfterRm = await page.locator("section.card:has-text('Users') table tbody tr").count();
  record(G, "Remove customer user refreshes list",
    cMembersAfterRm === cMembersBefore ? PASS : FAIL,
    `${cMembersAfterAdd} -> ${cMembersAfterRm}`);

  // ---- Dialog cancel/escape/confirm ----
  await page.goto(`${FRONTEND}/admin/users/3`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("button.btn-ghost:has-text('Deactivate')", { timeout: 10000 });
  await page.locator("button.btn-ghost:has-text('Deactivate')").first().click();
  await page.waitForTimeout(200);
  await page.locator("dialog[open] button:has-text('Cancel')").click();
  await page.waitForTimeout(200);
  let dialogOpen = await page.locator("dialog[open]").count();
  record("UI", "Cancel closes deactivate dialog", dialogOpen === 0 ? PASS : FAIL);

  await page.locator("button.btn-ghost:has-text('Deactivate')").first().click();
  await page.waitForTimeout(200);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  dialogOpen = await page.locator("dialog[open]").count();
  record("UI", "Escape closes deactivate dialog", dialogOpen === 0 ? PASS : FAIL);

  // Confirm action: deactivate, then API-restore.
  await page.locator("button.btn-ghost:has-text('Deactivate')").first().click();
  await page.waitForTimeout(200);
  await page.locator("dialog[open] button:has-text('Deactivate')").click();
  await page.waitForURL(/\/admin\/users(?:\?|$)/, { timeout: 10000 });
  record("UI", "Confirm action works", PASS);
  // Restore via API.
  const apiCtx2 = await adminApiContext(ACCOUNTS.super);
  await apiCtx2.post("/api/users/3/reactivate/");
  await apiCtx2.dispose();

  // ---- Reports section ----
  await runReportsForSuperAdmin(page);

  await ctx.close();
}

async function runCompanyAdmin(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await ctx.newPage();
  attachConsoleSinks(page, "COMPANY_ADMIN");
  const G = "COMPANY_ADMIN";

  await login(page, ACCOUNTS.companyAdmin);
  record(G, "Login", PASS);

  await expectAdminSidebar(page, G, true);

  await page.goto(`${FRONTEND}/admin/users`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("table.data-table tbody tr", { timeout: 10000 });
  const roleCells = await page.locator("table.data-table tbody tr td:nth-child(3)").allTextContents();
  const hasSuper = roleCells.some((t) => /Super admin/i.test(t));
  record(G, "Users list excludes SUPER_ADMIN", hasSuper ? FAIL : PASS, `roles=${[...new Set(roleCells)].join("|")}`);

  const superChip = await page.locator('div.field button:has-text("Super admin")').count();
  record(G, "Role filter does not expose SUPER_ADMIN", superChip === 0 ? PASS : FAIL);

  await page.goto(`${FRONTEND}/admin/invitations`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("select#invite-role", { timeout: 10000 });
  const inviteRoleOpts = await page.locator("select#invite-role option").allInnerTexts();
  record(G, "Invitation role does not include SUPER_ADMIN",
    inviteRoleOpts.some((t) => /Super admin/i.test(t)) ? FAIL : PASS,
    `options=${inviteRoleOpts.join(",")}`);

  // Manager (id 3) is in same company; can company_admin promote to SUPER_ADMIN?
  await page.goto(`${FRONTEND}/admin/users/3`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("select#user-role", { timeout: 10000 });
  const opts = await page.locator("select#user-role option").allInnerTexts();
  record(G, "Role select on manager does not offer SUPER_ADMIN",
    opts.some((t) => /Super admin/i.test(t)) ? FAIL : PASS,
    `options=${opts.join(",")}`);

  // Direct URL to other-company entities — expect clean denial (404 banner or empty).
  for (const [path, label] of [
    ["/admin/companies/2", "Other company detail blocked cleanly"],
    ["/admin/buildings/2", "Other building detail blocked cleanly"],
    ["/admin/customers/2", "Other customer detail blocked cleanly"],
  ]) {
    await page.goto(`${FRONTEND}${path}`, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(700);
    const errBanners = await page.locator(".alert-error").count();
    const bodyText = await page.locator("body").innerText();
    const cleanlyDenied = errBanners > 0 || /not found|geen|forbidden|niet/i.test(bodyText);
    // Must NOT show a populated form (no name input value).
    const nameInputs = await page.locator("form.card input").first().inputValue().catch(() => "");
    const noLeak = nameInputs === "" || /^\s*$/.test(nameInputs);
    record(G, label, cleanlyDenied && noLeak ? PASS : FAIL,
      `errBanners=${errBanners} formInputValue="${nameInputs}"`);
  }

  // Manage own-company building: edit and save name unchanged.
  await page.goto(`${FRONTEND}/admin/buildings/1`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("form.card input", { timeout: 10000 });
  // Pick the input with id="building-name"; fall back to first.
  const bnameInput = page.locator("input#building-name");
  if (await bnameInput.count() === 0) {
    record(G, "Edit own-company building succeeds", FAIL, "no #building-name input");
  } else {
    const original = await bnameInput.inputValue();
    await bnameInput.fill(original);
    await page.locator("form.card button[type='submit']").click();
    await page.waitForTimeout(900);
    const savedAlert = await page.locator(".alert-info[role='status']").count();
    record(G, "Edit own-company building succeeds", savedAlert > 0 ? PASS : FAIL,
      `original="${original}" alerts=${savedAlert}`);
  }

  // ---- Reports section ----
  await runReportsForCompanyAdmin(page);

  await ctx.close();
}

async function runNonStaff(browser, account, label) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await ctx.newPage();
  attachConsoleSinks(page, label);
  const G = label;

  await login(page, account);
  record(G, "Login", PASS);

  await expectAdminSidebar(page, G, false);

  await page.goto(`${FRONTEND}/admin/users`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(700);
  const url = page.url();
  const onDashboard = !/\/admin/.test(new URL(url).pathname);
  record(G, "Direct /admin/users redirects to dashboard", onDashboard ? PASS : FAIL, `url=${url}`);

  // Language-agnostic: select by data-testid instead of the translated text.
  // Dashboard renders the banner with data-testid="admin-required-banner"
  // when it sees ?admin_required=ok, regardless of the active language.
  const hasBanner =
    (await page.locator('[data-testid="admin-required-banner"]').count()) > 0;
  record(G, "Admin-required banner is shown", hasBanner ? PASS : FAIL);

  // Reports-section assertions for the non-staff roles.
  if (label === "BUILDING_MANAGER") {
    await runReportsForBuildingManager(page, G);
  } else if (label === "CUSTOMER_USER") {
    await runReportsForCustomerUser(page, G);
  }

  await ctx.close();
}

// ---- /reports coverage ------------------------------------------------

// i18n B3: chart cards identified by data-testid="chart-card-<slug>" so
// assertions stay language-agnostic. The slugs match the order the charts
// render on /reports; CHART_CARD_COUNT preserves the previous semantic.
const CHART_SLUGS = [
  "status-distribution",
  "tickets-over-time",
  "manager-throughput",
  "age-buckets",
  "sla-distribution",
  "sla-breach-rate-over-time",
];
const CHART_CARD_COUNT = CHART_SLUGS.length;

// Prefix selector picks every per-chart testid in one shot.
const CHART_CARD_SELECTOR = "[data-testid^='chart-card-']";

async function waitForReportsSettled(page) {
  // Wait until each chart card has a chart svg OR an alert-error OR a
  // [data-testid="chart-empty"] node — all three are language-agnostic
  // markers that the underlying useReport call resolved.
  await page.waitForFunction(
    ({ selector, expectedCount }) => {
      const cards = Array.from(document.querySelectorAll(selector));
      if (cards.length !== expectedCount) return false;
      return cards.every((card) =>
        card.querySelector("svg") ||
        card.querySelector(".alert-error") ||
        card.querySelector('[data-testid="chart-empty"]'),
      );
    },
    { selector: CHART_CARD_SELECTOR, expectedCount: CHART_CARD_COUNT },
    { timeout: 15000 },
  );
}

async function assertChartCardsPresent(page, group) {
  await page.goto(`${FRONTEND}/reports`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="reports-page-title"]', {
    timeout: 10000,
  });
  await waitForReportsSettled(page);
  const slugsRendered = await page
    .locator(CHART_CARD_SELECTOR)
    .evaluateAll((els) =>
      els.map((el) => (el.getAttribute("data-testid") || "").replace(/^chart-card-/, "")),
    );
  const allPresent = CHART_SLUGS.every((s) => slugsRendered.includes(s));
  record(
    group,
    `/reports renders ${CHART_CARD_COUNT} chart cards`,
    slugsRendered.length === CHART_CARD_COUNT && allPresent ? PASS : FAIL,
    `slugs=${slugsRendered.join("|")}`,
  );
}

async function runReportsForSuperAdmin(page) {
  const G = "SUPER_ADMIN";

  // 1. Renders all chart cards.
  await assertChartCardsPresent(page, G);

  // 2. No inline errors on any chart card; each card has svg or empty-state.
  const errorCount = await page
    .locator(`${CHART_CARD_SELECTOR} .alert-error`)
    .count();
  const cardsWithContent = await page.evaluate((selector) => {
    const cards = Array.from(document.querySelectorAll(selector));
    return cards.filter(
      (card) =>
        card.querySelector("svg") ||
        Array.from(card.querySelectorAll(".muted.small")).some((el) =>
          /no (tickets|managers|open tickets) /i.test(el.textContent || ""),
        ),
    ).length;
  }, CHART_CARD_SELECTOR);
  record(
    G,
    "All charts render without inline errors",
    errorCount === 0 && cardsWithContent === CHART_CARD_COUNT ? PASS : FAIL,
    `errors=${errorCount} contentCards=${cardsWithContent}`,
  );

  // 2b. SLA distribution chart specifically renders without inline error.
  const slaDistCard = page.locator('[data-testid="chart-card-sla-distribution"]');
  const slaDistVisible = (await slaDistCard.count()) === 1;
  const slaDistError = (await slaDistCard.locator(".alert-error").count()) > 0;
  record(
    G,
    "SLA distribution chart renders without inline error",
    slaDistVisible && !slaDistError ? PASS : FAIL,
    `visible=${slaDistVisible} hasError=${slaDistError}`,
  );

  // 2c. SLA breach rate chart specifically renders without inline error.
  const slaBreachCard = page.locator(
    '[data-testid="chart-card-sla-breach-rate-over-time"]',
  );
  const slaBreachVisible = (await slaBreachCard.count()) === 1;
  const slaBreachError = (await slaBreachCard.locator(".alert-error").count()) > 0;
  record(
    G,
    "SLA breach rate chart renders without inline error",
    slaBreachVisible && !slaBreachError ? PASS : FAIL,
    `visible=${slaBreachVisible} hasError=${slaBreachError}`,
  );

  // 3. Default range preset is "Last 30 days" and visually active.
  const last30Pressed = await page
    .locator('[data-testid="range-preset-last_30"]')
    .getAttribute("aria-pressed");
  const last7Pressed = await page
    .locator('[data-testid="range-preset-last_7"]')
    .getAttribute("aria-pressed");
  const last90Pressed = await page
    .locator('[data-testid="range-preset-last_90"]')
    .getAttribute("aria-pressed");
  record(
    G,
    'Default range preset is "Last 30 days"',
    last30Pressed === "true" && last7Pressed === "false" && last90Pressed === "false"
      ? PASS
      : FAIL,
    `last30=${last30Pressed} last7=${last7Pressed} last90=${last90Pressed}`,
  );

  // 4. Click "Last 7 days" updates ?from= and ?to= URL params.
  await page.locator('[data-testid="range-preset-last_7"]').click();
  await page.waitForURL(/[?&]from=\d{4}-\d{2}-\d{2}.*[?&]to=\d{4}-\d{2}-\d{2}/, {
    timeout: 5000,
  });
  const url = new URL(page.url());
  const fromIso = url.searchParams.get("from");
  const toIso = url.searchParams.get("to");
  const fromMs = Date.parse(`${fromIso}T00:00:00Z`);
  const toMs = Date.parse(`${toIso}T00:00:00Z`);
  const todayMs = Date.parse(`${new Date().toISOString().slice(0, 10)}T00:00:00Z`);
  const spanDays = Math.round((toMs - fromMs) / 86400000);
  // Allow ±1 day tolerance for midnight rollover during the run.
  const spanOk = spanDays >= 5 && spanDays <= 7;
  const toOk = Math.abs(toMs - todayMs) <= 86400000;
  record(
    G,
    'Clicking "Last 7 days" sets ?from= and ?to=',
    spanOk && toOk ? PASS : FAIL,
    `from=${fromIso} to=${toIso} span=${spanDays}d`,
  );
  await waitForReportsSettled(page);

  // 5. Selecting a specific company updates ?company= and reveals building dropdown.
  const companySelect = page.locator('[data-testid="filter-company"]');
  // Pick the second option (first is "All companies").
  const optionValues = await companySelect.locator("option").evaluateAll((els) =>
    els.map((el) => el.getAttribute("value")),
  );
  const firstSpecificValue = optionValues.find((v) => v && v !== "");
  if (!firstSpecificValue) {
    record(G, "Selecting a company updates ?company=", FAIL, "no company options found");
  } else {
    await companySelect.selectOption(firstSpecificValue);
    await page.waitForURL(new RegExp(`[?&]company=${firstSpecificValue}\\b`), {
      timeout: 5000,
    });
    await page.waitForTimeout(300);
    const buildingSelectVisible = await page
      .locator('[data-testid="filter-building"]')
      .isVisible()
      .catch(() => false);
    record(
      G,
      "Selecting a company updates ?company= and reveals building dropdown",
      buildingSelectVisible ? PASS : FAIL,
      `company=${firstSpecificValue} buildingDropdown=${buildingSelectVisible}`,
    );
  }
  await waitForReportsSettled(page);

  // 6. Refresh button is present and clickable without crash.
  const refreshBtn = page.locator('[data-testid="refresh-reports"]');
  const refreshVisible = await refreshBtn.isVisible().catch(() => false);
  await refreshBtn.click().catch(() => {});
  await page.waitForTimeout(400);
  await waitForReportsSettled(page);
  const stillRenderedCount = await page.locator(CHART_CARD_SELECTOR).count();
  const stillRendered = stillRenderedCount === CHART_CARD_COUNT;
  record(
    G,
    "Refresh button present and click does not crash",
    refreshVisible && stillRendered ? PASS : FAIL,
    `visible=${refreshVisible} cards=${stillRendered ? CHART_CARD_COUNT : "missing"}`,
  );
}

async function runReportsForCompanyAdmin(page) {
  const G = "COMPANY_ADMIN";

  // 7. /reports renders for COMPANY_ADMIN.
  await assertChartCardsPresent(page, G);

  // 8. Sidebar shows Reports link for COMPANY_ADMIN.
  const sidebarLink = page.locator('aside.sidebar a.nav-item[href="/reports"]');
  const sidebarVisible = await sidebarLink.isVisible().catch(() => false);
  record(
    G,
    "Sidebar shows Reports link",
    sidebarVisible ? PASS : FAIL,
    `visible=${sidebarVisible}`,
  );

  // 9. Cross-tenant URL probe: ?company=<other> => inline errors on all cards.
  // Other company id is 2 in the fixture (matches the existing other-tenant
  // probes in this script). Implicitly verifies the SLA cards' error path too.
  await page.goto(`${FRONTEND}/reports?company=2`, { waitUntil: "domcontentloaded" });
  await waitForReportsSettled(page);
  const errBanners = await page
    .locator(`${CHART_CARD_SELECTOR} .alert-error`)
    .count();
  // One banner per chart card.
  record(
    G,
    "Cross-tenant /reports?company= shows inline errors on all chart cards",
    errBanners === CHART_CARD_COUNT ? PASS : FAIL,
    `errBanners=${errBanners}`,
  );
}

async function runReportsForBuildingManager(page, G) {
  // 10. /reports renders for BUILDING_MANAGER.
  await assertChartCardsPresent(page, G);

  // 11. Building dropdown auto-selects + is disabled when only one assignment.
  const buildingSelect = page.locator('[data-testid="filter-building"]');
  // Wait for both: a non-empty value AND disabled attribute.
  let autoSelectOk = false;
  try {
    await page.waitForFunction(
      () => {
        const sel = document.querySelector('[data-testid="filter-building"]');
        if (!sel) return false;
        const value = sel.value;
        const disabled = sel.disabled;
        return value !== "" && disabled;
      },
      { timeout: 5000 },
    );
    autoSelectOk = true;
  } catch {
    autoSelectOk = false;
  }
  const value = await buildingSelect.inputValue().catch(() => "");
  const disabled = await buildingSelect.isDisabled().catch(() => false);
  record(
    G,
    "Building dropdown auto-selects sole assignment and is disabled",
    autoSelectOk && value !== "" && disabled ? PASS : FAIL,
    `value=${value} disabled=${disabled}`,
  );

  // 12. Sidebar shows Reports link for BUILDING_MANAGER.
  const sidebarLink = page.locator('aside.sidebar a.nav-item[href="/reports"]');
  const sidebarVisible = await sidebarLink.isVisible().catch(() => false);
  record(
    G,
    "Sidebar shows Reports link",
    sidebarVisible ? PASS : FAIL,
    `visible=${sidebarVisible}`,
  );
}

async function runReportsForCustomerUser(page, G) {
  // 13. Sidebar does NOT show Reports link for CUSTOMER_USER.
  const sidebarLink = page.locator('aside.sidebar a.nav-item[href="/reports"]');
  const sidebarCount = await sidebarLink.count();
  record(
    G,
    "Sidebar does not show Reports link",
    sidebarCount === 0 ? PASS : FAIL,
    `count=${sidebarCount}`,
  );

  // 14. Direct navigation to /reports redirects to /.
  await page.goto(`${FRONTEND}/reports`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
  const url = new URL(page.url());
  const onDashboard = url.pathname === "/" || url.pathname === "";
  // Language-agnostic: check chart cards by testid rather than the (now
  // translated) chart title text.
  const noChartCards = (await page.locator(CHART_CARD_SELECTOR).count()) === 0;
  record(
    G,
    "Direct /reports redirects to /",
    onDashboard && noChartCards ? PASS : FAIL,
    `url=${url.pathname} chartCards=${!noChartCards}`,
  );
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    await runSuperAdmin(browser);
    await runCompanyAdmin(browser);
    await runNonStaff(browser, ACCOUNTS.manager, "BUILDING_MANAGER");
    await runNonStaff(browser, ACCOUNTS.customer, "CUSTOMER_USER");
  } catch (err) {
    console.log("FATAL:", err.stack || err.message);
    process.exitCode = 2;
  } finally {
    await browser.close();
  }

  console.log("\n===== SMOKE RESULTS =====");
  for (const r of results) {
    console.log(`${r.status} | ${r.group} | ${r.item}${r.note ? " | " + r.note : ""}`);
  }
  console.log(`\n===== CONSOLE ERRORS (${consoleErrors.length}) =====`);
  for (const e of consoleErrors) {
    console.log(`[${e.role}] ${e.url}\n   ${e.text}`);
  }

  const failed = results.filter((r) => r.status === FAIL).length;
  if (failed > 0) process.exitCode = 1;
})();
