import { expect, test } from "@playwright/test";

// These are browser-only presentation/transport contract tests. Backend authority,
// XSD signatures and durable fiscal results have separate Python integration tests.
async function openExtremaPage(page, context, permissions) {
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    product: "FM NFCORE", version: "1.0",
    tenant_id: "tenant-extrema", unit_ids: ["unit-extrema"], role: "owner",
    permissions, supported_documents: ["nfse"],
    projection: {
      production_state: "BLOCKED_EXTERNAL",
      configured_fiscal_operations: [
        "issueFiscalDocument", "cancelExtremaNfse", "substituteExtremaNfse",
      ],
      authorized_units: [{
        unit_id: "unit-extrema", display_name: "Extrema synthetic",
        environments: ["homologation"],
      }],
    },
  }}));
  await page.route("**/v1/portal/surfaces/**", route => route.fulfill({
    json: {surface: "issuances", rows: []},
  }));
  await page.route("**/v1/portal/fiscal-intents?**", route => route.fulfill({
    json: {rows: []},
  }));
  await context.addCookies([
    {name: "nfcore_session", value: "synthetic-session", domain: "127.0.0.1", path: "/"},
    {name: "nfcore_csrf", value: "synthetic-csrf", domain: "127.0.0.1", path: "/"},
  ]);
  await page.goto("/");
  await page.getByRole("button", {name: "Emissões", exact: true}).click();
}

const fullRights = [
  "portal.read", "document.query", "document.issue", "document.cancel",
  "configuration.write",
];

test("Extrema cancellation sends only the reviewed issuer-scoped event with session proof", async ({page, context}) => {
  await openExtremaPage(page, context, fullRights);
  const form = page.locator("#extrema-cancel-form");
  await expect(form).toBeVisible();
  const payloads = [];
  const keys = [];
  await page.route("**/v1/portal/operations/cancelExtremaNfse", route => {
    const req = route.request();
    expect(req.headers()["x-csrf-token"]).toBe("synthetic-csrf");
    expect(req.headers()["idempotency-key"]).toBeTruthy();
    keys.push(req.headers()["idempotency-key"]);
    payloads.push(req.postDataJSON());
    return route.fulfill({json: {
      official_fiscal_confirmation: false, status: "cancel_requested",
    }});
  });
  await form.locator('input[type="text"], input:not([type])').first().fill("nfse-extrema-original");
  await form.locator("select").selectOption("1");
  await form.locator('input[type="checkbox"]').check();
  await form.getByRole("button", {name: "Solicitar cancelamento governado"}).click();
  await expect(form.getByRole("status")).toContainText(
    "rejeitou ou não confirmou o cancelamento",
  );
  expect(payloads).toEqual([{
    unit_id: "unit-extrema", environment: "homologation",
    document_id: "nfse-extrema-original", cancellation_code: "1",
    human_approval: true,
  }]);
  expect(keys[0]).toBeTruthy();
  await expect(form.getByRole("status")).not.toContainText(
    "Cancelamento municipal confirmado",
  );
});

test("Extrema substitution requires both role capabilities and cannot infer success", async ({page, context}) => {
  await openExtremaPage(page, context, [
    "portal.read", "document.query", "document.cancel",
  ]);
  await expect(page.locator("#extrema-substitution-form")).toHaveCount(0);
  await page.reload();
  // A fresh signed-in bootstrap with both capabilities is needed.
  await page.unroute("**/v1/portal/bootstrap");
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    product: "FM NFCORE", version: "1.0",
    tenant_id: "tenant-extrema", unit_ids: ["unit-extrema"], role: "owner",
    permissions: fullRights, supported_documents: ["nfse"],
    projection: {
      production_state: "BLOCKED_EXTERNAL",
      configured_fiscal_operations: [
        "issueFiscalDocument", "cancelExtremaNfse", "substituteExtremaNfse",
      ],
      authorized_units: [{
        unit_id: "unit-extrema", display_name: "Extrema synthetic",
        environments: ["homologation"],
      }],
    },
  }}));
  await page.reload();
  await page.getByRole("button", {name: "Emissões", exact: true}).click();
  const form = page.locator("#extrema-substitution-form");
  await expect(form).toBeVisible();
  const pending = [];
  await page.route("**/v1/portal/operations/substituteExtremaNfse", route => {
    const request = route.request();
    pending.push({
      key: request.headers()["idempotency-key"],
      csrf: request.headers()["x-csrf-token"],
      payload: request.postDataJSON(),
    });
    return route.fulfill({json: {official_fiscal_confirmation: false}});
  });
  const inputs = form.locator("input:not([type=checkbox])");
  await inputs.nth(0).fill("old-authorized-document");
  await inputs.nth(1).fill("new-prepared-rps");
  await form.locator("select").selectOption("1");
  await form.locator('input[type="checkbox"]').check();
  await form.getByRole("button", {name: "Solicitar substituição validada"}).click();
  await expect(form.getByRole("status")).toContainText("não confirmada");
  expect(pending).toEqual([{
    key: expect.any(String), csrf: "synthetic-csrf",
    payload: {
      unit_id: "unit-extrema", environment: "homologation",
      original_id: "old-authorized-document",
      replacement_id: "new-prepared-rps",
      cancellation_code: "1", human_approval: true,
    },
  }]);
  expect(pending[0].key.length).toBeGreaterThan(8);
});

test("Extrema reviewed RPS preparation displays a reservation, never authorization", async ({page, context}) => {
  await openExtremaPage(page, context, fullRights);
  const form = page.locator("#extrema-nfse-preparation");
  await expect(form).toBeVisible();
  const fields = {
    source_id: "reviewed-service-1",
    competence_date: "2026-11-11",
    taker_cnpj: "12345678000195",
    taker_name: "Synthetic Buyer Ltda",
    service_code: "0107",
    description: "Approved municipal service, synthetic",
    gross_amount: "100.00",
    deduction_amount: "0.00",
    iss_rate_fraction: "0.0300",
    exigibilidade_iss: "1",
    incidence_municipality: "3125101",
    nbs_code: "123456789",
    rtc_operation_indicator: "010101",
    rtc_cst: "000",
    rtc_tax_class: "000001",
    rule_reference: "urn:nfcore:test:rtc-rule",
    rule_version: "1",
    rps_series: "1",
  };
  for (const [name, value] of Object.entries(fields)) {
    await form.locator(`[name="${name}"]`).fill(value);
  }
  await form.locator('[name="iss_withheld"]').selectOption("false");
  await form.locator('[name="incentive_fiscal"]').selectOption("false");
  await form.locator('input[type="checkbox"]').check();
  const accepted = [];
  await page.route("**/v1/portal/operations/prepareExtremaNfse", route => {
    const req = route.request();
    expect(req.headers()["x-csrf-token"]).toBe("synthetic-csrf");
    expect(req.headers()["idempotency-key"]).toBeTruthy();
    accepted.push(req.postDataJSON());
    return route.fulfill({json: {
      document_id: "synthetic-extrema-durable-ref",
      rps_series: 1, rps_number: 42, status: "ready_to_transmit",
    }});
  });
  await form.getByRole("button", {name: "Preparar RPS em homologação"}).click();
  await expect(page.locator("#extrema-preparation-result")).toContainText(
    "NÃO é autorização municipal",
  );
  expect(accepted).toHaveLength(1);
  expect(accepted[0].fiscal_review_approved).toBe(true);
  expect(accepted[0].tenant_id).toBeUndefined();
  expect(accepted[0].issuer_cnpj).toBeUndefined();
  expect(accepted[0].rps_number).toBeUndefined();
});
