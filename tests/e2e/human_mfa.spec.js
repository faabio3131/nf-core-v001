import { expect, test } from "@playwright/test";

const BOOT = {
  tenant_id: "synthetic", unit_ids: ["unit"], role: "owner",
  permissions: ["portal.read", "configuration.write"], supported_documents: ["nfe"],
  projection: {available_surfaces: ["overview"]},
};

test("login asks for the app, enrolls, shows recovery codes and remembers nothing unasked", async ({ page, context }) => {
  await context.addCookies([{name: "nfcore_csrf", value: "mfa-csrf", domain: "127.0.0.1", path: "/"}]);
  let signedIn = false;
  await page.route("**/v1/portal/bootstrap", route => signedIn
    ? route.fulfill({json: BOOT})
    : route.fulfill({status: 401, json: {detail: {code: "SESSION_REQUIRED"}}}));
  await page.route("**/v1/portal/surfaces/**", route => route.fulfill({json: {rows: []}}));
  await page.route("**/v1/auth/login", route => route.fulfill({json: {mfa: {challenge: "c".repeat(43), purpose: "enroll"}}}));
  await page.route("**/v1/auth/mfa/enroll/start", route => {
    expect(route.request().postDataJSON()).toEqual({challenge: "c".repeat(43)});
    return route.fulfill({json: {secret_base32: "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/x",
      qr_data_uri: "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%2F%3E"}});
  });
  let confirmed = null;
  await page.route("**/v1/auth/mfa/enroll/confirm", route => {
    confirmed = route.request().postDataJSON();
    if (confirmed.code === "000000") {
      return route.fulfill({status: 401, json: {detail: {code: "MFA_INVALID_CODE"}}});
    }
    signedIn = true;
    return route.fulfill({json: {recovery_codes: ["ABCDE-FGHJK", "LMNPQ-RSTUV"], account: {}}});
  });
  await page.goto("/");
  await page.getByLabel("E-mail").first().fill("dono@empresa.com.br");
  await page.locator("#login-password").fill("Senha-forte-para-teste-1");
  await page.getByRole("button", {name: "Entrar"}).click();
  await expect(page.getByText(/ative o app autenticador/)).toBeVisible();
  await expect(page.locator("#mfa-secret")).toHaveText("JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP");
  await expect(page.getByAltText("QR code para o app autenticador")).toBeVisible();
  await page.locator("#mfa-code").fill("000000");
  await page.locator("#mfa-submit").click();
  await expect(page.getByText(/Código incorreto ou já usado/)).toBeVisible();
  await page.locator("#mfa-code").fill("123 456");
  await page.locator("#mfa-submit").click();
  expect(confirmed).toEqual({challenge: "c".repeat(43), code: "123456", remember_device: false});
  await expect(page.getByText("ABCDE-FGHJK")).toBeVisible();
  await page.getByRole("button", {name: "Já guardei os códigos"}).click();
  await expect(page.locator("#app-shell")).toBeVisible();
});

test("a sensitive operation asks for a fresh code and is retried once", async ({ page, context }) => {
  await context.addCookies([{name: "nfcore_csrf", value: "mfa-csrf", domain: "127.0.0.1", path: "/"}]);
  await page.route("**/v1/portal/bootstrap", route => route.fulfill({json: BOOT}));
  await page.route("**/v1/portal/surfaces/**", route => route.fulfill({json: {rows: []}}));
  await page.route("**/v1/auth/me", route => route.fulfill({json: {account: {role: "owner"}}}));
  await page.route("**/v1/auth/mfa/status", route => route.fulfill({json: {
    required: true, enrolled: true, recovery_codes_remaining: 7, tenant_requires_all: false, step_up_active: false,
  }}));
  let stepped = false;
  let policyCalls = 0;
  await page.route("**/v1/auth/mfa/step-up", route => {
    expect(route.request().headers()["x-csrf-token"]).toBe("mfa-csrf");
    expect(route.request().postDataJSON()).toEqual({code: "654321"});
    stepped = true;
    return route.fulfill({json: {step_up: "active"}});
  });
  await page.route("**/v1/auth/mfa/policy", route => {
    policyCalls += 1;
    if (!stepped) return route.fulfill({status: 403, json: {detail: {code: "STEP_UP_REQUIRED"}}});
    expect(route.request().postDataJSON()).toEqual({require_all: true});
    return route.fulfill({json: {tenant_requires_all: true}});
  });
  await page.goto("/");
  await page.getByRole("button", {name: "Segurança"}).click();
  await expect(page.getByText("Códigos de recuperação restantes: 7.")).toBeVisible();
  await page.getByRole("button", {name: "Exigir app autenticador de todos"}).click();
  await expect(page.getByRole("heading", {name: "Confirme com o app autenticador"})).toBeVisible();
  await page.locator("#step-up-code").fill("654321");
  await page.locator("#step-up-form").getByRole("button", {name: "Confirmar"}).click();
  await expect(page.getByText("Agora todos da empresa precisam do app autenticador.")).toBeVisible();
  expect(policyCalls).toBe(2);
});
