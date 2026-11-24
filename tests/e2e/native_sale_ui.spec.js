import {expect, test} from "@playwright/test";

// Browser contract; real session/SQLite/PG/crypto tests: test_native_sale.py.
async function openSale(page, context, issue = true) {
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    product:"FM NFCORE", version:"1.0", tenant_id:"synthetic",
    unit_ids:["unit"], role:"owner", permissions:["portal.read", "document.query", ...(issue ? ["document.issue"] : [])],
    supported_documents:["nfe", "nfce"], projection:{
      production_state:"BLOCKED_EXTERNAL", configured_fiscal_operations:["issueFiscalDocument"],
      authorized_units:[{unit_id:"unit", display_name:"Synthetic MG", environments:["homologation"]}],
    },
  }}));
  await page.route("**/v1/portal/surfaces/**", route => route.fulfill({json:{rows:[]}}));
  await page.route("**/v1/portal/fiscal-intents?**", route => route.fulfill({json:{rows:[]}}));
  await page.route("**/v1/portal/operations/reviewNativeSale", route => route.fulfill({json:{
    policy_sha256:"a".repeat(64), products:[{product_id:"p1", description:"Synthetic", unit:"UN"}],
  }}));
  await context.addCookies([
    {name:"nfcore_session", value:"synthetic", domain:"127.0.0.1", path:"/"},
    {name:"nfcore_csrf", value:"synthetic-csrf", domain:"127.0.0.1", path:"/"},
  ]);
  await page.goto("/");
  await page.getByRole("button", {name:"Emissões", exact:true}).click();
  return page.locator("#native-sale-preparation");
}

async function fillSale(form) {
  await form.locator('[name="document_kind"]').selectOption("nfce");
  await form.locator('[name="source_id"]').fill("manual-sale-1");
  await form.locator('[name="anonymous"]').check();
  await form.getByRole("button", {name:"Carregar configuração fiscal"}).click();
  await form.locator('[name="unit_price"]').fill("10.00");
  await form.locator('[name="amount"]').fill("10.00");
}

test("sale prepares canonical facts with csrf and retry identity; no browser fiscal authority", async ({page, context}) => {
  const form = await openSale(page, context);
  await expect(form.locator('select[name="document_kind"] option[value="nfce"]'))
    .toHaveText("NFC-e 65 — SP/MG");
  await fillSale(form);
  const requests = [];
  await page.route("**/v1/portal/operations/prepareNativeSale", route => {
    requests.push({body:route.request().postDataJSON(), headers:route.request().headers()});
    return route.fulfill({json:{document_id:"sale-prepared", transmitted:false}});
  });
  await form.getByRole("button", {name:"Preparar documento", exact:true}).click();
  await expect(form.getByRole("status")).toContainText("sale-prepared");
  expect(requests).toHaveLength(1);
  expect(requests[0].headers["x-csrf-token"]).toBe("synthetic-csrf");
  expect(requests[0].headers["idempotency-key"]).toBeTruthy();
  expect(requests[0].body).toMatchObject({unit_id:"unit", document_kind:"nfce", recipient:null,
    items:[{product_id:"p1", quantity:"1", unit_price:"10.00"}]});
  for (const field of ["tenant_id", "xml", "provider_id", "series", "invoice_number", "rules"]) {
    expect(requests[0].body).not.toHaveProperty(field);
  }
});

test("deterministic validation error permits corrected facts without reload", async ({page, context}) => {
  const form = await openSale(page, context);
  await fillSale(form);
  let attempts = 0;
  await page.route("**/v1/portal/operations/prepareNativeSale", route => {
    attempts++;
    return attempts === 1
      ? route.fulfill({status:400, json:{detail:{code:"NATIVE_SALE_INVALID_FACTS_OR_CONFIGURATION"}}})
      : route.fulfill({json:{document_id:"corrected-sale", transmitted:false}});
  });
  await form.getByRole("button", {name:"Preparar documento", exact:true}).click();
  await expect(form.getByRole("status")).toContainText("Confira destinatário");
  await form.locator('[name="unit_price"]').fill("11.00");
  await form.locator('[name="amount"]').fill("11.00");
  await form.getByRole("button", {name:"Preparar documento", exact:true}).click();
  await expect(form.getByRole("status")).toContainText("corrected-sale");
  expect(attempts).toBe(2);
});

test("network ambiguity preserves the original request and key", async ({page, context}) => {
  const form = await openSale(page, context);
  await fillSale(form);
  const attempts = [];
  await page.route("**/v1/portal/operations/prepareNativeSale", route => {
    attempts.push({body:route.request().postData(), key:route.request().headers()["idempotency-key"]});
    return attempts.length === 1 ? route.abort("failed") : route.fulfill({json:{document_id:"recovered-sale"}});
  });
  await form.getByRole("button", {name:"Preparar documento", exact:true}).click();
  await expect(form.getByRole("status")).toContainText("Conexão interrompida");
  await form.getByRole("button", {name:"Preparar documento", exact:true}).click();
  await expect(form.getByRole("status")).toContainText("recovered-sale");
  expect(attempts[0]).toEqual(attempts[1]);
});

test("viewer cannot see sale preparation", async ({page, context}) => {
  await expect(await openSale(page, context, false)).toHaveCount(0);
});

test("T14 reviewed ICMS configuration warns of mandatory server approval", async ({page, context}) => {
  const form = await openSale(page, context);
  await page.route("**/v1/portal/operations/reviewNativeSale", route => route.fulfill({json:{
    policy_sha256:"a".repeat(64), products:[{product_id:"p1", description:"Synthetic", unit:"UN"}],
    accounting_approval_required:[{benefit_id:"synthetic-benefit", benefit_code:"SP000001", rule_id:"r1"}],
  }}));
  await form.locator('[name="document_kind"]').selectOption("nfe");
  await form.getByRole("button", {name:"Carregar configuração fiscal"}).click();
  await expect(form.getByRole("status")).toContainText("SP000001 (synthetic-benefit)");
  await expect(form.getByRole("status")).toContainText("sem parecer válido, a operação é bloqueada");
});
