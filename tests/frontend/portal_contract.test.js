import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const html = await readFile(new URL("../../portal/index.html", import.meta.url), "utf8");
const script = await readFile(new URL("../../portal/app.js", import.meta.url), "utf8");
const styles = await readFile(new URL("../../portal/styles.css", import.meta.url), "utf8");
const runtimeStyles = await readFile(new URL("../../portal/runtime.css", import.meta.url), "utf8");


test("portal uses authenticated backend contracts", () => {
  assert.match(script, /\/v1\/auth\/login/);
  assert.match(script, /\/v1\/portal\/bootstrap/);
  assert.match(script, /\/v1\/portal\/surfaces\//);
  assert.match(script, /\/v1\/portal\/operations\//);
  assert.match(script, /credentials: "same-origin"/);
});


test("browser never supplies tenant or role authority", () => {
  assert.doesNotMatch(script, /X-FM-Tenant-Id/);
  assert.doesNotMatch(script, /X-FM-Unit-Id/);
  assert.doesNotMatch(script, /localStorage/);
  assert.doesNotMatch(script, /sessionStorage/);
  assert.match(html, /O navegador nunca é autoridade/);
});


test("mutations carry CSRF and idempotency controls", () => {
  assert.match(script, /X-CSRF-Token/);
  assert.match(script, /Idempotency-Key/);
  assert.match(script, /crypto\.randomUUID\(\)/);
  assert.match(script, /onboardUnit/);
});


test("portal keeps accessible login and governed operation surfaces", () => {
  assert.match(html, /id="login-form"/);
  assert.match(html, /autocomplete="username"/);
  assert.match(html, /autocomplete="current-password"/);
  assert.match(html, /aria-labelledby="operation-dialog-title"/);
  assert.match(html, /role="alert"/);
  assert.doesNotMatch(html, /Payload JSON/);
  assert.match(html, /id="operation-access-key"/);
  assert.match(html, /id="operation-authorization-protocol"/);
  assert.match(html, /id="operation-inutilization-field"/);
  assert.match(script, /operationPayloadForSelection/);
});


test("commercial recovery is browser-usable without exposing reset token on request", () => {
  assert.match(html, /id="forgot-password-action"/);
  assert.match(html, /id="password-reset-request-form"/);
  assert.match(html, /autocomplete="new-password"/);
  assert.match(html, /minlength="12"/);
  assert.match(html, /maxlength="1024"/);
  assert.match(html, /aria-describedby="password-policy"/);
  assert.match(html, /gerenciadores de senha são aceitas/);
  assert.match(script, /PASSWORD_POLICY_INVALID/);
  assert.match(script, /PASSWORD_RESET_NOT_USABLE/);
  assert.match(script, /\/v1\/auth\/password-reset\/request/);
  assert.match(script, /\/v1\/auth\/password-reset\/complete/);
  assert.match(script, /reset_token/);
  assert.doesNotMatch(script, /console\.log/);
});


test("navigation is constrained by backend-declared durable surfaces", () => {
  assert.match(script, /available_surfaces/);
  assert.match(script, /availableSurfaces\(\)/);
  assert.match(script, /allowed === null \|\| allowed\.has\(id\)/);
});


test("premium design system preserves responsive and accessibility contracts", () => {
  assert.match(styles, /--brand-primary:/);
  assert.match(styles, /--brand-cyan:/);
  assert.match(styles, /--radius-lg:/);
  assert.match(styles, /@media \(max-width: 760px\)/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(runtimeStyles, /:focus-visible/);
  assert.match(runtimeStyles, /button:disabled/);
  assert.match(runtimeStyles, /prefers-contrast: more/);
  assert.match(runtimeStyles, /prefers-reduced-motion: reduce/);
});


test("platform pricing administration is backend-authorized and zero-code", () => {
  assert.match(script, /pricing-admin/);
  assert.match(script, /\/v1\/admin\/pricing/);
  assert.match(script, /expected_version/);
  assert.match(script, /X-CSRF-Token/);
  assert.match(script, /platform_admin/);
  assert.match(script, /Sem preço comercial publicado|UNPRICED/);
  assert.doesNotMatch(script, /base_amount\s*:\s*["']\d/);
});


test("commercial release governance is explicit, human-controlled and separated from checkout", () => {
  assert.match(script, /commercial-release/);
  assert.match(script, /\/v1\/admin\/commercial-release/);
  assert.match(script, /commercial_approved/);
  assert.match(script, /human_decision_reference/);
  assert.match(script, /A aprovação comercial nunca é inferida/);
  assert.match(script, /Pagamento e produção fiscal permanecem autoridades separadas/);
});


test("Cakto checkout administration reuses governed bindings without secret material", () => {
  assert.match(script, /checkout-admin/);
  assert.match(script, /\/v1\/admin\/checkout\/cakto/);
  assert.match(script, /cakto:\/\/PRODUCT_ID\/OFFER_ID/);
  assert.match(script, /X-CSRF-Token/);
  assert.match(script, /Client secret, token e webhook secret nunca pertencem/);
  assert.doesNotMatch(script, /client_secret\s*[:=]/i);
});

test("activation delivery consumes the reset token from the URL fragment", () => {
  assert.match(script, /window\.location\.hash/);
  assert.match(script, /fragment\.get\("token"\)/);
  assert.match(script, /fragment\.delete\("token"\)/);
});

test("tenant user administration is session-authorized and cannot grant platform authority", () => {
  assert.match(script, /createUser/);
  assert.match(script, /updateUser/);
  assert.match(script, /user\.manage/);
  assert.match(script, /user-administration-form/);
  assert.match(script, /target_role/);
  assert.match(script, /target_unit_ids/);
  assert.match(script, /administrador da plataforma não pode ser concedido aqui/);
  assert.match(script, /sessões anteriores revogadas/);
  assert.doesNotMatch(script, /platform_admin\s*:\s*true/);
});

test("billing plans and usage remain read-only canonical projections", () => {
  assert.match(script, /usage.*Uso/);
  assert.match(script, /billing.*Cobrança/);
  assert.match(script, /plans.*Planos/);
  assert.match(script, /autoridades comerciais canônicas do NFCore/);
  assert.match(script, /Gateways externos permanecem adaptadores/);
  assert.doesNotMatch(script, /updateSubscription|setBillingStatus|recordUsage/);
});

test("customer configuration forms use existing portal commands and distinguish approval from delivery", () => {
  for (const operation of ["configureCertificates", "configureProviders", "configureWebhooks", "configureIntegrations", "configureSettings"]) assert.ok(script.includes(operation));
  assert.match(script, /customer_configuration_operations/);
  assert.match(script, /customer-configuration-form/);
  assert.match(script, /Verificação operacional não confirmada/);
  assert.match(script, /Solicitar entrega após aprovação da plataforma/);
  assert.match(script, /egress-decision-form/);
  assert.match(script, /if \(!bootstrapState\?\.platform_admin\) return/);
});


test("password visibility and creation guidance use the canonical policy", () => {
  assert.ok(html.includes('id="login-password-guidance"'));
  assert.ok(html.includes("12 a 1.024 caracteres"));
  assert.ok(html.includes("letras, números, espaços e símbolos são aceitos"));
  assert.ok(html.includes('data-password-toggle="login-password"'));
  assert.ok(html.includes('data-password-toggle="password-reset-new-password"'));
  assert.ok(html.includes('aria-pressed="false"'));
  assert.ok(script.includes('input.type = show ? "text" : "password"'));
  assert.ok(script.includes('button.setAttribute("aria-pressed", String(show))'));
});

test("user administration keeps success acknowledgement after refreshed workspace", () => {
  assert.match(script, /await renderSurface\("users"\);\s*\/\/ Re-render replaces the form/);
  assert.match(script, /workspace\.querySelector\("#user-administration-form \[role='status'\]"\)/);
  assert.match(script, /visibleStatus\.textContent = confirmation/);
});

test("outdated portal requests cannot overwrite current navigation on success or error", () => {
  assert.match(script, /const response = await api\(`\/v1\/portal\/surfaces\/.*?\n\s*\/\/ A prior request cannot overwrite/);
  assert.match(script, /if \(generation !== surfaceGeneration\) return;\s*const grid/);
  assert.match(script, /catch \(error\) \{\s*if \(generation !== surfaceGeneration\) return;\s*loading\.textContent/);
});

test("fiscal actions require current authorized unit and environment", () => {
  assert.match(script, /const authorizedScope = authorizedFiscalUnits\(\)\.some/);
  assert.match(script, /unit\.unit_id === selectedFiscalUnit && unit\.environments\.includes\(selectedFiscalEnvironment\)/);
  assert.match(script, /option\.disabled = !authorizedScope \|\| !configured\.includes\(option\.value\)/);
});


test("RTC screen uses the existing authenticated scoped portal and does not invent tax results", () => {
  assert.match(script, /\["tax-reform", "Reforma Tributária"\]/);
  assert.match(script, /appendRtcIssuerSummary\(article, rows\)/);
  assert.match(script, /issuer\.status === "profile_effective"/);
  assert.match(script, /Lucro Real \/ Presumido \/ Simples/);
  assert.match(script, /O CRT não define sozinho o regime de IRPJ\/CSLL/);
  assert.match(script, /nenhuma emissão ou cálculo fiscal é executado nesta tela/);
  assert.doesNotMatch(script, /\/v1\/rtc\/calculate/);
});


test("RTC issuer profile enrollment uses governed portal operation and no browser tenant authority", () => {
  assert.match(script, /registerFiscalProfile/);
  assert.match(script, /rtc-profile-registration/);
  assert.match(script, /configuration\.write/);
  assert.match(script, /Idempotency-Key/);
  assert.match(script, /X-CSRF-Token/);
  assert.match(script, /state_registration_exempt/);
  assert.match(script, /unit_id: selectedFiscalUnit/);
  assert.match(script, /environment: selectedFiscalEnvironment/);
  assert.doesNotMatch(script, /tenant_id:\s*.*payload/);
  assert.doesNotMatch(script, /localStorage/);
});

test("cognitive advisor is advisory-only, session-scoped and renders model text as plain text", () => {
  const start = script.indexOf("function appendCognitiveAdvisor");
  assert.ok(start > 0);
  const advisor = script.slice(start);
  assert.match(advisor, /\/v1\/portal\/cognitive\/advise/);
  assert.match(advisor, /X-CSRF-Token/);
  assert.match(advisor, /Idempotency-Key/);
  assert.match(advisor, /unit_id: selectedFiscalUnit/);
  // Authority comes from the session: the browser never sends tenant, role or permissions.
  assert.doesNotMatch(advisor, /tenant_id|permissions|host_namespace/);
  // Model/provider text must never be interpreted as markup.
  assert.doesNotMatch(advisor, /innerHTML|insertAdjacentHTML|outerHTML/);
  assert.match(advisor, /Requer aprovação humana/);
  assert.match(advisor, /IA desligada/);
  // Only the two read-only explanation views expose the panel.
  assert.match(script, /viewId === "errors" \|\| viewId === "reconciliation"\) appendCognitiveAdvisor/);
});
