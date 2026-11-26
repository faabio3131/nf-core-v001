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
    ++requests;
    if (requests === 3) return route.fulfill({json: {status: "insufficient_basis"}});
    if (requests === 4) return route.fulfill({status: 422, json: {detail: {code: "ANNUAL_COMPARISON_EVIDENCE_INVALID"}}});
    if (requests === 5) return route.fulfill({status: 503, json: {detail: {code: "UNAVAILABLE"}}});
    const totals = {simples_nacional: 1860012, lucro_presumido: 2079600, lucro_real: 2118000};
    const delta = {simples_nacional: 0, lucro_presumido: 0, lucro_real: 72000};
    const tax = {icms: 0, iss: 0, employer_contributions: 0, other_mandatory_taxes: 0, rtc_net_increment: 0};
    const scenario = {annual_tax_cents: totals, revenue_cents: 12000000, payroll_cents: 2400000, real_accounting_result_cents: 1200000,
      accounting_margin_bps: 1000, qualifying_payroll_bps: 2000,
      months: [{gross_rtc: {ibs_balance: 100, cbs_balance: 900}, outside: {simples_nacional: tax, lucro_presumido: tax, lucro_real: tax}}]};
    return route.fulfill({json: {status: "compared", source_mode: "linked_t11_snapshots",
      snapshot: {version: 2, digest: "a".repeat(64)}, registered_regime_by_month: {"2026-01-01": "simples_nacional"},
      scenarios: {baseline: scenario, margin: scenario, payroll: scenario},
      sensitivity_tax_delta_cents: {margin: delta, payroll: {...delta, simples_nacional: -665007}},
      recommendation: {status: requests === 2 ? "tie" : "review_required",
        candidates: requests === 2 ? ["simples_nacional", "lucro_presumido"] : ["simples_nacional"],
        sensitivity_stable: requests !== 2}}});
  });
  await page.goto("/");
  await page.getByRole("button", {name: "Reforma Tributária", exact: true}).click();
  await page.getByRole("button", {name: "Comparar regimes de 2026"}).click();
  await expect(page.getByText(/Menor carga estimada: Simples Nacional/)).toBeVisible();
  await expect(page.getByText(/Lucro Real trimestral · Carga anual/)).toBeVisible();
  await expect(page.getByText(/Regime cadastrado por competência/)).toBeVisible();
  await expect(page.getByText(/Snapshot revisado: versão 2/)).toBeVisible();
  await page.getByText("Limites do comparador", {exact: true}).click();
  await expect(page.getByText(/Não contempla majoração/)).toBeVisible();
  await page.getByText("Tributos externos e RTC bruto por cenário", {exact: true}).click();
  await expect(page.getByText(/Base · Margem 10%/)).toBeVisible();
  await page.getByRole("button", {name: "Comparar regimes de 2026"}).click();
  await expect(page.getByText(/Empate técnico — revisão contábil obrigatória/)).toBeVisible();
  await expect(page.getByText(/Ranking nos cenários alternativos: variável/)).toBeVisible();
  await expect(page.getByText(/Simples Nacional · Carga anual.*-R/)).toBeVisible();
  await page.getByRole("button", {name: "Comparar regimes de 2026"}).click();
  await expect(page.getByText("Falta base revisada comparável para o ano e a unidade.")).toBeVisible();
  await page.getByRole("button", {name: "Comparar regimes de 2026"}).click();
  await expect(page.getByText(/Falha HTTP 422|ANNUAL_COMPARISON_EVIDENCE_INVALID/)).toBeVisible();
  await expect(page.getByText(/Menor carga estimada/)).toHaveCount(0);
  await page.getByRole("button", {name: "Comparar regimes de 2026"}).click();
  await expect(page.getByText(/Falha HTTP 503|UNAVAILABLE/)).toBeVisible();
  await expect(page.getByText(/Menor carga estimada/)).toHaveCount(0);
});

test("accounting review exposes immutable decision and requires step-up before approval", async ({page, context}) => {
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: {
    tenant_id: "tenant-e2e", unit_ids: ["unit-a"], role: "accountant",
    permissions: ["portal.read", "document.query", "audit.read"], supported_documents: ["nfse"],
    projection: {authorized_units: [{unit_id: "unit-a", display_name: "Unidade A", environments: ["homologation"]}]},
  }}));
  await context.addCookies([{name: "nfcore_csrf", value: "csrf-e2e", domain: "127.0.0.1", path: "/"}]);
  await page.route("**/v1/portal/surfaces/**", route => route.fulfill({json: {rows: []}}));
  const subject = {kind: "benefit", benefit_id: "municipal-rule", source: "municipal",
    benefit_version: 1, snapshot_id: "facts", snapshot_version: 1,
    benefit_digest: "a".repeat(64), snapshot_digest: "b".repeat(64),
    estimated_cents: 1000, result_digest: "c".repeat(64),
    candidate: {citation: {act: "Ato sintetico", provision: "Art. 1",
      source_url: "https://example.gov.br/test", source_sha256: "f".repeat(64)},
      fact_review_reference: "reviewed-facts"}};
  const selection = {unit_id: "unit-a", environment: "homologation", competence: "2026-11-01",
    target: {kind: "benefit", source: "municipal", benefit_id: "municipal-rule"}};
  await page.route("**/v1/portal/cognitive/economy/opportunity-radar", route => route.fulfill({json: {
    opportunities: [{...subject, legal_act: "Ato sintetico", status: "potential"}],
    coverage: {municipal: {status: "advisory"}}, public_signals: [],
  }}));
  let confirmed = false;
  let requestId;
  await page.route("**/v1/auth/mfa/step-up", route => {
    confirmed = true;
    return route.fulfill({json: {step_up_active: true}});
  });
  await page.route("**/v1/portal/cognitive/economy/accounting-review", route => {
    const body = route.request().postDataJSON();
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf-e2e");
    const base = {subject, subject_digest: "d".repeat(64), current_version: 0, status: "pending",
      can_decide: true, latest: null, history: [], next_before_version: null, issuance_authorized: false};
    if (!body.command) {
      expect(body).toEqual(selection);
      return route.fulfill({json: base});
    }
    const {command, ...rest} = body;
    expect(rest).toEqual(selection);
    expect(command).toEqual({decision: "approved", subject_digest: "d".repeat(64),
      expected_version: 0, request_id: expect.any(String), opinion_reference: "parecer-teste",
      professional_reference: "CRC-TEST", rationale: "Parecer sintético de revisão contábil."});
    if (!confirmed) {
      requestId = command.request_id;
      return route.fulfill({status: 403, json: {detail: {code: "STEP_UP_REQUIRED"}}});
    }
    expect(command.request_id).toBe(requestId);
    const event = {...command, event_version: 1, event_digest: "e".repeat(64),
      actor_id: "accountant-test", recorded_at: "2026-11-24T12:00:00Z"};
    return route.fulfill({json: {...base, current_version: 1, status: "approved", history: [event], latest: event}});
  });
  await page.goto("/");
  await page.getByRole("button", {name: "Reforma Tributária", exact: true}).click();
  await page.getByLabel("Competência", {exact: true}).fill("2026-11");
  await page.getByRole("button", {name: "Consultar oportunidades da unidade"}).click();
  await page.getByRole("button", {name: "Consultar decisão contábil", exact: true}).click();
  await expect(page.getByText("Aguardando parecer", {exact: true})).toBeVisible();
  await page.getByLabel("Referência profissional (declarada, não verificada)").fill("CRC-TEST");
  await page.getByLabel("Referência do parecer").fill("parecer-teste");
  await page.getByLabel("Fundamentação").fill("Parecer sintético de revisão contábil.");
  await page.getByRole("button", {name: "Registrar decisão", exact: true}).click();
  await expect(page.locator("#step-up-dialog")).toBeVisible();
  await page.locator("#step-up-code").fill("123456");
  await page.locator("#step-up-form").evaluate(form => form.requestSubmit());
  await expect(page.getByText("Aprovado pelo contador", {exact: true})).toBeVisible();
  await expect(page.getByText(/Conta accountant-test/)).toBeVisible();
  await expect(page.getByText("Revogar aprovação", {exact: true})).toBeAttached();
});

test("T15 historical audit shows 60 months and paginated evidence without creating credits", async ({page, context}) => {
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json:{
    tenant_id:"tenant-e2e", unit_ids:["unit-a"], role:"auditor",
    permissions:["portal.read","document.query","audit.read"], supported_documents:["nfe"],
    projection:{authorized_units:[{unit_id:"unit-a", display_name:"Unidade A", environments:["homologation"]}]},
  }}));
  await context.addCookies([{name:"nfcore_csrf",value:"csrf-e2e",domain:"127.0.0.1",path:"/"}]);
  await page.route("**/v1/portal/surfaces/**", route => route.fulfill({json:{rows:[]}}));
  const digest="a".repeat(64), windowDigest="b".repeat(64);
  const month={competence:"2026-01-01",status:"reviewed_scope",document_count:12,item_count:36,pages:2,
    snapshot:{record_id:"history",version:2,digest},review_reference:"synthetic-review",as_of:"2026-11-24",
    groups:[{tax:"pis",collection:"direct",declared_cents:365,observed_paid_cents:365,
      reviewed_due_cents:235,paid_candidate_cents:130,status:"potential_undue_payment"}]};
  const months=Array.from({length:60},(_,i)=>{
    const dt=new Date(Date.UTC(2021,2+i,1)).toISOString().slice(0,10);
    return dt===month.competence?month:{competence:dt,status:"missing",document_count:null,
      item_count:null,snapshot:null,pages:0,groups:[]};
  });
  let queries=0;
  await page.route("**/v1/portal/cognitive/economy/historical-audit", route=>{
    const body=route.request().postDataJSON();
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf-e2e");
    expect(body.unit_id).toBe("unit-a");
    expect(body.environment).toBe("homologation");
    expect(body.competence).toBe("2026-02-01");
    if (!body.detail) {
      queries++;
      if (queries>1) return route.fulfill({status:503,json:{detail:{code:"HISTORICAL_AUDIT_UNAVAILABLE"}}});
      return route.fulfill({json:{window_start:"2021-03-01",window_end:"2026-02-01",
        reviewed_months:1,available_months:1,competences:60,status:"partial_basis",months,
        window_digest:windowDigest,partial_totals_by_tax:{pis:{classified_months:1,paid_candidate_cents:130},
          cofins:{classified_months:0,paid_candidate_cents:null},icms:{classified_months:0,paid_candidate_cents:null}},
        advisory_only:true,credit_recognized:false}});
    }
    expect(body.detail).toEqual({month:"2026-01-01",page:expect.any(Number),
      snapshot_digest:digest,window_digest:windowDigest});
    if (body.detail.page===1) return route.fulfill({status:409,json:{detail:{code:"HISTORICAL_AUDIT_CHANGED"}}});
    return route.fulfill({json:{page:0,next_page:1,rows:[{access_key:"1234567890",
      item_number:1,ncm:"30049099",cfop:"5102",tax:"pis",reason:"monophase_downstream",
      declared_cents:100,reviewed_due_cents:0,difference_cents:100,
      paid_candidate_cents:100,status:"potential_undue_payment",xml_sha256:"c".repeat(64),
      status_reference:"status",assessment_reference:"assessment",
      citation:{act:"Norma sintética",provision:"Art. 1",source_url:"https://www.gov.br/teste",
        source_sha256:"d".repeat(64)}}]}});
  });
  await page.goto("/");
  await page.getByRole("button",{name:"Reforma Tributária",exact:true}).click();
  await page.getByLabel("Última competência encerrada").fill("2026-02");
  await page.getByRole("button",{name:"Auditar histórico de 60 meses"}).click();
  await expect(page.getByText(/1\/60 competências reconciliadas/)).toBeVisible();
  await expect(page.getByRole("table",{name:"Competências e evidências"}).locator("tbody tr")).toHaveCount(60);
  await expect(page.getByText(/Cofins · Indícios em competências classificadas: Não disponível/)).toBeVisible();
  await page.getByRole("button",{name:"Detalhar 2026-01"}).click();
  await expect(page.getByText(/Item 1 · NCM 30049099.*Monofásico/)).toBeVisible();
  await expect(page.getByText(/Norma sintética · Art. 1/)).toBeVisible();
  await expect(page.getByText(/Página 1 de 2/)).toBeVisible();
  await page.getByRole("button",{name:"Próxima página de itens"}).click();
  await expect(page.getByText(/Consulte novamente a janela/)).toBeVisible();
  await page.getByRole("button",{name:"Auditar histórico de 60 meses"}).click();
  await expect(page.getByText(/Falha HTTP 503|HISTORICAL_AUDIT_UNAVAILABLE/)).toBeVisible();
  await expect(page.getByRole("table",{name:"Competências e evidências"})).toHaveCount(0);
});


test("T20 accountant downloads one source-bound sandbox dossier", async ({page, context}) => {
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json:{
    tenant_id:"tenant-e2e", unit_ids:["unit-a"], role:"accountant",
    permissions:["portal.read","document.query","audit.read"], supported_documents:["nfe"],
    projection:{authorized_units:[{unit_id:"unit-a", display_name:"Unidade A", environments:["homologation"]}]},
  }}));
  await context.addCookies([{name:"nfcore_csrf",value:"csrf-e2e",domain:"127.0.0.1",path:"/"}]);
  await page.route("**/v1/portal/surfaces/**", route => route.fulfill({json:{rows:[]}}));
  const finding="b".repeat(64), digest="a".repeat(64);
  const base={unit_id:"unit-a",environment:"homologation",competence:"2026-01-01"};
  await page.route("**/v1/portal/cognitive/economy/accounting-dossier/candidates", route => {
    expect(route.request().postDataJSON()).toEqual(base);
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf-e2e");
    return route.fulfill({json:{source:{record_id:"test-source",version:1,digest},as_of:"2026-11-24",
      candidates:[{finding_id:finding,tax:"pis",modality:"federal_undue_payment",estimated_cents:"371"}],
      credit_recognized:false,simulation_only:true}});
  });
  let downloads=0;
  await page.route("**/v1/portal/cognitive/economy/accounting-dossier/export", route => {
    expect(route.request().postDataJSON()).toEqual({...base,finding_id:finding,source_version:1,source_digest:digest});
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf-e2e");
    downloads++;
    // Browser transport fixture only; real ZIP/PDF/XLSX contents are tested in Python.
    return route.fulfill({status:200,contentType:"application/zip",body:"PK-synthetic-download"});
  });
  await page.goto("/");
  await page.getByRole("button",{name:"Reforma Tributária",exact:true}).click();
  await page.getByLabel("Competência do dossiê").fill("2026-01");
  await page.getByRole("button",{name:"Consultar achados para dossiê"}).click();
  await page.getByLabel("Achado para revisão").selectOption(finding);
  const download=page.waitForEvent("download");
  await page.getByRole("button",{name:"Exportar dossiê PDF/Excel/XML"}).click();
  expect((await download).suggestedFilename()).toBe("nfcore-dossie.zip");
  expect(downloads).toBe(1);
  await expect(page.getByText("Dossiê exportado. Revisão e assinatura do contador ainda pendentes.")).toBeVisible();
  await page.getByLabel("Competência do dossiê").fill("2026-02");
  await expect(page.getByRole("button",{name:"Exportar dossiê PDF/Excel/XML"})).toBeDisabled();
});
