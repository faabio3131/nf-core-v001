import { expect, test } from "@playwright/test";

const origin = "https://127.0.0.1:4174";
async function login(page, account = "owner") {
  await page.goto(origin);
  await page.locator("#login-email").fill(`${account}@example.com`);
  await page.locator("#login-password").fill("synthetic-p02-http-password-2026");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#authority-context")).toContainText("tenant-a");
}

for (const width of [320, 390, 1280]) {
  test(`durable portal preserves scoped support and keyboard details at ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 900});
    await login(page);
    await expect(page.locator(".product-banner-logo-approved")).toBeVisible();
    await page.getByRole("button", {name: "Suporte", exact: true}).click();
    await expect(page.locator("#workspace")).toContainText("Atendimento, SLA, incidentes e saúde operacional externa ainda não estão certificados");
    await expect(page.locator("#fiscal-unit-filter option")).toHaveCount(2);
    await expect(page.locator("#workspace .grid-list")).toContainText("unit-a");
    await expect(page.locator("#workspace .grid-list")).not.toContainText("unit-b");
    const projection = await page.request.get(`${origin}/v1/portal/surfaces/support?unit_id=unit-a&environment=homologation`);
    expect(projection.status()).toBe(200);
    expect((await projection.json()).rows.map((row) => row.unit_id)).toEqual(["unit-a"]);
    await page.locator(".skip-link").focus();
    await expect(page.locator(".skip-link")).toBeInViewport();
    await page.keyboard.press("Enter");
    await expect(page.locator("#main")).toBeFocused();
    await page.locator(".row summary").first().focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".row details").first()).toHaveAttribute("open", "");
    await expect(page.locator(".row dt").filter({hasText: "Canal de atendimento"}).first()).toBeVisible();
    await expect(page.locator("#workspace")).toHaveAttribute("aria-busy", "false");
    const geometry = await page.locator(".row details").first().evaluate((details) => {
      const bounds = details.getBoundingClientRect();
      return {left: bounds.left, right: bounds.right, viewport: innerWidth, overflow: details.scrollWidth - details.clientWidth};
    });
    expect(geometry.left).toBeGreaterThanOrEqual(0);
    expect(geometry.right).toBeLessThanOrEqual(geometry.viewport);
    expect(geometry.overflow).toBeLessThanOrEqual(1);
    await expect(page.locator(".skip-link")).not.toBeInViewport();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({path: `.artifacts/p02-t07/support-${width}.png`, fullPage: true});
    await page.locator("#fiscal-unit-filter").selectOption("unit-b");
    await expect(page.locator("#workspace .grid-list")).toContainText("unit-b");
    await expect(page.locator("#workspace .grid-list")).not.toContainText("unit-a");
  });
}

test("negative readiness remains visibly blocked and surface errors offer a read retry", async ({page}) => {
  // UI-only controlled failure; durable HTTP journeys above prove router integration.
  await page.route("**/v1/portal/bootstrap", (route) => route.fulfill({status: 200, contentType: "application/json", body: JSON.stringify({
    tenant_id: "synthetic-ux", role: "OWNER", permissions: ["portal.read"], unit_ids: [],
    projection: {production_state: "NOT_APPROVED", available_surfaces: ["overview", "support"]},
  })}));
  let requests = 0;
  await page.route("**/v1/portal/surfaces/support*", (route) => {
    requests += 1;
    return route.fulfill({status: 503, contentType: "application/json", body: JSON.stringify({detail: {code: "PORTAL_RUNTIME_NOT_READY", message: "Unavailable"}})});
  });
  await page.goto(origin);
  await expect(page.locator("#critical-state-copy")).toContainText("Produção permanece bloqueada");
  await expect(page.locator(".badge.success").filter({hasText: "NOT_APPROVED"})).toHaveCount(0);
  await page.getByRole("button", {name: "Suporte", exact: true}).click();
  await expect(page.locator("#workspace [role=alert]")).toContainText("Esta capacidade ainda não está disponível");
  await page.getByRole("button", {name: "Tentar carregar novamente"}).click();
  await expect.poll(() => requests).toBe(2);
  await expect(page.locator("#workspace")).toHaveAttribute("aria-busy", "false");
});

test("an in-flight submit is locked and a read cannot erase a pending mutation key", async ({page}) => {
  // UI concurrency/intent contract only; these responses are explicitly synthetic.
  await page.route("**/v1/portal/bootstrap", (route) => route.fulfill({status: 200, contentType: "application/json", body: JSON.stringify({
    tenant_id: "synthetic-ux", role: "OPERATOR", unit_ids: ["unit-a"],
    permissions: ["portal.read", "document.issue", "document.query"],
    projection: {available_surfaces: ["overview", "issuances"],
      configured_fiscal_operations: ["issueFiscalDocument", "queryFiscalDocument"],
      authorized_units: [{unit_id: "unit-a", display_name: "Synthetic unit", environments: ["homologation"]}]},
  })}));
  await page.route("**/v1/portal/surfaces/issuances*", (route) => route.fulfill({status: 200, contentType: "application/json", body: '{"rows":[]}'}));
  // New recovery protocol is stubbed only in this existing UI-only contract.
  await page.route("**/v1/portal/fiscal-intents?**", (route) => route.fulfill({status:200, contentType:"application/json", body:'{"rows":[]}'}));
  await page.route("**/v1/portal/fiscal-intents/prepare/issueFiscalDocument", (route) => route.fulfill({status:200, contentType:"application/json", body:'{"intent_id":"synthetic-ui-only-intent","state":"prepared"}'}));
  const keys = [];
  await page.route("**/v1/portal/fiscal-intents/*/resume", async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    await new Promise((resolve) => setTimeout(resolve, 400));
    await route.fulfill({status: keys.length === 1 ? 503 : 200, contentType: "application/json", body: keys.length === 1 ? '{"detail":{"message":"Synthetic outcome unknown"}}' : '{"status":"synthetic_internal_only"}'});
  });
  await page.route("**/v1/portal/operations/queryFiscalDocument", (route) => route.fulfill({status: 200, contentType: "application/json", body: '{"status":"synthetic_query_only"}'}));
  await page.goto(origin);
  await page.getByRole("button", {name: "Emissões", exact: true}).click();
  await page.getByRole("button", {name: "Executar operação governada"}).click();
  await page.locator("#operation-document-id").fill("synthetic-prepared-document");
  await page.locator("#operation-form").evaluate((form) => {form.requestSubmit(); form.requestSubmit();});
  await expect(page.locator('#operation-form button[type="submit"]')).toBeDisabled();
  await expect(page.locator("#operation-error")).toContainText("Synthetic outcome unknown");
  expect(keys).toHaveLength(1);
  await page.locator("#operation-id").selectOption("queryFiscalDocument");
  await page.locator("#operation-access-key").fill("35191111111111111111550010000000011000000010");
  await page.getByRole("button", {name: "Executar", exact: true}).click();
  await expect(page.locator("#operation-dialog")).not.toBeVisible();
  await page.getByRole("button", {name: "Executar operação governada"}).click();
  await page.getByRole("button", {name: "Executar", exact: true}).click();
  await expect(page.locator("#operation-dialog")).not.toBeVisible();
  expect(keys).toHaveLength(2); expect(keys[0]).toBeTruthy(); expect(keys[0]).toBe(keys[1]);
});
