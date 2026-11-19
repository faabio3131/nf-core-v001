import { expect, test } from "@playwright/test";

test("Bling review pins a snapshot, escapes supplier text and requires explicit approval", async ({ page, context }) => {
  await context.addCookies([{name: "nfcore_csrf", value: "review-csrf", domain: "127.0.0.1", path: "/"}]);
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    tenant_id: "synthetic", unit_ids: ["unit"], role: "owner",
    permissions: ["portal.read", "integration.manage", "document.issue"],
    supported_documents: ["nfe"], projection: {available_surfaces: ["integrations"]},
  }}));
  await page.route("**/v1/portal/surfaces/integrations*", route => route.fulfill({json: {rows: []}}));
  let selected = "old";
  let approved = false;
  await page.route("**/v1/portal/integrations/bling/orders/9001**", route => {
    const request = route.request();
    if (request.method() === "POST") {
      expect(request.headers()["x-csrf-token"]).toBe("review-csrf");
      if (request.url().endsWith("select-snapshot")) {
        expect(request.postDataJSON()).toEqual({snapshot_sha256: "new"}); selected = "new";
      } else {
        expect(request.postDataJSON()).toEqual({snapshot_sha256: "new", document_id: "prepared-1"}); approved = true;
      }
      return route.fulfill({json: {order: {state: approved ? "queued" : "review_required"}}});
    }
    return route.fulfill({json: {order: {state: approved ? "queued" : "review_required", snapshot_sha256: selected,
      changed_snapshot_sha256: selected === "old" ? "new" : null, document_id: approved ? "prepared-1" : null},
    snapshots: [selected, ...(selected === "old" ? ["new"] : [])].map(sha256 => ({sha256, content: {raw: {nome: "<img src=x onerror=alert(1)>"}}}))}});
  });
  await page.goto("/");
  await page.getByRole("button", {name: "Integrações", exact: true}).click();
  await page.getByLabel("Número interno do pedido no Bling").fill("9001");
  await page.getByRole("button", {name: "Consultar pedido"}).click();
  await page.getByText("Atualização aguardando revisão", {exact: true}).click();
  await expect(page.locator("details img")).toHaveCount(0);
  await page.getByRole("button", {name: "Selecionar esta atualização"}).click();
  await expect(page.getByLabel("Documento fiscal preparado no NFCore")).toBeVisible();
  await expect(page.getByText(/Política fiscal desta empresa e unidade ainda não configurada/)).toBeVisible();
  await page.getByRole("button", {name: "Aprovar envio"}).click();
  expect(approved).toBe(false);
  await page.getByLabel("Documento fiscal preparado no NFCore").fill("prepared-1");
  await page.getByLabel("Revisei o pedido e a correspondência com o documento fiscal preparado.").check();
  await page.getByRole("button", {name: "Aprovar envio"}).click();
  await expect(page.getByText("Situação: queued", {exact: true})).toBeVisible();
  expect(approved).toBe(true);
});

test("native preparation reviews recipient and posts only scoped fiscal facts", async ({page, context}) => {
  await context.addCookies([{name: "nfcore_csrf", value: "native-csrf", domain: "127.0.0.1", path: "/"}]);
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    tenant_id: "synthetic", unit_ids: ["unit"], role: "owner",
    permissions: ["portal.read", "integration.manage", "document.issue"],
    supported_documents: ["nfe"], projection: {available_surfaces: ["integrations"]},
  }}));
  await page.route("**/v1/portal/surfaces/integrations*", route => route.fulfill({json: {rows: []}}));
  let queued = false;
  await page.route("**/v1/portal/integrations/bling/orders/123**", route => {
    if (route.request().method() === "POST") {
      expect(route.request().url()).toMatch(/\/prepare$/);
      expect(route.request().headers()["x-csrf-token"]).toBe("native-csrf");
      const body = route.request().postDataJSON();
      expect(Object.keys(body).sort()).toEqual(["card_payments", "issued_at", "policy_sha256", "recipient", "snapshot_sha256"]);
      expect(body.card_payments).toEqual({"0": {acquirer_cnpj: "12345678000195", brand: "01", authorization: "TEST123"}});
      expect(body.recipient.document).toBe("12345678000195");
      expect(body.recipient.ie_indicator).toBe(9);
      expect(body.recipient.final_consumer).toBe(true);
      expect(body.policy_sha256).toBe("policy-hash");
      queued = true;
      return route.fulfill({json: {document_id: "native-doc", state: "queued"}});
    }
    return route.fulfill({json: {
      order: {state: queued ? "queued" : "review_required", snapshot_sha256: "snapshot-hash", document_id: queued ? "native-doc" : null},
      snapshots: [{sha256: "snapshot-hash", content: {raw: {contato: {nome: "Synthetic buyer", numeroDocumento: "12345678000195"}}}}],
      preparation: {configured: true, policy_id: "synthetic", version: 1, sha256: "policy-hash", issued_at: "2026-11-09T00:00:00+00:00", integrated_card_indexes: [0]},
    }});
  });
  await page.goto("/");
  await page.getByRole("button", {name: "Integrações", exact: true}).click();
  await page.getByLabel("Número interno do pedido no Bling").fill("123");
  await page.getByRole("button", {name: "Consultar pedido"}).click();
  await page.getByRole("button", {name: "Preparar e enviar NF-e"}).click();
  expect(queued).toBe(false);
  for (const [label, value] of [["Logradouro", "Rua Sintetica"], ["Número do endereço", "1"], ["Bairro", "Centro"], ["Município", "Sao Paulo"], ["Código IBGE do município", "3550308"], ["UF", "SP"], ["CEP", "01001000"]]) {
    await page.getByLabel(label, {exact: true}).fill(value);
  }
  await page.getByLabel("Condição da inscrição estadual").selectOption("9");
  await page.getByLabel("Consumidor final", {exact: true}).selectOption("true");
  await page.getByLabel("CNPJ da instituição de pagamento — pagamento 1").fill("12345678000195");
  await page.getByLabel("Código da bandeira — pagamento 1").fill("01");
  await page.getByLabel("Autorização da operação — pagamento 1").fill("TEST123");
  await page.getByLabel("Revisei o pedido, o destinatário e a política fiscal indicada.").check();
  await page.getByRole("button", {name: "Preparar e enviar NF-e"}).click();
  await expect(page.getByText("Situação: queued", {exact: true})).toBeVisible();
  expect(queued).toBe(true);
});


test("Bling mission control lists scoped jobs and recovers missing orders with CSRF", async ({ page, context }) => {
  const installId = "a".repeat(32);
  await context.addCookies([{
    name: "nfcore_csrf", value: "ops-csrf", domain: "127.0.0.1", path: "/",
  }]);
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    tenant_id: "tenant", unit_ids: ["unit"], role: "owner",
    permissions: ["portal.read", "integration.manage", "document.issue"],
    supported_documents: ["nfe"],
    projection: {
      available_surfaces: ["integrations"],
      authorized_units: [{unit_id: "unit", display_name: "Unidade teste", environments: ["homologation"]}],
    },
  }}));
  await page.route("**/v1/portal/surfaces/integrations*", route => route.fulfill({json: {rows: []}}));
  let recovered = false;
  await page.route("**/v1/portal/integrations/bling/installations/available*", route =>
    route.fulfill({json: {rows: [{
      installation_id: installId, company_id: "company", state: "connected",
      environment: "homologation", credential_status: "configured", revision: 1,
    }], next_cursor: null}}));
  await page.route("**/v1/portal/integrations/bling/installations/**", route => {
    const request = route.request();
    const url = new URL(request.url());
    // Specific availability fixture was registered earlier; let it handle this URL.
    if (url.pathname.endsWith("/available")) return route.fallback();
    if (url.pathname.endsWith("/orders") && request.method() === "GET") {
      return route.fulfill({json: {
        rows: [{order_id: 9001, state: "review_required", review_required: true,
          document_id: null, retryable: false, updated_at: "2026-11-10T00:00:00Z"},
        ...(recovered ? [{order_id: 9002, state: "review_required", review_required: true,
          document_id: null, retryable: false, updated_at: "2026-11-10T00:00:00Z"}] : [])],
        next_cursor: null,
      }});
    }
    if (url.pathname.endsWith("/jobs")) return route.fulfill({json: {rows: [
      {entry_id: "c".repeat(64), operation: "process_bling_order",
        status: "dead_letter", attempt_count: 3, available_at: "2026-11-10T00:00:00Z"},
    ], next_offset: null}});
    if (url.pathname.endsWith("/metrics")) return route.fulfill({json: {
      sample_limit: 100, partial: false, order_states: {review_required: recovered ? 2 : 1},
      job_states: {dead_letter: 1}, has_dead_letter: true,
    }});
    if (url.pathname.endsWith("/provider-orders")) return route.fulfill({json: {
      rows: [{order_id: 9002, recorded: recovered}], next_cursor: null,
    }});
    if (url.pathname.endsWith("/orders/9002/recover")) {
      expect(request.method()).toBe("POST");
      expect(request.headers()["x-csrf-token"]).toBe("ops-csrf");
      expect(typeof request.postDataJSON().request_id).toBe("string");
      recovered = true;
      return route.fulfill({json: {outcome: "requires_review", order_id: 9002}});
    }
    if (url.pathname.endsWith("/orders/9002")) return route.fulfill({json: {
      order: {order_id: 9002, state: "review_required", snapshot_sha256: "digest", document_id: null},
      snapshots: [{sha256: "digest", content: {raw: {nome: "<svg onload=alert(1)>"}}}],
      preparation: {configured: false},
    }});
    return route.fulfill({status: 404, json: {code: "NOT_FOUND"}});
  });
  await page.goto("/");
  await page.getByRole("button", {name: "Integrações", exact: true}).click();
  await expect(page.getByRole("heading", {name: "Centro de Operações Bling"})).toBeVisible();
  await expect(page.getByText("Pedido #9001 · review_required")).toBeVisible();
  await expect(page.getByText(/Há eventos em dead-letter/)).toBeVisible();
  await page.getByRole("button", {name: "Localizar pedidos que não chegaram pelo webhook"}).click();
  await expect(page.getByText("Pedido #9002: ausente no NFCore")).toBeVisible();
  await page.getByRole("button", {name: "Recuperar para revisão"}).click();
  await expect(page.getByText("Pedido #9002 · review_required")).toBeVisible();
  await expect(page.getByText("Pedido selecionado")).toBeVisible();
  await expect(page.locator(".bling-operations svg")).toHaveCount(0);
  expect(recovered).toBe(true);
});
