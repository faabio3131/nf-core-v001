import { expect, test } from "@playwright/test";

for (const queryStatus of ["authorized", "pending", "not_found"]) {
  test(`fiscal query displays ${queryStatus} without inferring a receipt`, async ({ page, context }) => {
    const accessKey = "35251012345678000190550010000000011000000010";
    await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
      tenant_id: "tenant-e2e", unit_ids: ["unit-a"], role: "owner",
      permissions: ["portal.read", "document.query"], supported_documents: ["nfe"],
      projection: {configured_fiscal_operations: ["queryFiscalDocument"],
        authorized_units: [{unit_id: "unit-a", display_name: "Synthetic unit", environments: ["homologation"]}]},
    }}));
    await page.route("**/v1/portal/surfaces/**", route => route.fulfill({json: {rows: []}}));
    await page.route("**/v1/portal/operations/queryFiscalDocument", route => {
      expect(route.request().postDataJSON()).toEqual({access_key: accessKey, unit_id: "unit-a", environment: "homologation"});
      expect(route.request().headers()["idempotency-key"]).toBeUndefined();
      return route.fulfill({json: {status: queryStatus, access_key: accessKey,
        protocol_reference: queryStatus === "authorized" ? "<b>synthetic-protocol</b>" : null}});
    });
    await context.addCookies([
      {name: "nfcore_session", value: "opaque-session", domain: "127.0.0.1", path: "/"},
      {name: "nfcore_csrf", value: "csrf-e2e", domain: "127.0.0.1", path: "/"},
    ]);
    await page.goto("/");
    await page.getByRole("button", {name: "Documentos", exact: true}).click();
    await page.getByRole("button", {name: "Executar operação governada"}).click();
    await page.locator("#operation-id").selectOption("queryFiscalDocument");
    await page.locator("#operation-access-key").fill(accessKey);
    await page.getByRole("button", {name: "Executar", exact: true}).click();
    const result = page.locator("#fiscal-operation-result");
    await expect(result).toContainText(`Resultado da consulta: ${queryStatus}.`);
    await expect(result).toContainText(accessKey);
    await expect(result).toContainText(queryStatus === "authorized" ? "<b>synthetic-protocol</b>" : "Nenhum protocolo informado");
    await expect(result.locator("b")).toHaveCount(0);
  });
}

test("authenticated portal loads governed tenant context and real surface", async ({ page, context }) => {
  await page.route("**/v1/portal/bootstrap", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        product: "FM NFCORE",
        version: "1.0",
        tenant_id: "tenant-e2e",
        unit_ids: ["unit-a"],
        role: "owner",
        permissions: ["portal.read", "document.query", "document.issue"],
        supported_documents: ["nfe", "nfce", "nfse"],
        projection: { production_state: "BLOCKED_EXTERNAL", readiness: "EVIDENCE_REQUIRED" },
      }),
    });
  });

  await page.route("**/v1/portal/surfaces/documents*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        surface: "documents",
        rows: [{ document_id: "DOC-E2E-1", kind: "NF-e", status: "AUTHORIZED" }],
      }),
    });
  });

  await context.addCookies([
    { name: "nfcore_session", value: "opaque-session", domain: "127.0.0.1", path: "/" },
    { name: "nfcore_csrf", value: "csrf-e2e", domain: "127.0.0.1", path: "/" },
  ]);

  await page.goto("/");
  await expect(page.getByText("tenant-e2e · owner")).toBeVisible();
  await expect(page.locator("#critical-state-title")).toHaveText("Bloqueado por dependência externa");
  await page.getByRole("button", { name: "Documentos" }).click();
  await expect(page.locator(".grid-list .row strong").filter({hasText: "DOC-E2E-1"})).toBeVisible();
  await expect(page.locator(".grid-list .row .badge").filter({hasText: "AUTHORIZED"})).toBeVisible();
});

for (const fiscalMutation of ["issueFiscalDocument", "cancelFiscalDocument"]) {
test(`${fiscalMutation} sends document reference, csrf and idempotency proof`, async ({ page, context }) => {
  await page.route("**/v1/portal/bootstrap", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        product: "FM NFCORE",
        version: "1.0",
        tenant_id: "tenant-e2e",
        unit_ids: ["unit-a"],
        role: "owner",
        permissions: ["portal.read", "document.query", "document.issue", "document.cancel"],
        supported_documents: ["nfe", "nfce", "nfse"],
        projection: { production_state: "BLOCKED_EXTERNAL", configured_fiscal_operations: [fiscalMutation],
          authorized_units: [{unit_id: "unit-a", display_name: "Synthetic unit A", environments: ["homologation"]}] },
      }),
    });
  });
  await page.route("**/v1/portal/surfaces/issuances*", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ surface: "issuances", rows: [] }) });
  });

  let seenCsrf = "";
  let seenIdempotency = "";
  await page.route("**/v1/portal/fiscal-intents?**", (route) => route.fulfill({json:{rows:[]}}));
  await page.route(`**/v1/portal/fiscal-intents/prepare/${fiscalMutation}`, (route) => {
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf-e2e");
    expect(route.request().headers()["idempotency-key"].length).toBeGreaterThan(10);
    expect(route.request().postDataJSON().document_id).toBe("DOC-E2E-PREPARED");
    return route.fulfill({json:{intent_id:"synthetic-ui-proof-intent",state:"prepared"}});
  });
  await page.route("**/v1/portal/fiscal-intents/*/resume", async (route) => {
    seenCsrf = route.request().headers()["x-csrf-token"] || "";
    seenIdempotency = route.request().headers()["idempotency-key"] || "";
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ACCEPTED" }) });
  });

  await context.addCookies([
    { name: "nfcore_session", value: "opaque-session", domain: "127.0.0.1", path: "/" },
    { name: "nfcore_csrf", value: "csrf-e2e", domain: "127.0.0.1", path: "/" },
  ]);

  await page.goto("/");
  await page.getByRole("button", { name: "Emissões" }).click();
  await page.getByRole("button", { name: "Executar operação governada" }).click();
  await page.locator("#operation-unit").fill("unit-a");
  await page.locator("#operation-document-id").fill("DOC-E2E-PREPARED");
  if (fiscalMutation === "cancelFiscalDocument") {
    await page.locator("#operation-access-key").fill("35251012345678000190550010000000011000000010");
    await page.locator("#operation-authorization-protocol").fill("SYNTHETIC-AUTH");
    await page.locator("#operation-cancel-justification").fill("Justificativa sintetica de cancelamento");
  }
  await page.getByRole("button", { name: "Executar", exact: true }).click();

  await expect.poll(() => seenCsrf).toBe("csrf-e2e");
  expect(seenIdempotency.length).toBeGreaterThan(10);
});
}

test("activation fragment completes password setup without keeping token in URL", async ({ page }) => {
  let submittedToken = "";

  await page.route("**/v1/portal/bootstrap", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: { message: "Authentication required" } }),
    });
  });
  await page.route("**/v1/auth/password-reset/complete", async (route) => {
    const payload = route.request().postDataJSON();
    submittedToken = payload.reset_token || "";
    await route.fulfill({ status: 204, body: "" });
  });

  await page.goto("/#token=synthetic-fragment-reset-token");
  await expect(page.locator("#password-reset-complete-form")).toBeVisible();
  await expect(page).not.toHaveURL(/token=/);

  await page.locator("#password-reset-new-password").fill("Strong-password-2026");
  await page.getByRole("button", { name: "Alterar senha" }).click();

  await expect.poll(() => submittedToken).toBe("synthetic-fragment-reset-token");
  await expect(page).not.toHaveURL(/token=/);
  await expect(page.getByText("Senha alterada. Entre novamente com a nova senha.")).toBeVisible();
});


test("activation shows actionable pt-BR message for an unusable reset token", async ({ page }) => {
  await page.route("**/v1/portal/bootstrap", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: { message: "Authentication required" } }),
    });
  });
  await page.route("**/v1/auth/password-reset/complete", async (route) => {
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          code: "PASSWORD_RESET_NOT_USABLE",
          message: "Password reset is not usable",
        },
      }),
    });
  });

  await page.goto("/#token=obsolete-reset-token");
  await expect(page.getByText(/12 a 1024 caracteres/)).toBeVisible();
  await page.locator("#password-reset-new-password").fill("G7!mQ2#vR9$kT4-xP8@cL6");
  await page.getByRole("button", { name: "Alterar senha" }).click();

  await expect(
    page.getByText(
      "Este link de recuperação não é mais válido. Solicite um novo link e use somente o e-mail mais recente.",
    ),
  ).toBeVisible();
});


test("authenticated session cannot bypass an unusable reset link", async ({ page }) => {
  let bootstrapCalls = 0;

  await page.route("**/v1/portal/bootstrap", async (route) => {
    bootstrapCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        tenant_id: "tenant-a",
        role: "OWNER",
        unit_ids: ["unit-a"],
        platform_admin: false,
        permissions: [],
        supported_documents: ["NF-e"],
        projection: {},
      }),
    });
  });
  await page.route("**/v1/auth/password-reset/complete", async (route) => {
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          code: "PASSWORD_RESET_NOT_USABLE",
          message: "Password reset is not usable",
        },
      }),
    });
  });

  await page.goto("/#token=consumed-reset-token");
  await expect(page.locator("#password-reset-complete-form")).toBeVisible();
  await expect(page.locator("#app-shell")).toBeHidden();
  await expect(page).not.toHaveURL(/token=/);
  expect(bootstrapCalls).toBe(0);

  await page.locator("#password-reset-new-password").fill("G7!mQ2#vR9$kT4-xP8@cL6");
  await page.getByRole("button", { name: "Alterar senha" }).click();

  await expect(
    page.getByText(
      "Este link de recuperação não é mais válido. Solicite um novo link e use somente o e-mail mais recente.",
    ),
  ).toBeVisible();
  await expect(page.locator("#app-shell")).toBeHidden();
  expect(bootstrapCalls).toBe(0);
});


test("mobile overview does not overflow the viewport", async ({ page, context }) => {
  await page.setViewportSize({ width: 390, height: 844 });

  await page.route("**/v1/portal/bootstrap", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        product: "FM NFCORE",
        version: "1.0",
        tenant_id: "nfcore-staging-e2e",
        unit_ids: [],
        role: "owner",
        permissions: ["portal.read"],
        supported_documents: ["nfe", "nfce", "nfse"],
        projection: {
          organization_onboarded: true,
          legal_name: "NFCore Staging E2E Test",
          unit_count: 0,
          unit_scope: "all",
          enabled_environments: [],
          production_state: "HUMAN_APPROVAL_REQUIRED",
        },
      }),
    });
  });

  await context.addCookies([
    { name: "nfcore_session", value: "opaque-session", domain: "127.0.0.1", path: "/" },
    { name: "nfcore_csrf", value: "csrf-e2e", domain: "127.0.0.1", path: "/" },
  ]);

  await page.goto("/");
  await expect(page.getByText("nfcore-staging-e2e · owner")).toBeVisible();

  const geometry = await page.evaluate(() => {
    const doc = document.documentElement;
    const banner = document.querySelector("#critical-state");
    const main = document.querySelector("main");
    const nav = document.querySelector("nav");
    if (!(banner instanceof HTMLElement) || !(main instanceof HTMLElement) || !(nav instanceof HTMLElement)) {
      throw new Error("Expected portal layout elements");
    }
    const bannerRect = banner.getBoundingClientRect();
    const mainRect = main.getBoundingClientRect();
    const navRect = nav.getBoundingClientRect();
    return {
      clientWidth: doc.clientWidth,
      scrollWidth: doc.scrollWidth,
      bannerRight: bannerRect.right,
      mainRight: mainRect.right,
      navRight: navRect.right,
    };
  });

  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
  expect(geometry.bannerRight).toBeLessThanOrEqual(geometry.clientWidth + 1);
  expect(geometry.mainRight).toBeLessThanOrEqual(geometry.clientWidth + 1);
  expect(geometry.navRight).toBeLessThanOrEqual(geometry.clientWidth + 1);
});


test("mobile overview keeps premium header compact", async ({ page, context }) => {
  await page.setViewportSize({ width: 390, height: 844 });

  await page.route("**/v1/portal/bootstrap", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        product: "FM NFCORE",
        version: "1.0",
        tenant_id: "nfcore-staging-e2e",
        unit_ids: [],
        role: "owner",
        permissions: ["portal.read"],
        supported_documents: ["nfe", "nfce", "nfse"],
        projection: {
          organization_onboarded: true,
          legal_name: "NFCore Staging E2E Test",
          unit_count: 0,
          unit_scope: "all",
          enabled_environments: [],
          production_state: "HUMAN_APPROVAL_REQUIRED",
        },
      }),
    });
  });

  await context.addCookies([
    { name: "nfcore_session", value: "opaque-session", domain: "127.0.0.1", path: "/" },
    { name: "nfcore_csrf", value: "csrf-e2e", domain: "127.0.0.1", path: "/" },
  ]);

  await page.goto("/");
  await expect(page.getByText("nfcore-staging-e2e · owner")).toBeVisible();

  const geometry = await page.evaluate(() => {
    const sidebar = document.querySelector(".sidebar");
    const topbar = document.querySelector(".topbar");
    const banner = document.querySelector("#critical-state");
    if (!(sidebar instanceof HTMLElement) || !(topbar instanceof HTMLElement) || !(banner instanceof HTMLElement)) {
      throw new Error("Expected premium mobile layout elements");
    }
    const sidebarRect = sidebar.getBoundingClientRect();
    const topbarRect = topbar.getBoundingClientRect();
    const bannerRect = banner.getBoundingClientRect();
    return {
      sidebarHeight: sidebarRect.height,
      topbarHeight: topbarRect.height,
      bannerTop: bannerRect.top,
    };
  });

  expect(geometry.sidebarHeight).toBeLessThanOrEqual(150);
  expect(geometry.topbarHeight).toBeLessThanOrEqual(125);
  expect(geometry.bannerTop).toBeLessThanOrEqual(305);

  // A long tenant label must not collapse into a narrow fourth column.
  const contextBounds = await page.locator("#authority-context").boundingBox();
  const actionsBounds = await page.locator(".top-actions").boundingBox();
  expect(contextBounds.width).toBeGreaterThanOrEqual(actionsBounds.width - 1);
  // MFA added a fourth header element. All session actions must remain present
  // and usable; compactness must not be achieved by clipping or hiding them.
  for (const id of ["theme-toggle", "security-action", "logout-action"]) {
    const action = page.locator("#" + id);
    await expect(action).toBeVisible();
    await expect(action).toBeEnabled();
    const bounds = await action.boundingBox();
    expect(bounds.height).toBeGreaterThanOrEqual(44);
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(391);
  }
  await page.setViewportSize({ width: 320, height: 844 });
  await expect(page.locator("#authority-context")).toHaveText("nfcore-staging-e2e · owner");
  for (const id of ["authority-context", "theme-toggle", "security-action", "logout-action"]) {
    const element = page.locator("#" + id);
    await expect(element).toBeVisible();
    const bounds = await element.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(321);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(320);
});

for (const [view, label, operation, fields] of [
  ["certificates", "Certificados", "configureCertificates", {reference_id: "ref:synthetic-browser", kind: "certificate"}],
  ["providers", "Provedores", "configureProviders", {binding_id: "synthetic-binding", document_kind: "nfe", state_code: "SP", operation: "authorize", provider_id: "synthetic"}],
  ["webhooks", "Webhooks", "configureWebhooks", {destination_id: "synthetic-events", url: "https://consumer.example.test/fiscal/webhooks"}],
  ["integrations", "Integrações", "configureIntegrations", {module_id: "synthetic-module"}],
  ["settings", "Configurações", "configureSettings", {policy_id: "synthetic-policy", provider_id: "synthetic", connect_timeout_seconds: "2", read_timeout_seconds: "3", max_attempts: "2", base_delay_seconds: "1", max_delay_seconds: "5", jitter_ratio: "0.1", circuit_failure_threshold: "3", circuit_recovery_seconds: "10", circuit_success_threshold: "1"}],
]) {
  test(`synthetic ${view} form submits scoped version csrf and idempotency contract`, async ({page, context}) => {
    await context.addCookies([{name: "nfcore_csrf", value: "synthetic-csrf", domain: "127.0.0.1", path: "/"}]);
    await page.route("**/v1/portal/bootstrap", (route) => route.fulfill({json: {
      tenant_id: "synthetic-tenant", role: "owner", platform_admin: false,
      unit_ids: ["unit-a"], permissions: ["portal.read", "certificate.manage", "integration.manage", "configuration.write"],
      supported_documents: ["nfe"], projection: {available_surfaces: ["overview", view],
        customer_configuration_operations: [operation],
        authorized_units: [{unit_id: "unit-a", display_name: "Synthetic unit", environments: ["homologation"]}]},
    }}));
    await page.route(`**/v1/portal/surfaces/${view}*`, (route) => route.fulfill({json: {rows: []}}));
    let submitted = null;
    await page.route(`**/v1/portal/operations/${operation}`, (route) => {
      submitted = route.request().postDataJSON();
      expect(route.request().headers()["x-csrf-token"]).toBe("synthetic-csrf");
      expect(route.request().headers()["idempotency-key"].length).toBeGreaterThan(10);
      return route.fulfill({json: {status: "configuration_recorded", version: 1, approval_status: view === "webhooks" ? "pending" : undefined}});
    });
    await page.goto("/"); await page.getByRole("button", {name: label, exact: true}).click();
    for (const [field, value] of Object.entries(fields)) {
      const control = page.locator(`#configuration-${field}`);
      // Fixed technical values are Portuguese-labelled selects; free values stay text inputs.
      if (await control.evaluate((element) => element.tagName) === "SELECT") await control.selectOption(value);
      else await control.fill(value);
    }
    await page.locator("#customer-configuration-form button[type=submit]").click();
    await expect(page.locator("#customer-configuration-form [role=status]")).toContainText("versão 1");
    expect(submitted.unit_id).toBe("unit-a"); expect(submitted.environment).toBe("homologation");
    expect(submitted.expected_version).toBe(0); expect(submitted.tenant_id).toBeUndefined();
    expect(submitted.platform_admin).toBeUndefined();
    for (const [field, value] of Object.entries(fields)) {
      if (["kind", "document_kind", "operation"].includes(field)) expect(submitted.values[field]).toBe(value);
    }
    if (view === "webhooks") await expect(page.locator("#customer-configuration-form [role=status]")).toContainText("aprovação pending");
  });
}

test("platform egress review uses existing session and approved target version", async ({page, context}) => {
  await context.addCookies([{name: "nfcore_csrf", value: "synthetic-csrf", domain: "127.0.0.1", path: "/"}]);
  await page.route("**/v1/portal/bootstrap", (route) => route.fulfill({json: {
    tenant_id: "synthetic-platform", role: "owner", platform_admin: true, unit_ids: null,
    permissions: ["portal.read"], supported_documents: ["nfe"],
    projection: {available_surfaces: ["overview", "webhook-egress"]},
  }}));
  await page.route("**/v1/portal/egress/tenant-a/unit-a/homologation/synthetic-events", (route) => route.fulfill({json: {
    url: "https://consumer.example.test/fiscal/webhooks", version: 1, approval_status: "pending", enabled: true,
  }}));
  await page.route("**/v1/portal/egress/tenant-a/unit-a/homologation/synthetic-events/approved", (route) => {
    expect(route.request().postDataJSON().expected_version).toBe(1);
    expect(route.request().headers()["x-csrf-token"]).toBe("synthetic-csrf");
    expect(route.request().headers()["idempotency-key"].length).toBeGreaterThan(10);
    return route.fulfill({json: {version: 2, approval_status: "approved"}});
  });
  await page.goto("/"); await page.getByRole("button", {name: "Aprovação de saída"}).click();
  for (const [field, value] of Object.entries({tenant: "tenant-a", unit: "unit-a", environment: "homologation", destination: "synthetic-events"})) await page.locator(`#configuration-egress-${field}`).fill(value);
  await page.getByRole("button", {name: "Consultar solicitação"}).click();
  await expect(page.locator("#egress-decision-form")).toBeVisible();
  await page.locator("#configuration-egress-expiry").fill("2026-10-07T12:00:00Z");
  await page.getByRole("button", {name: "Aprovar saída"}).click();
  await expect(page.locator("#egress-review-form [role=status]")).toContainText("Decisão aprovada registrada · versão 2");
});


test("tenant admin user management exposes only approved delegated roles and server-owned authority", async ({page, context}) => {
  await context.addCookies([
    {name: "nfcore_session", value: "synthetic-session", domain: "127.0.0.1", path: "/"},
    {name: "nfcore_csrf", value: "synthetic-csrf", domain: "127.0.0.1", path: "/"},
  ]);
  await page.route("**/v1/portal/bootstrap", (route) => route.fulfill({json: {
    tenant_id: "tenant-a", role: "admin", platform_admin: false,
    unit_ids: ["unit-a"], permissions: ["portal.read", "user.manage"],
    supported_documents: ["nfe"],
    projection: {
      available_surfaces: ["overview", "users"],
      authorized_units: [{unit_id: "unit-a", display_name: "Unit A", environments: ["homologation"]}],
    },
  }}));
  await page.route("**/v1/portal/surfaces/users*", (route) => route.fulfill({json: {
    surface: "users",
    rows: [
      {account_id: "admin-a", email: "admin@example.com", role: "admin", unit_ids: ["unit-a"], enabled: true, platform_admin: false, version: 0, mutable: false},
      {account_id: "operator-a", email: "operator@example.com", role: "operator", unit_ids: ["unit-a"], enabled: true, platform_admin: false, version: 0, mutable: true},
    ],
  }}));

  let command = null;
  await page.route("**/v1/portal/operations/createUser", async (route) => {
    command = route.request().postDataJSON();
    expect(route.request().headers()["x-csrf-token"]).toBe("synthetic-csrf");
    expect(route.request().headers()["idempotency-key"].length).toBeGreaterThan(10);
    await route.fulfill({json: {
      account_id: "billing-a", email: "billing@example.com", role: "billing",
      unit_ids: ["unit-a"], enabled: true, platform_admin: false, version: 0,
      created: true, replay: false, activation: "password_recovery",
    }});
  });

  await page.goto("/");
  await page.getByRole("button", {name: "Usuários", exact: true}).click();
  await expect(page.locator("#user-administration-form")).toBeVisible();

  const roleOptions = await page.locator("#user-target-role option").allTextContents();
  expect(roleOptions).toEqual(["Operador", "Auditor", "Cobrança"]);

  await page.locator("#user-administration-form input[type=email]").fill("billing@example.com");
  await page.locator("#user-target-role").selectOption("billing");
  await page.locator("#user-target-units").fill("unit-a");
  await page.getByRole("button", {name: "Criar usuário"}).click();

  await expect.poll(() => command).not.toBeNull();
  expect(command).toEqual({
    email: "billing@example.com",
    target_role: "billing",
    target_unit_ids: ["unit-a"],
  });
  expect(command.tenant_id).toBeUndefined();
  expect(command.platform_admin).toBeUndefined();
});


for (const width of [320, 390, 1280]) {
  test(`operational navigation prioritizes the workspace at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/v1/portal/bootstrap", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        tenant_id: "synthetic-ux", role: "owner", platform_admin: false,
        unit_ids: ["unit-a"], permissions: ["portal.read"],
        projection: {
          production_state: "HUMAN_APPROVAL_REQUIRED",
          authorized_units: [{ unit_id: "unit-a", display_name: "Synthetic unit", environments: ["homologation"] }],
          available_surfaces: ["overview", "documents", "issuances", "onboarding", "units", "support"],
        },
      }),
    }));
    await page.route("**/v1/portal/surfaces/**", (route) => route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ rows: [{ unit_id: "unit-a", display_name: "Synthetic unit" }] }),
    }));
    await page.route("**/v1/portal/fiscal-intents**", (route) => route.fulfill({
      status: 200, contentType: "application/json", body: '{"rows":[]}',
    }));

    await page.goto("/");
    const readiness = page.locator("#critical-state");
    await expect(page.locator(".product-banner")).toHaveCount(0);
    await expect(readiness).toContainText("Aguardando aprovação humana");

    // A user leaving a scrolled overview must see tools immediately.
    await page.evaluate(() => window.scrollTo({ top: 600, behavior: "instant" }));
    for (const name of ["Documentos", "Emissões", "Configuração inicial", "Unidades", "Suporte"]) {
      await page.getByRole("button", { name, exact: true }).click();
      await expect(readiness).toBeVisible();
      await expect(readiness).toContainText("Aguardando aprovação humana");
      await expect(page.locator("#workspace .panel").first()).toBeVisible();
      const workspaceTop = await page.locator("#workspace").evaluate((element) => element.getBoundingClientRect().top);
      expect(workspaceTop).toBeGreaterThanOrEqual(0);
      expect(workspaceTop).toBeLessThan(900);
      await expect(page.locator("#app-shell")).toHaveClass(/is-operational-view/);
    }

    await page.getByRole("button", { name: "Visão geral", exact: true }).click();
    await expect(readiness).toBeVisible();
    await expect(page.locator("#app-shell")).not.toHaveClass(/is-operational-view/);
  });
}


test("RTC-02 owner declares Lucro Presumido explicitly and reads persisted status", async ({ page, context }) => {
  const issuer = {
    record_type: "rtc_issuer", status: "profile_effective",
    legal_name: "Empresa Sintetica", crt: 3, primary_cnae: "8011101",
    state_code: "SP", municipality_ibge_code: "3509205",
    profile_version: 1, effective_from: "2026-01-01T00:00:00Z",
    federal_regime_status: "declaration_not_configured",
  };
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    tenant_id: "tenant-e2e", unit_ids: ["unit-a"], role: "owner",
    permissions: ["portal.read", "configuration.write"], supported_documents: ["nfse"],
    projection: {authorized_units: [{unit_id: "unit-a", display_name: "Synthetic unit",
      environments: ["homologation"]}]},
  }}));
  await page.route("**/v1/portal/surfaces/**", route => route.fulfill({json: {
    rows: route.request().url().includes("/tax-reform") ? [issuer] : [],
  }}));
  await page.route("**/v1/portal/operations/declareFederalRegime", route => {
    expect(route.request().postDataJSON()).toEqual({
      unit_id: "unit-a", environment: "homologation",
      federal_income_tax_regime: "lucro_presumido", effective_from: "2026-01-01",
      source_reference: "ECF synthetic evidence",
    });
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf-e2e");
    expect(route.request().headers()["idempotency-key"]).toBeTruthy();
    Object.assign(issuer, {
      federal_regime_status: "declared", federal_income_tax_regime: "lucro_presumido",
      federal_regime_version: 1, federal_regime_effective_from: "2026-01-01T00:00:00-03:00",
    });
    return route.fulfill({json: {status: "declared", version: 1}});
  });
  await context.addCookies([
    {name: "nfcore_session", value: "opaque-session", domain: "127.0.0.1", path: "/"},
    {name: "nfcore_csrf", value: "csrf-e2e", domain: "127.0.0.1", path: "/"},
  ]);
  await page.goto("/");
  await page.getByRole("button", {name: "Reforma Tributária", exact: true}).click();
  const form = page.getByRole("form", {name: "Declarar regime federal"});
  const regime = form.locator("select[name=federal_income_tax_regime]");
  await expect(regime).toHaveValue("");
  await expect(regime.locator("option[value=lucro_presumido]")).toHaveCount(1);
  await expect(regime.locator("option[value=lucro_real]")).toHaveCount(1);
  await expect(regime.locator("option[value=simples_nacional]")).toHaveCount(0);
  await regime.selectOption("lucro_presumido");
  await form.locator("input[type=date]").fill("2026-01-01");
  await form.locator("input[autocomplete=off]").fill("ECF synthetic evidence");
  await form.getByRole("button", {name: "Declarar regime federal"}).click();
  await expect(page.getByText("Regime federal declarado: Lucro Presumido, desde 2026-01-01 (versão 1).")).toBeVisible();
});

test("radar uses selected unit and shows missing estimates and coverage", async ({page, context}) => {
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    tenant_id: "tenant-e2e", unit_ids: ["unit-a"], role: "owner",
    permissions: ["portal.read", "document.query", "audit.read"], supported_documents: ["nfse"],
    projection: {authorized_units: [{unit_id: "unit-a", display_name: "Unidade A", environments: ["homologation"]}]},
  }}));
  await context.addCookies([{name: "nfcore_csrf", value: "csrf-e2e", domain: "127.0.0.1", path: "/"}]);
  await page.route("**/v1/portal/surfaces/**", route => route.fulfill({json: {rows: []}}));
  await page.route("**/v1/portal/cognitive/economy/opportunity-radar", route => {
    expect(route.request().postDataJSON()).toEqual({unit_id: "unit-a", environment: "homologation", competence: "2026-11-01"});
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf-e2e");
    return route.fulfill({json: {opportunities: [{legal_act: "Ato de teste", estimated_cents: null}],
      coverage: {municipal: {status: "advisory"}, state: {status: "insufficient_basis"}},
      public_signals: []}});
  });
  await page.goto("/");
  await page.getByRole("button", {name: "Reforma Tributária", exact: true}).click();
  await page.getByLabel("Competência", {exact: true}).fill("2026-11");
  await page.getByRole("button", {name: "Consultar oportunidades da unidade"}).click();
  await expect(page.getByText("Ato de teste — sem estimativa")).toBeVisible();
  await expect(page.getByText("Estadual — faltam dados revisados")).toBeVisible();
});

test("quarterly simulator submits only the selected scope and period", async ({page, context}) => {
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    tenant_id: "tenant-e2e", unit_ids: ["unit-a"], role: "owner",
    permissions: ["portal.read", "document.query", "audit.read"], supported_documents: ["nfe"],
    projection: {authorized_units: [{unit_id: "unit-a", display_name: "Unidade A", environments: ["homologation"]}]},
  }}));
  await context.addCookies([{name: "nfcore_csrf", value: "csrf-e2e", domain: "127.0.0.1", path: "/"}]);
  await page.route("**/v1/portal/surfaces/**", route => route.fulfill({json: {rows: []}}));
  await page.route("**/v1/portal/cognitive/economy/quarterly-simulation", route => {
    const body = route.request().postDataJSON();
    expect(body).toEqual({unit_id: "unit-a", environment: "homologation", competence: expect.stringMatching(/^2026-(01|04)-01$/)});
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf-e2e");
    if (body.competence === "2026-04-01") return route.fulfill({json: {status: "insufficient_basis"}});
    const income = {irpj: 1057500, additional_irpj: 105000, csll: 621000};
    return route.fulfill({json: {status: "simulated", review_reference: "trimestre-revisado",
      lucro_presumido: income, lucro_real: income, months: [{competence: "2026-01-01",
        cumulative: {pis: 650, cofins: 3000}, noncumulative: {pis_balance: -350, cofins_balance: 1600},
        regular_vat: {ibs_balance: 80, cbs_balance: 750}}]}});

  });
  await page.goto("/");
  await page.getByRole("button", {name: "Reforma Tributária", exact: true}).click();
  await page.getByRole("button", {name: "Simular trimestre"}).click();
  await expect(page.getByText("Cenários consultivos · Revisão trimestre-revisado")).toBeVisible();
  await expect(page.getByText(/2026-01 · PIS\/Cofins cumulativos/)).toBeVisible();
  await page.getByLabel("Trimestre de 2026").selectOption("2026-04-01");
  await page.getByRole("button", {name: "Simular trimestre"}).click();
  await expect(page.getByText("Falta uma base contábil revisada para esta unidade e trimestre.")).toBeVisible();
});

test("annual regime comparison presents reviewed scenarios and insufficient basis", async ({page, context}) => {
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    tenant_id: "tenant-e2e", unit_ids: ["unit-a"], role: "owner",
    permissions: ["portal.read", "document.query", "audit.read"], supported_documents: ["nfe"],
    projection: {authorized_units: [{unit_id: "unit-a", display_name: "Unidade A", environments: ["homologation"]}]},
  }}));
  await context.addCookies([{name: "nfcore_csrf", value: "csrf-e2e", domain: "127.0.0.1", path: "/"}]);
  await page.route("**/v1/portal/surfaces/**", route => route.fulfill({json: {rows: []}}));
  let requests = 0;
  await page.route("**/v1/portal/cognitive/economy/annual-regime-comparison", route => {
    expect(route.request().postDataJSON()).toEqual({unit_id: "unit-a", environment: "homologation", competence: "2026-01-01"});
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf-e2e");
    if (++requests > 1) return route.fulfill({json: {status: "insufficient_basis"}});
    const totals = {simples_nacional: 1860012, lucro_presumido: 2079600, lucro_real: 2118000};
    const delta = {simples_nacional: 0, lucro_presumido: 0, lucro_real: 72000};
    return route.fulfill({json: {status: "compared",
      scenarios: {baseline: {annual_tax_cents: totals, revenue_cents: 12000000, payroll_cents: 2400000, real_accounting_result_cents: 1200000}},
      sensitivity_tax_delta_cents: {margin: delta, payroll: delta},
      recommendation: {candidates: ["simples_nacional"], sensitivity_stable: true}}});
  });
  await page.goto("/");
  await page.getByRole("button", {name: "Reforma Tributária", exact: true}).click();
  await page.getByRole("button", {name: "Comparar regimes de 2026"}).click();
  await expect(page.getByText(/Menor carga estimada: Simples Nacional/)).toBeVisible();
  await expect(page.getByText(/Lucro Real trimestral · Carga anual/)).toBeVisible();
  await page.getByRole("button", {name: "Comparar regimes de 2026"}).click();
  await expect(page.getByText("Falta base revisada comparável para o ano e a unidade.")).toBeVisible();
});
