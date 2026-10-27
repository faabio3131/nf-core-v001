import { expect, test } from "@playwright/test";

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
  await expect(page.locator("#critical-state-title")).toHaveText("BLOCKED_EXTERNAL");
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
    const banner = document.querySelector(".product-banner");
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
    const banner = document.querySelector(".product-banner");
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
});

for (const [view, label, operation, fields] of [
  ["certificates", "Certificados", "configureCertificates", {reference_id: "ref:synthetic-browser", kind: "certificate"}],
  ["providers", "Providers", "configureProviders", {binding_id: "synthetic-binding", document_kind: "nfe", state_code: "SP", operation: "authorize", provider_id: "synthetic"}],
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
    for (const [field, value] of Object.entries(fields)) await page.locator(`#configuration-${field}`).fill(value);
    await page.locator("#customer-configuration-form button[type=submit]").click();
    await expect(page.locator("#customer-configuration-form [role=status]")).toContainText("versão 1");
    expect(submitted.unit_id).toBe("unit-a"); expect(submitted.environment).toBe("homologation");
    expect(submitted.expected_version).toBe(0); expect(submitted.tenant_id).toBeUndefined();
    expect(submitted.platform_admin).toBeUndefined();
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
  await page.goto("/"); await page.getByRole("button", {name: "Aprovação de egress"}).click();
  for (const [field, value] of Object.entries({tenant: "tenant-a", unit: "unit-a", environment: "homologation", destination: "synthetic-events"})) await page.locator(`#configuration-egress-${field}`).fill(value);
  await page.getByRole("button", {name: "Consultar solicitação"}).click();
  await expect(page.locator("#egress-decision-form")).toBeVisible();
  await page.locator("#configuration-egress-expiry").fill("2026-10-07T12:00:00Z");
  await page.getByRole("button", {name: "Aprovar egress"}).click();
  await expect(page.locator("#egress-review-form [role=status]")).toContainText("Decisão approved registrada · versão 2");
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
  expect(roleOptions).toEqual(["OPERATOR", "AUDITOR", "BILLING"]);

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
    const banner = page.locator(".product-banner");
    const pillars = page.locator(".mission-strip");
    const readiness = page.locator("#critical-state");
    await expect(banner).toBeVisible();
    await expect(pillars).toBeVisible();
    await expect(readiness).toContainText("HUMAN_APPROVAL_REQUIRED");

    // A user leaving a scrolled overview must see tools immediately.
    await page.evaluate(() => window.scrollTo({ top: 600, behavior: "instant" }));
    for (const name of ["Documentos", "Emissões", "Onboarding", "Unidades", "Suporte"]) {
      await page.getByRole("button", { name, exact: true }).click();
      await expect(banner).toBeHidden();
      await expect(pillars).toBeHidden();
      await expect(readiness).toBeVisible();
      await expect(readiness).toContainText("HUMAN_APPROVAL_REQUIRED");
      await expect(page.locator("#workspace .panel").first()).toBeVisible();
      const workspaceTop = await page.locator("#workspace").evaluate((element) => element.getBoundingClientRect().top);
      expect(workspaceTop).toBeGreaterThanOrEqual(0);
      expect(workspaceTop).toBeLessThan(900);
      await expect(page.locator("#app-shell")).toHaveClass(/is-operational-view/);
    }

    await page.getByRole("button", { name: "Visão geral", exact: true }).click();
    await expect(banner).toBeVisible();
    await expect(pillars).toBeVisible();
    await expect(readiness).toBeVisible();
    await expect(page.locator("#app-shell")).not.toHaveClass(/is-operational-view/);
  });
}
