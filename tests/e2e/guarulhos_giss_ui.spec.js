import { expect, test } from "@playwright/test";

// Presentation/HTTP contract only; municipal confirmation is never simulated as homologation.
async function openGuarulhos(page, context, permissions) {
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    tenant_id: "tenant-guarulhos", unit_ids: ["unit-g"], role: "owner",
    permissions, supported_documents: ["nfse"],
    projection: {
      production_state: "BLOCKED_EXTERNAL",
      configured_fiscal_operations: ["cancelGuarulhosNfse", "substituteGuarulhosNfse"],
      authorized_units: [{unit_id: "unit-g", display_name: "Guarulhos synthetic",
        environments: ["homologation"]}],
    },
  }}));
  await page.route("**/v1/portal/surfaces/**", route => route.fulfill({json: {rows: []}}));
  await page.route("**/v1/portal/fiscal-intents?**", route => route.fulfill({json: {rows: []}}));
  await context.addCookies([
    {name: "nfcore_session", value: "synthetic-session", domain: "127.0.0.1", path: "/"},
    {name: "nfcore_csrf", value: "synthetic-csrf", domain: "127.0.0.1", path: "/"},
  ]);
  await page.goto("/");
  await page.getByRole("button", {name: "Emissões", exact: true}).click();
}

test("Guarulhos cancellation uses scoped canonical operation and preserves uncertain outcome", async ({page, context}) => {
  await openGuarulhos(page, context, ["portal.read", "document.query", "document.cancel", "document.issue"]);
  const payloads = [];
  await page.route("**/v1/portal/operations/cancelGuarulhosNfse", route => {
    expect(route.request().headers()["x-csrf-token"]).toBe("synthetic-csrf");
    expect(route.request().headers()["idempotency-key"]).toBeTruthy();
    payloads.push(route.request().postDataJSON());
    return route.fulfill({json: {official_fiscal_confirmation: false}});
  });
  const form = page.locator("#guarulhos-cancel-form");
  await expect(form).toBeVisible();
  await expect(page.locator("#jundiai-cancel-form")).toHaveCount(0);
  await form.locator('input[type="text"]').fill("original-g");
  await form.locator("select").selectOption("4");
  await form.locator('input[type="checkbox"]').check();
  await form.getByRole("button", {name: "Cancelar nota original"}).click();
  await expect(form.getByRole("status")).toContainText("Cancelamento não confirmado");
  expect(payloads).toEqual([{unit_id: "unit-g", environment: "homologation",
    document_id: "original-g", reason_code: "4", human_approval: true}]);
  await expect(form.getByRole("button")).toBeDisabled();
  await expect(page.locator("#guarulhos-substitute-form")).toContainText("não representa substituição municipal atômica");
});

test("Guarulhos reissue requires both capabilities and cancellation requires cancel permission", async ({page, context}) => {
  await openGuarulhos(page, context, ["portal.read", "document.query", "document.cancel"]);
  await expect(page.locator("#guarulhos-cancel-form")).toBeVisible();
  await expect(page.locator("#guarulhos-substitute-form")).toHaveCount(0);
});

test("Guarulhos events are hidden without cancellation permission", async ({page, context}) => {
  await openGuarulhos(page, context, ["portal.read", "document.query", "document.issue"]);
  await expect(page.locator("#guarulhos-cancel-form")).toHaveCount(0);
  await expect(page.locator("#guarulhos-substitute-form")).toHaveCount(0);
});
