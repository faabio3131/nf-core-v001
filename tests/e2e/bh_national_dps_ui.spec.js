import {expect, test} from "@playwright/test";

// Adapted from PR440 to the shared native preparation form. Browser contract only;
// authenticated API/persistence tests are in test_native_nfse_preparation_http.py.
const fullRights = [
  "portal.read", "document.query", "document.issue",
  "configuration.write",
];

async function openBh(page, context, permissions) {
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    product: "FM NFCORE", version: "1.0", tenant_id: "tenant-bh",
    unit_ids: ["unit-bh"], role: "owner", permissions,
    supported_documents: ["nfse"],
    projection: {
      production_state: "BLOCKED_EXTERNAL",
      configured_fiscal_operations: ["issueFiscalDocument", "reconcileFiscalOperation"],
      authorized_units: [{
        unit_id: "unit-bh", display_name: "Belo Horizonte Synthetic",
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
    {name: "nfcore_session", value: "synthetic", domain: "127.0.0.1", path: "/"},
    {name: "nfcore_csrf", value: "bh-synthetic-csrf", domain: "127.0.0.1", path: "/"},
  ]);
  await page.goto("/");
  await page.getByRole("button", {name: "Emissões", exact: true}).click();
}

test("BH reviewed cTribMun and NBS use the shared native preparation contract", async ({page, context}) => {
  await openBh(page, context, fullRights);
  const form = page.locator("#native-nfse-preparation");
  await expect(form).toBeVisible();
  const values = {
    source_id: "bh-approved-order-1", competence_date: "2026-11-16",
    service_state_code: "MG", service_municipality_ibge: "3106200",
    municipal_service_code: "0107", national_taxation_code: "010701",
    municipal_taxation_detail: "001", nbs_code: "115021000",
    description: "Synthetic service reviewed by accountant",
    gross_amount: "100.00", deduction_amount: "0.00", iss_amount: "3.00",
    taker_document: "12345678000195", taker_name: "Synthetic recipient",
    taker_street: "Rua Teste", taker_number: "10", taker_neighborhood: "Centro",
    taker_city: "Belo Horizonte", taker_state: "MG",
    taker_municipality_ibge: "3106200", taker_postal_code: "30110000",
    source_normative: "urn:nfcore:synthetic:reviewed:2026", rule_version: "1",
  };
  for (const [key, value] of Object.entries(values)) {
    await form.locator('input[name="' + key + '"]').fill(value);
  }
  await form.locator('select[name="iss_withheld"]').selectOption("false");
  await form.locator('input[type="checkbox"]').first().check();
  const recorded = [];
  await page.route("**/v1/portal/operations/prepareNativeNfse", route => {
    const request = route.request();
    expect(request.headers()["x-csrf-token"]).toBe("bh-synthetic-csrf");
    expect(request.headers()["idempotency-key"]).toBeTruthy();
    recorded.push(request.postDataJSON());
    return route.fulfill({json: {
      document_id: "bh-prepared-1", status: "ready_to_transmit", transmitted: false,
      fiscal_authorization: "not_inferred_from_preparation",
      fiscal_policy_state: "review_required_before_sefin",
      dps_numbering: "reserved_durable", dps_series: 1, dps_number: 17,
    }});
  });
  await form.getByRole("button", {name: "Preparar NFS-e revisada em homologação"}).click();
  await expect(form.locator("#native-nfse-result")).toContainText("não transmitido nem autorizado");
  await expect(form.locator("#native-nfse-result")).toContainText(
    "BLOQUEIO FISCAL: falta política tributária nacional aprovada e instalada",
  );
  await expect(form.locator("#native-nfse-result")).toContainText(
    "DPS série 1, número 17 já reservados de forma durável",
  );
  expect(recorded).toHaveLength(1);
  expect(recorded[0]).toMatchObject({
    unit_id: "unit-bh", environment: "homologation",
    municipal_taxation_detail: "001", nbs_code: "115021000",
    fiscal_review_approved: true, iss_withheld: false, rule_version: 1,
  });
  for (const field of ["tenant_id", "certificate", "provider_id", "dps_series", "dps_number"]) {
    expect(recorded[0]).not.toHaveProperty(field);
  }
});

test("native preparation is hidden without both configuration and issuance authority", async ({page, context}) => {
  await openBh(page, context, ["portal.read", "document.query", "configuration.write"]);
  await expect(page.locator("#native-nfse-preparation")).toHaveCount(0);
});
