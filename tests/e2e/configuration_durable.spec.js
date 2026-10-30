import { expect, test } from "@playwright/test";

const origin = "https://127.0.0.1:4174";

test("customer configuration views expose governed forms while keeping metadata sanitized", async ({page}) => {
  await page.goto(origin);
  await page.locator("#login-email").fill("owner@example.com");
  await page.locator("#login-password").fill("synthetic-p02-http-password-2026");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#authority-context")).toContainText("tenant-a");
  for (const [label, identifier] of [
    ["Certificados", "ref:synthetic-a-certificate"],
    ["Provedores", "binding-a"],
    ["Webhooks", "events-a"],
    ["Integrações", "module-a"],
    ["Configurações", "policy-a"],
  ]) {
    await page.getByRole("button", {name: label, exact: true}).click();
    await expect(page.locator("#workspace")).toContainText(identifier);
    await expect(page.locator("#workspace")).toContainText("Cadastro não comprova");
    await expect(page.locator("#workspace")).not.toContainText("SYNTHETIC_QUERY_MUST_NOT_ESCAPE");
    await expect(page.locator("#workspace")).not.toContainText("callback.example.invalid");
    await expect(page.locator("#customer-configuration-form")).toBeVisible();
  }
  await page.locator("#fiscal-unit-filter").selectOption("unit-b");
  await expect(page.locator("#workspace")).toContainText("policy-b");
  await expect(page.locator("#workspace")).not.toContainText("policy-a");
});

test("durable webhook request approval and revocation stay separate from delivery", async ({page}) => {
  // Real canonical HTTP and SQLite; no page.route and no external webhook traffic.
  async function login(account) {
    await page.goto(origin);
    await page.locator("#login-email").fill(`${account}@example.com`);
    await page.locator("#login-password").fill("synthetic-p02-http-password-2026");
    await page.locator("#login-form button[type=submit]").click();
    await expect(page.locator("#authority-context")).toContainText("tenant-a");
  }
  await login("owner");
  await page.getByRole("button", {name: "Webhooks", exact: true}).click();
  await page.locator("#configuration-destination_id").fill("browser-governed-events");
  await page.locator("#configuration-url").fill("https://consumer.example.test/fiscal/webhooks");
  await page.locator("#configuration-enabled").check();
  await page.getByRole("button", {name: "Solicitar destino"}).click();
  await expect(page.locator("#customer-configuration-form [role=status]")).toContainText("aprovação pending");
  await page.reload();
  await page.getByRole("button", {name: "Webhooks", exact: true}).click();
  await expect(page.locator("#workspace")).toContainText("browser-governed-events");
  await expect(page.locator("#workspace")).not.toContainText("consumer.example.test");
  await expect(page.getByRole("button", {name: "Aprovação de egress"})).toHaveCount(0);
  await page.locator("#logout-action").click();
  await login("platform");
  await page.getByRole("button", {name: "Aprovação de egress"}).click();
  for (const [field, value] of Object.entries({tenant: "tenant-a", unit: "unit-a", environment: "homologation", destination: "browser-governed-events"})) await page.locator(`#configuration-egress-${field}`).fill(value);
  await page.getByRole("button", {name: "Consultar solicitação"}).click();
  await expect(page.locator("#egress-decision-form")).toBeVisible();
  await page.locator("#configuration-egress-expiry").fill(new Date(Date.now() + 86400000).toISOString());
  await page.getByRole("button", {name: "Aprovar egress"}).click();
  await expect(page.locator("#egress-review-form [role=status]")).toContainText("Decisão approved registrada · versão 2");
  await page.getByRole("button", {name: "Revogar egress"}).click();
  await expect(page.locator("#egress-review-form [role=status]")).toContainText("Decisão revoked registrada · versão 3");
  await expect(page.locator("#egress-review-form [role=status]")).toContainText("Entrega não confirmada");
});
