import { expect, test } from "@playwright/test";

const origin = "https://127.0.0.1:4174";
// All requests hit the canonical HTTP router and durable SQLite. No page.route mocks.
async function login(page, account = "operator") {
  await page.goto(origin);
  await page.locator("#login-email").fill(`${account}@example.com`);
  await page.locator("#login-password").fill("synthetic-p02-http-password-2026");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#authority-context")).toContainText("tenant-a");
}

test("five fiscal views show durable authorized state and explicit capability blocking", async ({page}) => {
  await login(page);
  for (const [label, expected] of [["Documentos", "DOC-a"], ["Emissões", "DOC-a"], ["Erros", "DOC-a"], ["Conciliação", "DOC-a"]]) {
    await page.getByRole("button", {name: label, exact: true}).click();
    await expect(page.locator("#workspace")).toContainText(expected);
    await expect(page.locator("#workspace")).not.toContainText("DOC-b");
    await expect(page.locator("#workspace")).not.toContainText("DOC-other");
    await expect(page.locator("#workspace")).not.toContainText("PROTECTED_SYNTHETIC_RAW_CONTENT");
    await expect(page.locator("#workspace")).not.toContainText("LEGACY-UNSCOPED");
  }
  await page.getByRole("button", {name: "Capacidades", exact: true}).click();
  await expect(page.locator("#workspace")).toContainText("CAPABILITY_AUTHORITY_NOT_CONFIGURED");
  await expect(page.locator("#workspace")).not.toContainText("HOMOLOGATION_READY");
});

test("owner can select a permitted unit while operator cannot request another unit", async ({page}) => {
  await login(page, "owner");
  await page.getByRole("button", {name: "Documentos", exact: true}).click();
  await page.locator("#fiscal-unit-filter").selectOption("unit-b");
  await expect(page.locator("#workspace")).toContainText("DOC-b");
  await expect(page.locator("#workspace")).not.toContainText("DOC-a");
  await page.locator("#logout-action").click();
  await login(page);
  await page.getByRole("button", {name: "Documentos", exact: true}).click();
  await expect(page.locator("#fiscal-unit-filter option")).toHaveCount(1);
  const response = await page.request.get(`${origin}/v1/portal/surfaces/documents?unit_id=unit-b`);
  expect(response.status()).toBe(403);
});

test("retry after post-commit failure reuses intent and shows one durable reservation", async ({page}) => {
  await login(page);
  await page.getByRole("button", {name: "Emissões", exact: true}).click();
  await page.getByRole("button", {name: "Executar operação governada"}).click();
  await page.locator("#operation-document-id").fill("synthetic-prepared-reference");
  const keys = [];
  page.on("request", (request) => {
    if (request.url().includes("/fiscal-intents/") && request.url().endsWith("/resume")) keys.push(request.headers()["idempotency-key"]);
  });
  await page.getByRole("button", {name: "Executar", exact: true}).click();
  await expect(page.locator("#operation-error")).toContainText("Synthetic response loss");
  await page.getByRole("button", {name: "Executar", exact: true}).click();
  await expect(page.locator("#operation-dialog")).not.toBeVisible();
  await expect(page.locator("#workspace")).toContainText("HTTP-RESERVATION-");
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[0]).toBe(keys[1]);
  const response = await page.request.get(`${origin}/v1/portal/surfaces/issuances?unit_id=unit-a`);
  const body = await response.json();
  expect(body.rows.filter((row) => row.document_id?.startsWith("HTTP-RESERVATION-"))).toHaveLength(1);
  // This proves a reservation and replay, never SEFAZ/provider issuance or production.
});


test("prepared document reconciliation uses durable authority and preserves confirmed result", async ({page}) => {
  await login(page);
  await page.getByRole("button", {name: "Conciliação", exact: true}).click();
  await page.getByRole("button", {name: "Executar operação governada"}).click();
  await expect(page.locator("#operation-id")).toHaveValue("reconcileFiscalOperation");
  await expect(page.locator("#operation-access-key-field")).not.toBeVisible();
  await page.locator("#operation-document-id").fill("missing-prepared-document");
  await page.getByRole("button", {name: "Executar", exact: true}).click();
  await expect(page.locator("#operation-error")).toContainText("Referência inválida");
  await expect(page.locator("#operation-dialog")).toBeVisible();
  await page.locator("#operation-document-id").fill("PREPARED-RECOVERY-a");
  await page.getByRole("button", {name: "Executar", exact: true}).click();
  await expect(page.locator("#prepared-document-result")).toContainText("O recibo do pedido não confirma autorização fiscal");
  await page.reload();
  await page.getByRole("button", {name: "Emissões", exact: true}).click();
  const response = await page.request.get(`${origin}/v1/portal/surfaces/issuances?unit_id=unit-a`);
  const body = await response.json();
  const row = body.rows.find((item) => item.document_id === "PREPARED-RECOVERY-a");
  expect(row).toBeTruthy();
  expect(row.state || row.status).toBe("authorized");
  // Only the provider boundary is synthetic; HTTP, auth, intent and database are real local paths.
});


test("RTC-09 page reads canonical tenant scope and reports missing regime without inventing taxes", async ({page}) => {
  // Real local HTTPS, human session, portal router and durable SQLite. No page.route mocks.
  await login(page, "owner");
  await page.getByRole("button", {name: "Reforma Tributária", exact: true}).click();
  await expect(page.locator("#workspace")).toContainText("Perfil fiscal vigente não configurado");
  await expect(page.locator("#workspace")).toContainText("O CRT não define sozinho o regime de IRPJ/CSLL");
  await expect(page.locator("#workspace")).toContainText("nenhuma emissão ou cálculo fiscal é executado nesta tela");
  await expect(page.locator("#rtc-profile-registration")).toBeVisible();
  await page.locator("#fiscal-unit-filter").selectOption("unit-b");
  await expect(page.locator("#workspace")).toContainText("Perfil fiscal vigente não configurado");
  await expect(page.locator("#workspace")).not.toContainText("RTC Test Company");
  const rejected = await page.request.get(
    `${origin}/v1/portal/surfaces/tax-reform?unit_id=outside-tenant&environment=homologation`,
  );
  expect(rejected.status()).toBe(409);
});
