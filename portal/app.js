"use strict";

/** @typedef {{tenant_id:string, role:string, unit_ids:string[]|null, platform_admin:boolean, permissions:string[], supported_documents:string[], projection:Record<string, unknown>}} BootstrapState */
/** @typedef {{method?:string, headers?:Record<string,string>, body?:string}} ApiOptions */

const navigation = [
  { label: "Operação", items: [["overview", "Visão geral"], ["documents", "Documentos"], ["issuances", "Emissões"], ["inutilizations", "Inutilização"], ["errors", "Erros"], ["reconciliation", "Conciliação"], ["tax-reform", "Reforma Tributária"]] },
  { label: "Configuração", items: [["onboarding", "Configuração inicial"], ["companies", "Empresas"], ["units", "Unidades"], ["environments", "Ambientes"], ["capabilities", "Capacidades"], ["certificates", "Certificados"], ["providers", "Provedores"], ["users", "Usuários"]] },
  { label: "Plataforma", items: [["webhooks", "Webhooks"], ["webhook-egress", "Aprovação de saída"], ["integrations", "Integrações"], ["usage", "Uso"], ["billing", "Cobrança"], ["plans", "Planos"], ["pricing-admin", "Catálogo comercial"], ["commercial-release", "Liberação comercial"], ["checkout-admin", "Canais de venda e pagamento"], ["audit", "Auditoria"], ["support", "Suporte"], ["settings", "Configurações"]] },
];

const supportedDocumentLabels = ["NF-e", "NFC-e", "NFS-e"];
const safetyStates = {
  blocked: "PROD BLOQUEADA",
  external: "BLOCKED_EXTERNAL",
  approval: "HUMAN_APPROVAL_REQUIRED",
};

/** @type {Record<string,string>} */
const descriptions = {
  overview: "Visão governada da operação fiscal e da prontidão comprovada da organização.",
  documents: "Ciclo de vida documental, consulta, arquivo e correlação.",
  issuances: "Emissões idempotentes e rastreáveis.",
  inutilizations: "Solicitação governada de inutilização de faixa e acompanhamento do processamento interno.",
  errors: "Falhas operacionais sem exposição de segredo.",
  reconciliation: "Convergência segura entre estado interno e provedor.",
  "tax-reform": "Enquadramento do emitente e estado de adequação à Reforma Tributária, lidos da fonte fiscal canônica.",
  onboarding: "Configuração inicial por organização e unidade.",
  companies: "Empresas visíveis no escopo autorizado da sessão.",
  units: "Unidades permitidas para o usuário autenticado.",
  environments: "Homologação e produção com autoridade segregada.",
  capabilities: "Capacidades e prontidão fiscal baseadas em evidência.",
  certificates: "Referências de certificado; material secreto nunca é exibido.",
  providers: "Vínculos de provedores por documento, operação e jurisdição.",
  users: "Usuários, papéis e permissões da organização.",
  webhooks: "Destinos e estado de entrega governada.",
  "webhook-egress": "Aprovação e revogação de destinos pela autoridade da plataforma.",
  integrations: "Integrações da organização via contratos versionados.",
  usage: "Uso medido sem interferir na autoridade fiscal.",
  billing: "Cobrança separada da autoridade fiscal.",
  plans: "Plano e direitos comerciais configurados.",
  "pricing-admin": "Catálogo comercial versionado, durável e restrito à administração da plataforma.",
  "commercial-release": "Decisão humana versionada que governa a disponibilidade comercial pública do NFCore.",
  "checkout-admin": "Canais de venda governados por adaptadores. O provedor configurado traduz o pagamento e os eventos sem virar autoridade comercial do NFCore.",
  audit: "Auditoria administrativa e operacional.",
  support: "Configuração autorizada e limites do suporte operacional.",
  settings: "Políticas e configurações autorizadas.",
};

const loginView = /** @type {HTMLElement} */ (document.getElementById("login-view"));
const appShell = /** @type {HTMLElement} */ (document.getElementById("app-shell"));
const loginForm = /** @type {HTMLFormElement} */ (document.getElementById("login-form"));
const loginEmail = /** @type {HTMLInputElement} */ (document.getElementById("login-email"));
const loginPassword = /** @type {HTMLInputElement} */ (document.getElementById("login-password"));
const loginError = /** @type {HTMLElement} */ (document.getElementById("login-error"));
const forgotPasswordAction = /** @type {HTMLButtonElement} */ (document.getElementById("forgot-password-action"));
const passwordResetRequestForm = /** @type {HTMLFormElement} */ (document.getElementById("password-reset-request-form"));
const passwordResetEmail = /** @type {HTMLInputElement} */ (document.getElementById("password-reset-email"));
const passwordResetRequestCancel = /** @type {HTMLButtonElement} */ (document.getElementById("password-reset-request-cancel"));
const passwordResetRequestStatus = /** @type {HTMLElement} */ (document.getElementById("password-reset-request-status"));
const passwordResetCompleteForm = /** @type {HTMLFormElement} */ (document.getElementById("password-reset-complete-form"));
const passwordResetNewPassword = /** @type {HTMLInputElement} */ (document.getElementById("password-reset-new-password"));
const passwordResetCompleteStatus = /** @type {HTMLElement} */ (document.getElementById("password-reset-complete-status"));
const nav = /** @type {HTMLElement} */ (document.getElementById("nav"));
const workspace = /** @type {HTMLElement} */ (document.getElementById("workspace"));
const title = /** @type {HTMLElement} */ (document.getElementById("view-title"));
const authorityContext = /** @type {HTMLElement} */ (document.getElementById("authority-context"));
const runtimeState = /** @type {HTMLElement} */ (document.getElementById("runtime-state"));
const criticalTitle = /** @type {HTMLElement} */ (document.getElementById("critical-state-title"));
const criticalCopy = /** @type {HTMLElement} */ (document.getElementById("critical-state-copy"));
const logoutAction = /** @type {HTMLButtonElement} */ (document.getElementById("logout-action"));
const operationDialog = /** @type {HTMLDialogElement} */ (document.getElementById("operation-dialog"));
const operationForm = /** @type {HTMLFormElement} */ (document.getElementById("operation-form"));
const operationId = /** @type {HTMLSelectElement} */ (document.getElementById("operation-id"));
const operationUnit = /** @type {HTMLInputElement} */ (document.getElementById("operation-unit"));
const operationDocument = /** @type {HTMLInputElement} */ (document.getElementById("operation-document-id"));
const operationDocumentField = /** @type {HTMLElement} */ (document.getElementById("operation-document-field"));
const operationDocumentHelp = /** @type {HTMLElement} */ (document.getElementById("operation-document-help"));
const operationAccessKeyField = /** @type {HTMLFieldSetElement} */ (document.getElementById("operation-access-key-field"));
const operationAccessKey = /** @type {HTMLInputElement} */ (document.getElementById("operation-access-key"));
const operationCancelField = /** @type {HTMLFieldSetElement} */ (document.getElementById("operation-cancel-field"));
const operationAuthorizationProtocol = /** @type {HTMLInputElement} */ (document.getElementById("operation-authorization-protocol"));
const operationCancelJustification = /** @type {HTMLTextAreaElement} */ (document.getElementById("operation-cancel-justification"));
const operationInutilizationField = /** @type {HTMLFieldSetElement} */ (document.getElementById("operation-inutilization-field"));
const operationInutilizationModel = /** @type {HTMLSelectElement} */ (document.getElementById("operation-inutilization-model"));
const operationInutilizationSeries = /** @type {HTMLInputElement} */ (document.getElementById("operation-inutilization-series"));
const operationInutilizationFirst = /** @type {HTMLInputElement} */ (document.getElementById("operation-inutilization-first"));
const operationInutilizationLast = /** @type {HTMLInputElement} */ (document.getElementById("operation-inutilization-last"));
const operationInutilizationJustification = /** @type {HTMLTextAreaElement} */ (document.getElementById("operation-inutilization-justification"));

function usesPreparedReference() {
  return ["issueFiscalDocument", "reconcileFiscalOperation"].includes(operationId.value);
}

function configureOperationForm() {
  const prepared = usesPreparedReference();
  const accessKey = ["queryFiscalDocument", "cancelFiscalDocument"].includes(operationId.value);
  const cancellation = operationId.value === "cancelFiscalDocument";
  const inutilization = operationId.value === "inutilizeFiscalRange";
  operationDocumentField.hidden = !(prepared || cancellation);
  operationDocumentHelp.hidden = !(prepared || cancellation);
  operationDocument.disabled = !(prepared || cancellation);
  operationDocument.required = prepared || cancellation;
  operationAccessKeyField.hidden = !accessKey;
  operationAccessKeyField.disabled = !accessKey;
  operationAccessKey.required = accessKey;
  operationCancelField.hidden = !cancellation;
  operationCancelField.disabled = !cancellation;
  operationAuthorizationProtocol.required = cancellation;
  operationCancelJustification.required = cancellation;
  operationInutilizationField.hidden = !inutilization;
  operationInutilizationField.disabled = !inutilization;
  for (const input of [operationInutilizationSeries, operationInutilizationFirst,
    operationInutilizationLast, operationInutilizationJustification]) input.required = inutilization;
}

/** @returns {Record<string, string|number>} */
function operationPayloadForSelection() {
  if (usesPreparedReference()) return {document_id: operationDocument.value.trim()};
  if (operationId.value === "queryFiscalDocument") return {access_key: operationAccessKey.value.trim()};
  if (operationId.value === "cancelFiscalDocument") return {
    document_id: operationDocument.value.trim(),
    access_key: operationAccessKey.value.trim(),
    authorization_protocol: operationAuthorizationProtocol.value.trim(),
    justification: operationCancelJustification.value.trim(),
  };
  if (operationId.value === "inutilizeFiscalRange") {
    const payload = {
      model: Number(operationInutilizationModel.value),
      series: Number(operationInutilizationSeries.value),
      first_number: Number(operationInutilizationFirst.value),
      last_number: Number(operationInutilizationLast.value),
      justification: operationInutilizationJustification.value.trim(),
    };
    if (![payload.series, payload.first_number, payload.last_number].every(Number.isSafeInteger)
      || payload.last_number < payload.first_number) {
      throw new Error("Informe números inteiros válidos e uma faixa crescente.");
    }
    return payload;
  }
  throw new Error("Operação fiscal não reconhecida.");
}

const operationError = /** @type {HTMLElement} */ (document.getElementById("operation-error"));
const operationCancel = /** @type {HTMLButtonElement} */ (document.getElementById("operation-cancel"));

if (!loginView || !appShell || !loginForm || !nav || !workspace || !title || !operationDialog) {
  throw new Error("FM NFCORE portal shell is incomplete");
}

/** @type {BootstrapState|null} */
let bootstrapState = null;
let currentView = "overview";
const fiscalViews = new Set(["documents", "issuances", "inutilizations", "errors", "reconciliation", "capabilities", "tax-reform"]);
const configurationViews = new Set(["certificates", "providers", "webhooks", "integrations", "settings"]);
const scopedViews = new Set([...fiscalViews, ...configurationViews, "support"]);
let selectedFiscalUnit = "";
let selectedFiscalEnvironment = "homologation";
let fiscalPageOffset = 0;
let surfaceGeneration = 0;
/** @type {{fingerprint:string, key:string, intent_id?:string}|null} */
let pendingFiscalRequest = null;
/** @type {{intent_id:string,operation:string}|null} */
let selectedFiscalIntent = null;
const fiscalOperationPermissions = {
  issueFiscalDocument: "document.issue",
  queryFiscalDocument: "document.query",
  cancelFiscalDocument: "document.cancel",
  inutilizeFiscalRange: "document.inutilize",
  reconcileFiscalOperation: "reconciliation.execute",
};

/** @returns {{unit_id:string, display_name:string, environments:string[]}[]} */
function authorizedFiscalUnits() {
  const units = bootstrapState?.projection.authorized_units;
  if (!Array.isArray(units)) return [];
  return units.filter((unit) => unit && typeof unit.unit_id === "string"
    && typeof unit.display_name === "string" && Array.isArray(unit.environments));
}

/** @param {HTMLElement} article @param {string} viewId */
function appendFiscalFilters(article, viewId) {
  const units = authorizedFiscalUnits();
  if (!units.some((unit) => unit.unit_id === selectedFiscalUnit)) selectedFiscalUnit = units[0]?.unit_id || "";
  const unitLabel = document.createElement("label");
  unitLabel.textContent = "Unidade fiscal";
  const select = document.createElement("select");
  select.id = "fiscal-unit-filter";
  for (const unit of units) {
    const option = document.createElement("option");
    option.value = unit.unit_id; option.textContent = unit.display_name;
    select.append(option);
  }
  select.value = selectedFiscalUnit;
  select.addEventListener("change", () => {
    selectedFiscalUnit = select.value; fiscalPageOffset = 0; void renderSurface(viewId);
  });
  unitLabel.append(select); article.append(unitLabel);
  const environments = units.find((unit) => unit.unit_id === selectedFiscalUnit)?.environments || [];
  if (!environments.includes(selectedFiscalEnvironment)) selectedFiscalEnvironment = environments[0] || "homologation";
  const envLabel = document.createElement("label");
  envLabel.textContent = "Ambiente fiscal";
  const envSelect = document.createElement("select");
  envSelect.id = "fiscal-environment-filter";
  for (const environment of environments) {
    const option = document.createElement("option");
    option.value = environment;
    option.textContent = environment === "production" ? configurationViews.has(viewId) ? "Produção — configuração não autoriza operação" : "Produção — consulta de estado" : "Homologação";
    envSelect.append(option);
  }
  envSelect.value = selectedFiscalEnvironment;
  envSelect.addEventListener("change", () => {
    selectedFiscalEnvironment = envSelect.value; fiscalPageOffset = 0; void renderSurface(viewId);
  });
  envLabel.append(envSelect); article.append(envLabel);
  const notice = document.createElement("p");
  notice.textContent = configurationViews.has(viewId)
    ? "Configuração persistida por unidade e ambiente. Até 100 registros por tipo nesta página. Vínculos de integração seguem o escopo do modelo existente."
    : "Estado registrado no backend. Readiness declarado não autoriza operação. Registros legados sem escopo comprovado não são exibidos. Até 100 registros por tipo nesta página.";
  article.append(notice);
}

/** @param {HTMLElement} article */
function appendFiscalActions(article) {
  const recoveryNotice = document.createElement("p");
  recoveryNotice.textContent = "Se a resposta for interrompida, mantenha esta página aberta e preserve o pedido original. Após recarregar, consulte o estado fiscal antes de iniciar outra solicitação.";
  article.append(recoveryNotice);
  const operations = bootstrapState?.projection.configured_fiscal_operations;
  const configured = Array.isArray(operations) ? operations : [];
  const authorizedScope = authorizedFiscalUnits().some((unit) =>
    unit.unit_id === selectedFiscalUnit && unit.environments.includes(selectedFiscalEnvironment));
  for (const option of operationId.options) {
    const permission = fiscalOperationPermissions[/** @type {keyof typeof fiscalOperationPermissions} */ (option.value)];
    option.disabled = !authorizedScope || !configured.includes(option.value) || !bootstrapState?.permissions.includes(permission);
    option.hidden = option.disabled;
  }
  const allowed = Array.from(operationId.options).filter((option) => !option.disabled);
  if (!allowed.length) {
    const blocked = document.createElement("p");
    blocked.setAttribute("role", "status");
    blocked.textContent = "Operação fiscal indisponível neste escopo: unidade/ambiente, executor ou permissão não autorizados. Nenhuma emissão foi realizada.";
    article.append(blocked);
    return;
  }
  const preferred = currentView === "reconciliation" ? "reconcileFiscalOperation" : "issueFiscalDocument";
  operationId.value = allowed.some((option) => option.value === preferred) ? preferred : allowed[0].value;
  const action = document.createElement("button");
  action.className = "primary"; action.type = "button";
  action.textContent = "Executar operação governada";
  action.addEventListener("click", () => {
    operationUnit.value = selectedFiscalUnit;
    configureOperationForm();
    operationDialog.showModal();
  });
  article.append(action);
}


/** Query the existing authorized archive handler; metadata only, no fiscal provider.
 * @param {HTMLElement} article
 */
function appendArchiveLookup(article) {
  const configured = bootstrapState?.projection.configured_fiscal_operations;
  if (!Array.isArray(configured) || !configured.includes("queryArchiveReference")
      || !bootstrapState?.permissions.includes("document.query")) return;
  const form = document.createElement("form");
  form.id = "archive-lookup-form";
  form.className = "panel-form";
  const label = document.createElement("label");
  label.textContent = "Referência do documento arquivado";
  const reference = document.createElement("input");
  reference.name = "document_reference";
  reference.required = true;
  reference.maxLength = 256;
  reference.autocomplete = "off";
  reference.placeholder = "Referência do documento";
  label.append(reference);
  const help = document.createElement("p");
  help.textContent = "Consulta de metadados internos por unidade e ambiente. Não realiza emissão nem contato com provedor fiscal.";
  const submit = document.createElement("button");
  submit.className = "primary";
  submit.type = "submit";
  submit.textContent = "Consultar arquivo fiscal";
  const statusLine = document.createElement("p");
  statusLine.setAttribute("role", "status");
  const entries = document.createElement("div");
  entries.className = "grid-list";
  form.append(label, help, submit, statusLine, entries);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    if (!selectedFiscalUnit) {
      statusLine.textContent = "Selecione uma unidade autorizada.";
      return;
    }
    submit.disabled = true;
    statusLine.textContent = "Consultando arquivo...";
    entries.replaceChildren();
    try {
      const data = await api("/v1/portal/operations/queryArchiveReference", {
        method: "POST",
        headers: {"X-CSRF-Token": csrfToken()},
        body: JSON.stringify({
          unit_id: selectedFiscalUnit,
          environment: selectedFiscalEnvironment,
          document_reference: reference.value.trim(),
        }),
      });
      const rows = Array.isArray(data.entries) ? data.entries : [];
      statusLine.textContent = data.found === true
        ? `Referência encontrada: ${rows.length} registro(s) arquivado(s).`
        : "Nenhum registro arquivado para esta referência no escopo selecionado.";
      for (const row of rows) entries.append(fiscalRowElement(row));
    } catch (error) {
      statusLine.textContent = error instanceof Error ? error.message : "Falha ao consultar o arquivo";
    } finally {
      submit.disabled = false;
    }
  });
  article.append(form);
}

function csrfToken() {
  const prefix = "nfcore_csrf=";
  const entry = document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith(prefix));
  return entry ? decodeURIComponent(entry.slice(prefix.length)) : "";
}

/** @returns {string|null} */
function resetTokenFromLocation() {
  const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const fragmentToken = fragment.get("token");
  if (fragmentToken) return fragmentToken;
  // Temporary compatibility for previously issued links. New activation delivery uses
  // the fragment so raw reset tokens are not sent in the initial HTTP request.
  return new URLSearchParams(window.location.search).get("reset_token");
}

function clearResetTokenFromLocation() {
  const url = new URL(window.location.href);
  url.searchParams.delete("reset_token");
  const fragment = new URLSearchParams(url.hash.replace(/^#/, ""));
  fragment.delete("token");
  const remainingFragment = fragment.toString();
  url.hash = remainingFragment ? `#${remainingFragment}` : "";
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

/** @type {string|null} */
let pendingPasswordResetToken = resetTokenFromLocation();
if (pendingPasswordResetToken) clearResetTokenFromLocation();

/** @param {string} path @param {ApiOptions} [options] @returns {Promise<any>} */
async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  }).catch(() => {
    throw new Error("Conexão interrompida. O resultado não está confirmado; consulte o acompanhamento antes de repetir uma operação.");
  });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body && typeof body === "object" ? body.detail : null;
    const messages = {
      SESSION_REQUIRED: "Entre novamente para acessar o escopo autorizado.",
      INVALID_SESSION: "A sessão expirou ou foi revogada. Entre novamente.",
      CSRF_REQUIRED: "A proteção da sessão precisa ser renovada. Entre novamente antes de repetir.",
      CSRF_INVALID: "A proteção da sessão não é válida. Entre novamente.",
      UNIT_NOT_CONFIGURED: "A unidade selecionada não está configurada.",
      UNIT_SELECTION_REQUIRED: "Selecione uma unidade autorizada.",
      ENVIRONMENT_NOT_ENABLED: "O ambiente selecionado não está habilitado para esta unidade.",
      FISCAL_RUNTIME_NOT_READY: "O executor fiscal está indisponível. Nenhuma autorização fiscal foi confirmada.",
      PORTAL_RUNTIME_NOT_READY: "Esta capacidade ainda não está disponível no runtime. Tente novamente após a configuração governada.",
      BROWSER_AUTHORITY_REJECTED: "Organização e permissões são definidas pela sessão. Remova campos de autoridade do pedido.",
      INVALID_PREPARED_DOCUMENT: "Referência inválida ou documento ainda não preparado neste escopo. Confira e corrija o campo.",
      MISSING_IDEMPOTENCY_KEY: "O pedido precisa de um identificador de tentativa para ser processado com segurança.",
    };
    const code = detail && typeof detail === "object" && typeof detail.code === "string" ? detail.code : "";
    const translated = messages[/** @type {keyof typeof messages} */ (code)];
    const message = translated || (detail && typeof detail === "object" && typeof detail.message === "string"
      ? detail.message
      : `Falha HTTP ${response.status}`);
    throw Object.assign(new Error(message), { status: response.status, body });
  }
  return body;
}

/** @param {string} [message] */
function showLogin(message = "") {
  loginView.hidden = false;
  appShell.hidden = true;
  loginError.textContent = message;
}

function showApp() {
  loginView.hidden = true;
  appShell.hidden = false;
}

function showPasswordResetRequest() {
  loginForm.hidden = true;
  passwordResetCompleteForm.hidden = true;
  passwordResetRequestForm.hidden = false;
  passwordResetEmail.value = loginEmail.value;
  passwordResetRequestStatus.textContent = "";
}

function showRegularLogin() {
  passwordResetRequestForm.hidden = true;
  passwordResetCompleteForm.hidden = true;
  loginForm.hidden = false;
}

function showPasswordResetCompletion() {
  loginView.hidden = false;
  appShell.hidden = true;
  loginForm.hidden = true;
  passwordResetRequestForm.hidden = true;
  passwordResetCompleteForm.hidden = false;
  passwordResetCompleteStatus.textContent = "";
}

/** @param {unknown} error */
function passwordResetErrorCode(error) {
  const body = error && typeof error === "object" && "body" in error
    ? error.body
    : null;
  const detail = body && typeof body === "object" && "detail" in body
    ? body.detail
    : null;
  return detail && typeof detail === "object" && "code" in detail
    && typeof detail.code === "string"
    ? detail.code
    : "";
}

/** @param {unknown} error */
function passwordResetErrorMessage(error) {
  const code = passwordResetErrorCode(error);
  if (code === "PASSWORD_POLICY_INVALID") {
    return "A senha deve ter entre 12 e 1024 caracteres. Letras, números, espaços e símbolos são permitidos.";
  }
  if (code === "PASSWORD_RESET_NOT_USABLE") {
    return "Este link de recuperação não é mais válido. Solicite um novo link e use somente o e-mail mais recente.";
  }
  return error instanceof Error ? error.message : "Não foi possível alterar a senha.";
}

/** @param {unknown} value @returns {string} */
function text(value) {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.map(text).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** @param {unknown} value */
function tone(value) {
  const normalized = text(value).toUpperCase();
  if (/FAIL|ERROR|REJECT|UNAVAILABLE/.test(normalized)) return "danger";
  if (/NOT_|UNCONFIRMED|EXCLUDED|DISABLED|BLOCKED|PENDING|MISSING|REQUIRED|HOMOLOG/.test(normalized)) return "warning";
  if (/READY|ACTIVE|ATIVA|AUTHORIZED|OK|HEALTHY|CONCLU/.test(normalized)) return "success";
  return "neutral";
}

/** @param {string} key */
function fieldLabel(key) {
  const labels = {
    organization_onboarded: "Organização cadastrada", legal_name: "Razão social",
    unit_count: "Quantidade de unidades", authorized_units: "Unidades autorizadas",
    capability_readiness_configured: "Autoridade de capacidades configurada",
    legacy_unscoped_lifecycle_visibility: "Registros legados sem escopo",
    unit_scope: "Escopo de unidades", enabled_environments: "Ambientes habilitados",
    fiscal_operation_executor_configured: "Executor fiscal composto",
    fiscal_operations_configured: "Operações fiscais configuradas",
    configured_fiscal_operations: "Operações fiscais disponíveis", onboarding_stage: "Etapa de configuração",
    basic_onboarding_complete: "Configuração básica concluída", customer_configuration_mode: "Modo de configuração",
    customer_configuration_operations: "Comandos de configuração", unit_id: "Unidade", environment: "Ambiente",
    record_type: "Tipo de registro", entry_id: "Identificador na fila", operation: "Operação",
    status: "Estado registrado", attempt_count: "Tentativas", created_at: "Criado em",
    available_at: "Próxima tentativa a partir de", fiscal_confirmation: "Confirmação fiscal",
    fiscal_executor: "Executor fiscal", capability_authority: "Autoridade de capacidades",
    support_delivery: "Canal de atendimento", production: "Produção", document_id: "Documento",
    document_reference: "Referência do documento", readiness: "Prontidão", state: "Estado", code: "Código",
    version: "Versão", operational_verification: "Verificação operacional", reference_id: "Referência",
  };
  return labels[/** @type {keyof typeof labels} */ (key)] || key.replaceAll("_", " ");
}

/** @type {Record<string,string>} */
const termLabels = {
  unavailable: "Indisponível", internal_only: "Somente uso interno", waitlist: "Lista de espera",
  ready_for_checkout_configuration: "Pronto para configurar pagamento", ready_for_commercial_review: "Pronto para revisão comercial",
  commercial_approved: "Aprovado comercialmente", excluded_unconfirmed: "Excluídos (não confirmados)", all: "Todas",
  queryarchivereference: "Consultar referência arquivada", unit_setup_required: "Falta cadastrar a unidade",
  governed_configuration: "Configuração governada", configurecertificates: "Configurar certificados",
  configureproviders: "Configurar provedores", configurewebhooks: "Configurar webhooks",
  configureintegrations: "Configurar integrações", configuresettings: "Configurar ajustes",
  issuefiscaldocument: "Emitir documento", cancelfiscaldocument: "Cancelar documento",
  inutilizefiscalrange: "Inutilizar faixa", reconcilefiscaloperation: "Conciliar", queryfiscaldocument: "Consultar documento",
  versioned: "Versionado", audited: "Auditado", session_authority: "Autoridade da sessão", scoped: "Com escopo",
  homologation: "Homologação", production: "Produção", capability: "capacidade",
  owner: "Proprietário", admin: "Administrador", manager: "Gerente", operator: "Operador", viewer: "Leitor",
  auditor: "Auditor", support: "Suporte", billing: "Cobrança", fiscal_operator: "Operador fiscal", platform_admin: "Administrador da plataforma",
  human_approval_required: "Aguardando aprovação humana", blocked_external: "Bloqueado por dependência externa",
  ready: "Pronto", approved: "Aprovado", pending: "Pendente", failed: "Falhou", active: "Ativo", disabled: "Desabilitado",
  registered: "Registrado", registrado: "Registrado", configured: "Configurado", not_configured: "Não configurado",
  enabled: "Habilitado", true: "Sim", false: "Não",
};

/** @param {unknown} value @returns {string} */
function shown(value) {
  if (value === true) return "Sim";
  if (value === false) return "Não";
  if (Array.isArray(value)) return value.map(shown).join(", ");
  if (typeof value === "string" && value) {
    const found = termLabels[value.toLowerCase()];
    if (found) return found;
  }
  return text(value);
}

/** @param {unknown} value */
function friendlyValue(value) {
  return shown(value);
}

/** @param {Record<string, unknown>} row */
function rowElement(row) {
  const wrapper = document.createElement("div");
  wrapper.className = "row";
  const entries = Object.entries(row);
  const primary = entries[0] || ["registro", "—"];
  const secondary = entries[1] || ["contexto", ""];
  const state = entries.find(([key]) => /state|status|readiness|health/i.test(key)) || entries[2] || ["status", ""];

  const strong = document.createElement("strong");
  strong.textContent = friendlyValue(primary[1]);
  const context = document.createElement("span");
  context.className = "state";
  context.textContent = text(secondary[1]);
  const badge = document.createElement("span");
  badge.className = `badge ${tone(state[1])}`;
  badge.textContent = friendlyValue(state[1]);
  context.textContent = friendlyValue(secondary[1]);
  if (context.textContent === badge.textContent) context.textContent = "";
  wrapper.append(strong, context, badge);
  return wrapper;
}

/** @param {Record<string, unknown>} row */
function fiscalRowElement(row) {
  const primary = row.document_id || row.document_reference || row.source_id || row.entry_id || row.reference_id || row.binding_id || row.destination_id || row.module_id || row.policy_id || row.document_kind || "Registro";
  const state = row.readiness || row.state || row.status || row.kind || "registrado";
  const display = {registro: primary, escopo: `${text(row.unit_id)} · ${text(row.environment)} · ${text(row.record_type || row.code || "capability")}`, state};
  return appendRecordDetails(rowElement(display), row);
}

/** Show the complete authorized projection instead of dropping commercial fields. */
/** @param {HTMLElement} wrapper @param {Record<string, unknown>} row */
function appendRecordDetails(wrapper, row) {
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "Detalhes do registro";
  const values = document.createElement("dl");
  for (const [key, value] of Object.entries(row)) {
    const term = document.createElement("dt"); term.textContent = fieldLabel(key);
    const description = document.createElement("dd"); description.textContent = shown(value);
    values.append(term, description);
  }
  details.append(summary, values); wrapper.append(details);
  return wrapper;
}

/** @param {string} titleText @param {string} [eyebrow] */
function panel(titleText, eyebrow = "FM NFCORE V1.0") {
  const article = document.createElement("article");
  article.className = "panel full";
  const header = document.createElement("div");
  header.className = "panel-header";
  const heading = document.createElement("div");
  const eye = document.createElement("p");
  eye.className = "eyebrow";
  eye.textContent = eyebrow;
  const h2 = document.createElement("h2");
  h2.textContent = titleText;
  heading.append(eye, h2);
  header.append(heading);
  article.append(header);
  return article;
}

function renderOverview() {
  workspace.replaceChildren();
  const projection = bootstrapState?.projection || {};
  const article = panel("Estado operacional", "Controle da plataforma");
  const grid = document.createElement("div");
  grid.className = "grid-list";
  const visible = Object.entries(projection).filter(([key]) => key !== "available_surfaces");
  if (!visible.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "A API não retornou projeções operacionais para este escopo.";
    grid.append(empty);
  } else {
    for (const [key, value] of visible) grid.append(rowElement({ item: fieldLabel(key), value, status: value }));
  }
  article.append(grid);

  const identity = panel("Autoridade da sessão", "Proteção de acesso");
  const identityGrid = document.createElement("div");
  identityGrid.className = "grid-list";
  identityGrid.append(
    rowElement({ item: bootstrapState?.tenant_id, value: bootstrapState?.role, status: "SESSION_AUTHORITY" }),
    rowElement({ item: "Unidades", value: bootstrapState?.unit_ids || "todas autorizadas", status: "SCOPED" }),
    rowElement({ item: "Documentos", value: supportedDocumentLabels, status: "V1" }),
  );
  identity.append(identityGrid);
  workspace.append(article, identity);
}

/** @param {HTMLElement} article */
function appendOnboardingControls(article) {
  const stage = bootstrapState?.projection.onboarding_stage;
  if (stage === "commercial_provisioning_required") {
    const notice = document.createElement("div");
    notice.className = "empty-state";
    notice.textContent = "O provisioning comercial confiável da organização precisa ser concluído antes da configuração da unidade.";
    article.append(notice);
    return;
  }
  // The same canonical onboarding operation also registers additional units.
  // Do not make the customer lose this Web capability after their first unit.
  if (typeof stage !== "string"
    || !["unit_setup_required", "basic_setup_complete"].includes(stage)
    || !bootstrapState?.permissions.includes("configuration.write")
    || bootstrapState?.projection.unit_scope !== "all") return;

  const form = document.createElement("form");
  form.className = "panel-form";
  const unitLabel = document.createElement("label");
  unitLabel.textContent = "Código da unidade";
  const unitInput = document.createElement("input");
  unitInput.name = "unit_id";
  unitInput.required = true;
  unitInput.autocomplete = "off";
  const nameLabel = document.createElement("label");
  nameLabel.textContent = "Nome da unidade";
  const nameInput = document.createElement("input");
  nameInput.name = "display_name";
  nameInput.required = true;
  nameInput.autocomplete = "organization";
  unitLabel.append(unitInput);
  nameLabel.append(nameInput);
  const submit = document.createElement("button");
  submit.className = "primary";
  submit.type = "submit";
  submit.textContent = stage === "basic_setup_complete"
    ? "Adicionar unidade em homologação" : "Cadastrar unidade em homologação";
  const statusLine = document.createElement("p");
  statusLine.className = "form-error";
  statusLine.setAttribute("role", "status");
  form.append(unitLabel, nameLabel, submit, statusLine);
  /** @type {{fingerprint:string,key:string}|null} */
  let attempt = null;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const payload = {unit_id: unitInput.value.trim(), display_name: nameInput.value.trim()};
    const fingerprint = JSON.stringify(payload);
    // A network interruption must not mint a new request key on retry.
    if (!attempt || attempt.fingerprint !== fingerprint) {
      attempt = {fingerprint, key: crypto.randomUUID()};
    }
    statusLine.textContent = "";
    submit.disabled = true;
    try {
      await api("/v1/portal/operations/onboardUnit", {
        method: "POST",
        headers: {
          "X-CSRF-Token": csrfToken(),
          "Idempotency-Key": attempt.key,
        },
        body: fingerprint,
      });
      attempt = null;
      await bootstrap();
      // Show the newly registered unit on the existing authorized Units surface.
      await renderSurface("units");
    } catch (error) {
      statusLine.textContent = error instanceof Error ? error.message : "Não foi possível cadastrar a unidade";
    } finally {
      submit.disabled = false;
    }
  });
  article.append(form);
}

async function renderPricingAdmin() {
  workspace.replaceChildren();
  const article = panel("Catálogo comercial", "Administração da plataforma");
  const statusLine = document.createElement("p");
  statusLine.className = "form-error";
  statusLine.setAttribute("role", "status");
  article.append(statusLine);
  workspace.append(article);

  if (!bootstrapState?.platform_admin) {
    statusLine.textContent = "A administração do catálogo exige autoridade explícita de plataforma.";
    return;
  }

  try {
    const response = await api("/v1/admin/pricing");
    const current = response.current && typeof response.current === "object" ? response.current : null;
    const history = Array.isArray(response.history) ? response.history : [];

    const summary = document.createElement("div");
    summary.className = "grid-list";
    summary.append(
      rowElement({
        item: "Estado",
        value: current ? "Catálogo publicado" : "Sem preço comercial publicado",
        status: current ? "PUBLISHED" : "UNPRICED",
      }),
      rowElement({
        item: "Versão ativa",
        value: current && typeof current.version === "number" ? current.version : "—",
        status: "VERSIONED",
      }),
      rowElement({
        item: "Histórico",
        value: history.length,
        status: "AUDITED",
      }),
    );

    const form = document.createElement("form");
    form.className = "panel-form";
    const label = document.createElement("label");
    label.textContent = "Próxima configuração JSON";
    const editor = document.createElement("textarea");
    editor.rows = 18;
    editor.spellcheck = false;
    const draft = current
      ? { ...current, version: Number(current.version) + 1 }
      : { configuration_id: "nfcore-commercial", version: 1, prices: [], plans: [] };
    editor.value = JSON.stringify(draft, null, 2);
    label.append(editor);

    const publish = document.createElement("button");
    publish.className = "primary";
    publish.type = "submit";
    publish.textContent = "Publicar nova versão";
    const warning = document.createElement("p");
    warning.className = "empty-state";
    warning.textContent = "Preços são configuração operacional. Nenhum valor deve ser inventado ou copiado para o código-fonte.";

    form.append(label, warning, publish);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      publish.disabled = true;
      statusLine.textContent = "";
      try {
        const configuration = JSON.parse(editor.value);
        const expectedVersion = current && typeof current.version === "number" ? current.version : null;
        await api("/v1/admin/pricing", {
          method: "POST",
          headers: { "X-CSRF-Token": csrfToken() },
          body: JSON.stringify({
            configuration,
            expected_version: expectedVersion,
          }),
        });
        await renderPricingAdmin();
      } catch (error) {
        statusLine.textContent = error instanceof Error ? error.message : "Não foi possível publicar o catálogo";
      } finally {
        publish.disabled = false;
      }
    });

    article.replaceChildren(summary, form, statusLine);
    // This is an operator action on the same platform-admin Web surface.
    // The API, not this browser, decides whether a staging binding may exist.
    const profile = await api("/runtime/profile");
    if (profile.environment === "staging") {
      const setup = document.createElement("section");
      const explanation = document.createElement("p");
      explanation.textContent = "Staging: registrar a referência já aprovada do segredo de trial no cofre canônico. A ação exige administração da plataforma, não cria preços nem ativa pagamentos.";
      const bind = document.createElement("button");
      bind.type = "button";
      bind.className = "secondary";
      bind.textContent = "Registrar assinatura comercial do staging";
      const result = document.createElement("p");
      result.setAttribute("role", "status");
      bind.addEventListener("click", async () => {
        bind.disabled = true;
        result.textContent = "Registrando referência autorizada...";
        try {
          const response = await api("/internal/staging/commercial-trial-binding", {
            method: "POST", headers: {"X-CSRF-Token": csrfToken()},
          });
          result.textContent = response.status === "bound"
            ? "Vínculo comercial registrado. O segredo continua protegido no Google Secret Manager."
            : "Não foi possível confirmar o vínculo.";
        } catch (error) {
          result.textContent = error instanceof Error ? error.message : "Vínculo negado pela autoridade da plataforma.";
        } finally {
          bind.disabled = false;
        }
      });
      setup.append(explanation, bind, result);
      article.append(setup);
    }
  } catch (error) {
    statusLine.textContent = error instanceof Error ? error.message : "Falha ao carregar catálogo comercial";
  }
}

async function renderCommercialRelease() {
  workspace.replaceChildren();
  const article = panel("Liberação comercial", "Administração da plataforma");
  const statusLine = document.createElement("p");
  statusLine.className = "form-error";
  statusLine.setAttribute("role", "status");
  article.append(statusLine);
  workspace.append(article);

  if (!bootstrapState?.platform_admin) {
    statusLine.textContent = "A decisão de liberação comercial exige autoridade explícita de plataforma.";
    return;
  }

  try {
    const response = await api("/v1/admin/commercial-release");
    const current = response.current && typeof response.current === "object" ? response.current : null;
    const history = Array.isArray(response.history) ? response.history : [];

    const summary = document.createElement("div");
    summary.className = "grid-list";
    summary.append(
      rowElement({
        item: "Estado comercial",
        value: current?.status || "unavailable",
        status: current?.status || "UNAVAILABLE",
      }),
      rowElement({
        item: "Versão",
        value: typeof current?.version === "number" ? current.version : "—",
        status: "VERSIONED",
      }),
      rowElement({
        item: "Histórico",
        value: history.length,
        status: "AUDITED",
      }),
    );

    const form = document.createElement("form");
    form.className = "panel-form";

    const statusLabel = document.createElement("label");
    statusLabel.textContent = "Próximo estado";
    const statusSelect = document.createElement("select");
    for (const value of [
      "unavailable",
      "internal_only",
      "waitlist",
      "ready_for_checkout_configuration",
      "ready_for_commercial_review",
      "commercial_approved",
    ]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = shown(value);
      if ((current?.status || "unavailable") === value) option.selected = true;
      statusSelect.append(option);
    }
    statusLabel.append(statusSelect);

    const messageLabel = document.createElement("label");
    messageLabel.textContent = "Mensagem pública";
    const messageInput = document.createElement("textarea");
    messageInput.rows = 3;
    messageInput.value = typeof current?.public_message === "string" ? current.public_message : "";
    messageLabel.append(messageInput);

    const decisionLabel = document.createElement("label");
    decisionLabel.textContent = "Referência da decisão humana";
    const decisionInput = document.createElement("input");
    decisionInput.type = "text";
    decisionInput.value = typeof current?.human_decision_reference === "string"
      ? current.human_decision_reference
      : "";
    decisionInput.placeholder = "Obrigatória para commercial_approved";
    decisionLabel.append(decisionInput);

    const warning = document.createElement("p");
    warning.className = "empty-state";
    warning.textContent = "A aprovação comercial nunca é inferida por preços, CI, Cakto ou prontidão fiscal. Pagamento e produção fiscal permanecem autoridades separadas.";

    const publish = document.createElement("button");
    publish.className = "primary";
    publish.type = "submit";
    publish.textContent = "Registrar nova decisão";

    form.append(statusLabel, messageLabel, decisionLabel, warning, publish);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      publish.disabled = true;
      statusLine.textContent = "";
      try {
        const expectedVersion = typeof current?.version === "number" ? current.version : null;
        const decision = {
          version: expectedVersion === null ? 1 : expectedVersion + 1,
          status: statusSelect.value,
          public_message: messageInput.value.trim() || null,
          human_decision_reference: decisionInput.value.trim() || null,
        };
        await api("/v1/admin/commercial-release", {
          method: "POST",
          headers: { "X-CSRF-Token": csrfToken() },
          body: JSON.stringify({
            decision,
            expected_version: expectedVersion,
          }),
        });
        await renderCommercialRelease();
      } catch (error) {
        statusLine.textContent = error instanceof Error ? error.message : "Não foi possível registrar a decisão comercial";
      } finally {
        publish.disabled = false;
      }
    });

    article.replaceChildren(summary, form, statusLine);
  } catch (error) {
    statusLine.textContent = error instanceof Error ? error.message : "Falha ao carregar a decisão comercial";
  }
}

async function renderCheckoutAdmin() {
  workspace.replaceChildren();
  const article = panel("Canais de Venda / Checkout", "Administração da plataforma");
  const statusLine = document.createElement("p");
  statusLine.className = "form-error";
  statusLine.setAttribute("role", "status");
  article.append(statusLine);
  workspace.append(article);

  if (!bootstrapState?.platform_admin) {
    statusLine.textContent = "A configuração de canais de venda exige autoridade explícita de plataforma.";
    return;
  }

  try {
    const response = await api("/v1/admin/checkout/cakto");
    const bindings = Array.isArray(response.bindings) ? response.bindings : [];
    const summary = document.createElement("div");
    summary.className = "grid-list";

    if (!bindings.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "Nenhum adaptador de pagamento configurado. A compra permanece bloqueada por segurança.";
      summary.append(empty);
    } else {
      for (const binding of bindings) {
        summary.append(
          rowElement({
            plano: binding.plan_id,
            oferta: binding.external_offer_id,
            status: binding.enabled ? "ENABLED" : "DISABLED",
          }),
        );
      }
    }

    const form = document.createElement("form");
    form.className = "panel-form";

    const productLabel = document.createElement("label");
    productLabel.textContent = "Cakto product ID";
    const productInput = document.createElement("input");
    productInput.required = true;
    productInput.autocomplete = "off";
    productLabel.append(productInput);

    const offerLabel = document.createElement("label");
    offerLabel.textContent = "Cakto offer ID";
    const offerInput = document.createElement("input");
    offerInput.required = true;
    offerInput.autocomplete = "off";
    offerLabel.append(offerInput);

    const planLabel = document.createElement("label");
    planLabel.textContent = "NFCore plan_id";
    const planInput = document.createElement("input");
    planInput.required = true;
    planInput.autocomplete = "off";
    planLabel.append(planInput);

    const entitlementLabel = document.createElement("label");
    entitlementLabel.textContent = "Entitlements (separados por vírgula)";
    const entitlementInput = document.createElement("input");
    entitlementInput.required = true;
    entitlementInput.autocomplete = "off";
    entitlementLabel.append(entitlementInput);

    const enabledLabel = document.createElement("label");
    const enabledInput = document.createElement("input");
    enabledInput.type = "checkbox";
    enabledInput.checked = true;
    enabledLabel.append(enabledInput, document.createTextNode(" Vínculo habilitado"));

    const warning = document.createElement("p");
    warning.className = "empty-state";
    warning.textContent = "Adaptador ativo: Cakto. O preço deve referenciar esta oferta como cakto://PRODUCT_ID/OFFER_ID. IDs não são credenciais. Client secret, token e webhook secret nunca pertencem a este formulário.";

    const submit = document.createElement("button");
    submit.className = "primary";
    submit.type = "submit";
    submit.textContent = "Salvar vínculo";

    form.append(
      productLabel,
      offerLabel,
      planLabel,
      entitlementLabel,
      enabledLabel,
      warning,
      submit,
    );

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      statusLine.textContent = "";
      try {
        const entitlementIds = entitlementInput.value
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean);
        await api("/v1/admin/checkout/cakto", {
          method: "POST",
          headers: { "X-CSRF-Token": csrfToken() },
          body: JSON.stringify({
            external_product_id: productInput.value.trim(),
            external_offer_id: offerInput.value.trim(),
            plan_id: planInput.value.trim(),
            entitlement_ids: entitlementIds,
            enabled: enabledInput.checked,
          }),
        });
        await renderCheckoutAdmin();
      } catch (error) {
        statusLine.textContent = error instanceof Error ? error.message : "Não foi possível salvar o vínculo Cakto";
      } finally {
        submit.disabled = false;
      }
    });

    article.replaceChildren(summary, form, statusLine);
  } catch (error) {
    statusLine.textContent = error instanceof Error ? error.message : "Falha ao carregar o canal de venda configurado";
  }
}

/** @param {string} viewId */
/** @type {Record<string, {operation:string, permission:string, fields:[string,string,string][]}>} */
const customerForms = {
  certificates: {operation: "configureCertificates", permission: "certificate.manage", fields: [["reference_id", "Referência governada (sem material secreto)", "text"], ["kind", "Tipo: certificate, csc ou credentials", "text"], ["provider_id", "Provedor (opcional para certificado)", "optional"]]},
  providers: {operation: "configureProviders", permission: "integration.manage", fields: [["binding_id", "ID do vínculo", "text"], ["document_kind", "Documento: nfe, nfce ou nfse", "text"], ["state_code", "UF", "text"], ["municipality_ibge_code", "Município IBGE (NFS-e)", "optional"], ["operation", "Operação: authorize, query, cancel, inutilize ou status", "text"], ["provider_id", "Provider", "text"], ["enabled", "Vínculo habilitado", "checkbox"]]},
  webhooks: {operation: "configureWebhooks", permission: "integration.manage", fields: [["destination_id", "ID do destino", "text"], ["url", "HTTPS público com path explícito, sem query ou credenciais", "url"], ["enabled", "Solicitar entrega após aprovação da plataforma", "checkbox"]]},
  integrations: {operation: "configureIntegrations", permission: "integration.manage", fields: [["module_id", "ID do módulo", "text"], ["enabled", "Módulo habilitado", "checkbox"]]},
  settings: {operation: "configureSettings", permission: "configuration.write", fields: [["policy_id", "ID da política", "text"], ["provider_id", "Provider", "text"], ["connect_timeout_seconds", "Timeout de conexão (segundos)", "number"], ["read_timeout_seconds", "Timeout de leitura (segundos)", "number"], ["max_attempts", "Máximo de tentativas", "number"], ["base_delay_seconds", "Espera inicial (segundos)", "number"], ["max_delay_seconds", "Espera máxima (segundos)", "number"], ["jitter_ratio", "Jitter (0 a 1)", "number"], ["circuit_failure_threshold", "Falhas para abrir circuito", "number"], ["circuit_recovery_seconds", "Recuperação do circuito (segundos)", "number"], ["circuit_success_threshold", "Sucessos para fechar circuito", "number"]]},
};

/** @param {HTMLFormElement} form @param {string} key @param {string} label @param {string} kind @returns {HTMLInputElement} */
function configurationInput(form, key, label, kind) {
  const wrapper = document.createElement("label"); wrapper.textContent = label;
  const input = document.createElement("input"); input.name = key;
  input.id = `configuration-${key}`; input.type = kind === "optional" ? "text" : kind;
  input.required = kind !== "optional" && kind !== "checkbox";
  if (kind === "number") input.step = "any";
  input.autocomplete = "off"; wrapper.append(input); form.append(wrapper);
  return input;
}

/** @param {HTMLElement} article @param {string} viewId @param {Record<string, unknown>[]} rows */
function appendCustomerConfiguration(article, viewId, rows) {
  const spec = customerForms[viewId];
  const configured = bootstrapState?.projection.customer_configuration_operations;
  if (!spec || !bootstrapState?.permissions.includes(spec.permission) || !Array.isArray(configured)
      || !configured.includes(spec.operation) || !selectedFiscalUnit) return;
  const form = document.createElement("form"); form.id = "customer-configuration-form";
  const intro = document.createElement("p");
  intro.textContent = "Alteração governada neste escopo. Informe a versão atual (0 para cadastro novo). Cadastro não comprova material secreto resolvido, entrega ou homologação. Webhook alterado aguarda nova aprovação da plataforma.";
  form.append(intro);
  const revision = configurationInput(form, "expected_version", "Versão atual", "number");
  revision.min = "0"; revision.step = "1"; revision.value = "0";
  /** @type {Map<string,HTMLInputElement>} */
  const inputs = new Map(spec.fields.map(([key, label, kind]) => [key, configurationInput(form, key, label, kind)]));
  const existing = document.createElement("select"); existing.id = "configuration-existing";
  const empty = document.createElement("option"); empty.textContent = "Novo cadastro"; empty.value = ""; existing.append(empty);
  rows.filter((row) => viewId === "certificates" || row.record_type === viewId).forEach((row, index) => {
    const option = document.createElement("option"); option.value = String(index);
    option.textContent = `${row.target_key || row.destination_id || row.binding_id || row.module_id || row.reference_kind || row.provider_id} · versão ${row.version || 0}`;
    existing.append(option);
  });
  const selectionLabel = document.createElement("label"); selectionLabel.textContent = "Editar cadastro existente";
  selectionLabel.append(existing); form.prepend(selectionLabel);
  existing.addEventListener("change", () => {
    const row = existing.value === "" ? null : rows.filter((item) => viewId === "certificates" || item.record_type === viewId)[Number(existing.value)];
    revision.value = String(row?.version || 0);
    for (const [key, input] of inputs) {
      const value = row?.[key === "kind" ? "reference_kind" : key];
      if (input.type === "checkbox") input.checked = value === true;
      else input.value = value == null ? "" : String(value);
    }
  });
  const submit = document.createElement("button"); submit.type = "submit"; submit.className = "primary";
  submit.textContent = viewId === "webhooks" ? "Solicitar destino" : "Salvar configuração";
  const result = document.createElement("p"); result.setAttribute("role", "status");
  form.append(submit, result);
  /** @type {{fingerprint:string,key:string,intent_id?:string}|null} */
  let attempt = null;
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); if (!form.reportValidity()) return;
    /** @type {Record<string,unknown>} */
    const values = {};
    for (const [key, input] of inputs) {
      if (input.type === "checkbox") values[key] = input.checked;
      else if (input.type === "number") values[key] = Number(input.value);
      else if (input.value || spec.fields.find(([field]) => field === key)?.[2] !== "optional") values[key] = input.value;
    }
    const payload = {unit_id: selectedFiscalUnit, environment: selectedFiscalEnvironment, expected_version: Number(revision.value), values};
    const fingerprint = JSON.stringify(payload);
    if (!attempt || attempt.fingerprint !== fingerprint) attempt = {fingerprint, key: crypto.randomUUID()};
    submit.disabled = true; result.textContent = "Registrando configuração…";
    try {
      const saved = await api(`/v1/portal/operations/${spec.operation}`, {method: "POST", headers: {"X-CSRF-Token": csrfToken(), "Idempotency-Key": attempt.key}, body: fingerprint});
      result.textContent = `Configuração registrada · versão ${saved.version}${saved.approval_status ? ` · aprovação ${saved.approval_status}` : ""}. Verificação operacional não confirmada.`;
      revision.value = String(saved.version); attempt = null;
    } catch (error) { result.textContent = error instanceof Error ? error.message : "Falha ao registrar configuração"; }
    finally { submit.disabled = false; }
  });
  article.append(form);
}

/** @param {HTMLElement} article */
function appendEgressReview(article) {
  if (!bootstrapState?.platform_admin) return;
  const form = document.createElement("form"); form.id = "egress-review-form";
  const tenant = configurationInput(form, "egress-tenant", "Organização solicitada", "text");
  const unit = configurationInput(form, "egress-unit", "Unidade solicitada", "text");
  const environment = configurationInput(form, "egress-environment", "Ambiente: homologation ou production", "text");
  const destination = configurationInput(form, "egress-destination", "ID do destino solicitado", "text");
  const review = document.createElement("button"); review.type = "submit"; review.textContent = "Consultar solicitação";
  const status = document.createElement("p"); status.setAttribute("role", "status"); form.append(review, status);
  const decisionForm = document.createElement("form"); decisionForm.id = "egress-decision-form"; decisionForm.hidden = true;
  const expiry = configurationInput(decisionForm, "egress-expiry", "Validade da aprovação (ISO 8601 com fuso, até 30 dias)", "text");
  const notice = document.createElement("p"); notice.textContent = "Somente autoridade canônica da plataforma. Não aprova a própria solicitação. Não realiza tráfego ou deploy.";
  decisionForm.append(notice);
  /** @type {{url:string,version:number,path:string}|null} */
  let reviewed = null;
  /** @type {{fingerprint:string,key:string,intent_id?:string}|null} */
  let attempt = null;
  for (const [decision, label] of [["approved", "Aprovar saída"], ["revoked", "Revogar saída"]]) {
    const button = document.createElement("button"); button.type = "button"; button.textContent = label;
    button.addEventListener("click", async () => {
      if (!reviewed || (decision === "approved" && !decisionForm.reportValidity())) return;
      const payload = {url: reviewed.url, expected_version: reviewed.version, expires_at: expiry.value};
      const fingerprint = JSON.stringify([reviewed.path, decision, payload]);
      if (!attempt || attempt.fingerprint !== fingerprint) attempt = {fingerprint, key: crypto.randomUUID()};
      button.disabled = true;
      try {
        const result = await api(`${reviewed.path}/${decision}`, {method: "POST", headers: {"X-CSRF-Token": csrfToken(), "Idempotency-Key": attempt.key}, body: JSON.stringify(payload)});
        status.textContent = `Decisão ${({approved:"aprovada",revoked:"revogada"})[String(result.approval_status)] || result.approval_status} registrada · versão ${result.version}. Entrega não confirmada.`;
        reviewed.version = Number(result.version); attempt = null;
      } catch (error) { status.textContent = error instanceof Error ? error.message : "Decisão negada"; }
      finally { button.disabled = false; }
    }); decisionForm.append(button);
  }
  for (const input of [tenant, unit, environment, destination]) input.addEventListener("input", () => { reviewed = null; decisionForm.hidden = true; });
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); reviewed = null; decisionForm.hidden = true;
    const path = `/v1/portal/egress/${[tenant.value, unit.value, environment.value, destination.value].map(encodeURIComponent).join("/")}`;
    try {
      const result = await api(path);
      reviewed = {path, url: String(result.url), version: Number(result.version)};
      status.textContent = `${reviewed.url} · versão ${reviewed.version} · ${result.approval_status}. Habilitado solicitado: ${result.enabled}.`;
      decisionForm.hidden = false;
    } catch (error) { status.textContent = error instanceof Error ? error.message : "Consulta negada"; }
  }); article.append(form, decisionForm);
}

/** @returns {string[]} */
function assignableUserRoles() {
  if (bootstrapState?.role === "owner") return ["owner", "admin", "operator", "auditor", "billing"];
  if (bootstrapState?.role === "admin") return ["operator", "auditor", "billing"];
  return [];
}

/** @param {string} value @returns {string[]|null} */
function parseUserUnits(value) {
  const normalized = value.split(",").map((item) => item.trim()).filter(Boolean);
  return normalized.length ? [...new Set(normalized)] : null;
}

/** @param {HTMLElement} article @param {Record<string, unknown>[]} rows */
function appendUserAdministration(article, rows) {
  if (!bootstrapState?.permissions.includes("user.manage")) return;
  const roles = assignableUserRoles();
  if (!roles.length) return;

  const form = document.createElement("form");
  form.id = "user-administration-form";
  form.className = "panel-form";

  const intro = document.createElement("p");
  intro.textContent = "Administração baseada na autoridade da sessão. A organização nunca vem do navegador, o administrador da plataforma não pode ser concedido aqui e alterações revogam sessões ativas.";

  const existingLabel = document.createElement("label");
  existingLabel.textContent = "Usuário";
  const existing = document.createElement("select");
  existing.id = "user-existing";
  const createOption = document.createElement("option");
  createOption.value = "";
  createOption.textContent = "Novo usuário";
  existing.append(createOption);
  rows.forEach((row, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = String(row.email || row.account_id || ("Usuário " + (index + 1)));
    existing.append(option);
  });
  existingLabel.append(existing);

  const emailLabel = document.createElement("label");
  emailLabel.textContent = "E-mail";
  const email = document.createElement("input");
  email.type = "email";
  email.autocomplete = "email";
  email.required = true;
  emailLabel.append(email);

  const roleLabel = document.createElement("label");
  roleLabel.textContent = "Papel";
  const role = document.createElement("select");
  role.id = "user-target-role";
  for (const roleName of roles) {
    const option = document.createElement("option");
    option.value = roleName;
    option.textContent = shown(roleName.toLowerCase() === roleName ? roleName : roleName.toLowerCase());
    role.append(option);
  }
  roleLabel.append(role);

  const unitsLabel = document.createElement("label");
  unitsLabel.textContent = "Unidades (separadas por vírgula; vazio = todas, quando autorizado)";
  const units = document.createElement("input");
  units.id = "user-target-units";
  units.autocomplete = "off";
  unitsLabel.append(units);

  const enabledLabel = document.createElement("label");
  const enabled = document.createElement("input");
  enabled.type = "checkbox";
  enabled.checked = true;
  enabledLabel.append(enabled, document.createTextNode(" Conta habilitada"));

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "primary";
  submit.textContent = "Criar usuário";
  const statusLine = document.createElement("p");
  statusLine.setAttribute("role", "status");
  statusLine.className = "form-error";

  /** @type {{fingerprint:string,key:string,intent_id?:string}|null} */
  let attempt = null;

  function loadSelection() {
    const row = existing.value === "" ? null : rows[Number(existing.value)];
    email.disabled = Boolean(row);
    email.value = row ? String(row.email || "") : "";
    const rowRole = row ? String(row.role || "") : "";
    if (rowRole && roles.includes(rowRole)) role.value = rowRole;
    else role.value = roles[0];
    units.value = row && Array.isArray(row.unit_ids) ? row.unit_ids.join(", ") : "";
    enabled.checked = row ? row.enabled === true : true;
    const mutable = !row || row.mutable === true;
    role.disabled = !mutable;
    units.disabled = !mutable;
    enabled.disabled = !mutable;
    submit.disabled = !mutable;
    submit.textContent = row ? "Salvar usuário" : "Criar usuário";
    statusLine.textContent = row && !mutable
      ? "Conta visível, mas protegida contra alteração por esta autoridade."
      : row?.platform_admin === true
        ? "Autoridade de plataforma nunca é administrada por esta tela."
        : "";
    attempt = null;
  }
  existing.addEventListener("change", loadSelection);
  loadSelection();

  form.append(intro, existingLabel, emailLabel, roleLabel, unitsLabel, enabledLabel, submit, statusLine);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const row = existing.value === "" ? null : rows[Number(existing.value)];
    if (row && row.mutable !== true) return;
    const operation = row ? "updateUser" : "createUser";
    const payload = row
      ? {
          target_account_id: row.account_id,
          expected_version: Number(row.version),
          target_role: role.value,
          target_unit_ids: parseUserUnits(units.value),
          enabled: enabled.checked,
        }
      : {
          email: email.value.trim(),
          target_role: role.value,
          target_unit_ids: parseUserUnits(units.value),
        };
    const fingerprint = JSON.stringify([operation, payload]);
    if (!attempt || attempt.fingerprint !== fingerprint) {
      attempt = {fingerprint, key: crypto.randomUUID()};
    }
    submit.disabled = true;
    statusLine.textContent = "";
    try {
      const result = await api("/v1/portal/operations/" + operation, {
        method: "POST",
        headers: {"X-CSRF-Token": csrfToken(), "Idempotency-Key": attempt.key},
        body: JSON.stringify(payload),
      });
      const confirmation = result.created
        ? "Usuário criado. A senha deve ser definida pelo fluxo existente de recuperação."
        : result.replay
          ? "Estado já aplicado; nenhuma duplicação foi criada."
          : "Usuário atualizado e sessões anteriores revogadas.";
      attempt = null;
      await bootstrap();
      await renderSurface("users");
      // Re-render replaces the form; keep the acknowledged result visible.
      const visibleStatus = workspace.querySelector("#user-administration-form [role='status']");
      if (visibleStatus) visibleStatus.textContent = confirmation;
    } catch (error) {
      statusLine.textContent = error instanceof Error ? error.message : "Administração de usuário rejeitada";
      submit.disabled = false;
    }
  });
  article.append(form);
}

/** @param {string} operation @param {Record<string,unknown>} payload */
async function sendFiscalMutation(operation, payload) {
  const fingerprint = `${operation}:${JSON.stringify(payload)}`;
  if (pendingFiscalRequest && pendingFiscalRequest.fingerprint !== fingerprint) {
    throw new Error("Há uma tentativa pendente com outro conteúdo. Preserve o pedido original.");
  }
  pendingFiscalRequest ||= {fingerprint, key: crypto.randomUUID()};
  const headers = {"X-CSRF-Token": csrfToken(), "Idempotency-Key": pendingFiscalRequest.key};
  if (!pendingFiscalRequest.intent_id) {
    if (selectedFiscalIntent?.operation === operation) {
      pendingFiscalRequest.intent_id = selectedFiscalIntent.intent_id;
    } else {
      const list = await api(`/v1/portal/fiscal-intents?${new URLSearchParams({unit_id:String(payload.unit_id), environment:String(payload.environment)})}`);
      if ((list.rows || []).some((/** @type {Record<string,unknown>} */ row) => row.operation === operation && row.state !== "recorded")) {
        throw new Error("Há um pedido original pendente. Selecione Retomar pedido original e reenvie o mesmo conteúdo.");
      }
      try {
        const receipt = await api(`/v1/portal/fiscal-intents/prepare/${encodeURIComponent(operation)}`, {method:"POST", headers, body:JSON.stringify(payload)});
        pendingFiscalRequest.intent_id = String(receipt.intent_id);
      } catch (error) {
        // A definitive validation rejection precedes intent persistence. Network
        // uncertainty and failures after an intent exists still preserve its key.
        if (error instanceof Error && "status" in error && error.status === 400) {
          pendingFiscalRequest = null;
        }
        throw error;
      }
    }
  }
  const result = await api(`/v1/portal/fiscal-intents/${encodeURIComponent(pendingFiscalRequest.intent_id)}/resume`, {method:"POST", headers, body:JSON.stringify(payload)});
  pendingFiscalRequest = null; selectedFiscalIntent = null;
  const previous = document.querySelector("#fiscal-recovery");
  const article = previous?.parentElement;
  if (previous && article) {
    const marker = document.createElement("span"); previous.replaceWith(marker);
    const refreshed = await appendFiscalRecovery(article);
    if (refreshed) marker.replaceWith(refreshed); else marker.remove();
  }
  return result;
}

/** @param {HTMLElement} article */
async function appendFiscalRecovery(article) {
  if (!selectedFiscalUnit) return;
  const section = document.createElement("section"); section.id = "fiscal-recovery";
  const title = document.createElement("h3"); title.textContent = "Pedidos fiscais recentes"; section.append(title);
  const notice = document.createElement("p"); notice.textContent = "Retome o pedido original reenviando o mesmo conteúdo. Registro interno não comprova autorização fiscal; resultado desconhecido exige reconciliação."; section.append(notice);
  article.append(section);
  try {
    const response = await api(`/v1/portal/fiscal-intents?${new URLSearchParams({unit_id:selectedFiscalUnit, environment:selectedFiscalEnvironment})}`);
    for (const row of response.rows || []) {
      const item = document.createElement("div"); item.dataset.intentId = String(row.intent_id); item.dataset.intentState = String(row.state);
      /** @type {Record<string,string>} */
      const operationNames = {issueFiscalDocument:"Emissão", cancelFiscalDocument:"Cancelamento", inutilizeFiscalRange:"Inutilização", reconcileFiscalOperation:"Conciliação"};
      /** @type {Record<string,string>} */
      const stateNames = {prepared:"Preparado para retomada", executing:"Resultado a verificar", recorded:"Resposta registrada"};
      const label = document.createElement("p"); label.textContent = `${operationNames[String(row.operation)] || "Pedido fiscal"} · ${stateNames[String(row.state)] || "Estado a verificar"} · ${new Date(String(row.created_at)).toLocaleString("pt-BR")}`; item.append(label);
      const button = document.createElement("button"); button.type = "button"; button.className = "ghost"; button.textContent = "Retomar pedido original";
      button.addEventListener("click", () => {
        if (pendingFiscalRequest?.intent_id && pendingFiscalRequest.intent_id !== row.intent_id) {
          notice.textContent = "Preserve a tentativa selecionada até confirmar o resultado."; return;
        }
        selectedFiscalIntent = {intent_id:String(row.intent_id), operation:String(row.operation)};
        notice.textContent = "Pedido original selecionado. Preencha os mesmos dados e solicite novamente para consultar ou retomar.";
      }); item.append(button); section.append(item);
    }
  } catch (error) { notice.textContent = error instanceof Error ? error.message : "Recuperação indisponível"; }
  return section;
}

/** @param {HTMLElement} article */
function appendInutilizationForm(article) {
  const notice = document.createElement("p");
  notice.setAttribute("role", "status");
  notice.textContent = "Estado da fila não confirma inutilização fiscal. Cadastro, envio ou resposta HTTP não substituem protocolo e evidência oficial. Produção exige autoridade específica do backend.";
  notice.textContent += " Se a resposta for interrompida, mantenha a página aberta. Após recarregar, consulte o estado fiscal antes de iniciar outra solicitação.";
  article.append(notice);
  const operations = bootstrapState?.projection.configured_fiscal_operations;
  if (!bootstrapState?.permissions.includes("document.inutilize")
    || !Array.isArray(operations) || !operations.includes("inutilizeFiscalRange")
    || !authorizedFiscalUnits().some((unit) => unit.unit_id === selectedFiscalUnit
      && unit.environments.includes(selectedFiscalEnvironment))) {
    notice.textContent += " Solicitação bloqueada: executor, permissão ou unidade/ambiente indisponível. Nenhuma operação fiscal foi realizada.";
    return;
  }
  const form = document.createElement("form");
  form.id = "inutilization-form";
  const modelLabel = document.createElement("label"); modelLabel.textContent = "Modelo";
  const model = document.createElement("select"); model.id = "inutilization-model";
  for (const [value, label] of [["55", "NF-e (55)"], ["65", "NFC-e (65)"]]) {
    const option = document.createElement("option"); option.value = value; option.textContent = label;
    model.append(option);
  }
  modelLabel.append(model); form.append(modelLabel);
  /** @type {Record<string, HTMLInputElement>} */
  const numbers = {};
  for (const [name, label, min, max] of [["series", "Série", "0", "999"], ["first_number", "Número inicial", "1", ""], ["last_number", "Número final", "1", ""]]) {
    const wrapper = document.createElement("label"); wrapper.textContent = label;
    const input = document.createElement("input"); input.type = "number"; input.step = "1";
    input.id = `inutilization-${name}`; input.required = true; input.min = min;
    if (max) input.max = max;
    numbers[name] = input; wrapper.append(input); form.append(wrapper);
  }
  const reasonLabel = document.createElement("label"); reasonLabel.textContent = "Justificativa (15 a 255 caracteres)";
  const reason = document.createElement("textarea"); reason.id = "inutilization-justification";
  reason.required = true; reason.minLength = 15; reason.maxLength = 255;
  reasonLabel.append(reason); form.append(reasonLabel);
  const confirmLabel = document.createElement("label");
  const confirm = document.createElement("input"); confirm.type = "checkbox"; confirm.required = true;
  confirm.id = "inutilization-confirm";
  confirmLabel.append(confirm, document.createTextNode(" Conferi modelo, série, faixa, unidade e ambiente."));
  form.append(confirmLabel);
  const resultLine = document.createElement("p"); resultLine.id = "inutilization-result";
  resultLine.setAttribute("role", "status"); resultLine.setAttribute("aria-live", "polite");
  const submit = document.createElement("button"); submit.type = "submit"; submit.className = "primary";
  submit.textContent = "Solicitar inutilização";
  form.append(resultLine, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); resultLine.textContent = "";
    const payload = {unit_id: selectedFiscalUnit, environment: selectedFiscalEnvironment,
      model: Number(model.value), series: Number(numbers.series.value),
      first_number: Number(numbers.first_number.value), last_number: Number(numbers.last_number.value),
      justification: reason.value.trim()};
    if (![payload.series, payload.first_number, payload.last_number].every(Number.isSafeInteger)
      || payload.last_number < payload.first_number) {
      resultLine.textContent = "Informe números inteiros válidos e uma faixa crescente."; return;
    }
    const fingerprint = `inutilizeFiscalRange:${JSON.stringify(payload)}`;
    if (pendingFiscalRequest && pendingFiscalRequest.fingerprint !== fingerprint) {
      resultLine.textContent = "Há uma tentativa pendente com outro conteúdo. Preserve o pedido original até confirmar seu resultado."; return;
    }
    pendingFiscalRequest ||= {fingerprint, key: crypto.randomUUID()};
    submit.disabled = true;
    try {
      await sendFiscalMutation("inutilizeFiscalRange", payload);
      pendingFiscalRequest = null; selectedFiscalIntent = null;
      form.reset();
      resultLine.textContent = "Resposta recebida do executor. Consulte o estado registrado; a confirmação fiscal depende da evidência oficial.";
      const refresh = document.createElement("button"); refresh.type = "button";
      refresh.textContent = "Atualizar acompanhamento";
      refresh.addEventListener("click", () => void renderSurface("inutilizations"));
      resultLine.append(refresh);
    } catch (error) {
      resultLine.textContent = error instanceof Error ? error.message : "Resultado não confirmado. Repita o mesmo pedido, sem alterar conteúdo.";
    } finally { submit.disabled = false; }
  });
  article.append(form);
}

/** Initial profile enrollment through the canonical Control Plane command.
 * @param {HTMLElement} section
 */
function appendRtcProfileRegistration(section) {
  if (!bootstrapState?.permissions.includes("configuration.write") || !selectedFiscalUnit) return;
  const form = document.createElement("form");
  form.className = "panel-form rtc-profile-form";
  form.id = "rtc-profile-registration";
  const heading = document.createElement("h3");
  heading.textContent = "Cadastrar perfil fiscal inicial";
  const note = document.createElement("p");
  note.className = "form-hint";
  note.textContent = "O cadastro cria um snapshot fiscal imutável e auditado para a unidade selecionada. Não habilita emissão, assinatura ou cálculos IBS/CBS.";
  form.append(heading, note);
  /** @type {Record<string,HTMLInputElement>} */
  const fields = {};
  for (const [name, labelText, pattern] of [
    ["cnpj", "CNPJ do emitente (14 dígitos)", "[0-9]{14}"],
    ["legal_name", "Razão social", ""],
    ["primary_cnae", "CNAE principal (7 dígitos)", "[0-9]{7}"],
    ["state_registration", "Inscrição estadual (se aplicável)", ""],
    ["street", "Logradouro", ""],
    ["number", "Número", ""],
    ["district", "Bairro", ""],
    ["municipality_name", "Município", ""],
    ["state_code", "UF (2 letras)", "[A-Za-z]{2}"],
    ["municipality_ibge_code", "Código IBGE municipal (7 dígitos)", "[0-9]{7}"],
    ["postal_code", "CEP (8 dígitos)", "[0-9]{8}"],
  ]) {
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = document.createElement("input");
    input.name = name;
    input.autocomplete = "off";
    input.required = name !== "state_registration";
    if (pattern) input.pattern = pattern;
    label.append(input);
    fields[name] = input;
    form.append(label);
  }
  const crtLabel = document.createElement("label");
  crtLabel.textContent = "CRT da NF-e/NFC-e (não confundir com regime federal IRPJ)";
  const crt = document.createElement("select");
  for (const [code, label] of [["1", "Simples Nacional"], ["2", "Simples com sublimite"],
    ["3", "Regime normal CRT"], ["4", "MEI"]]) {
    const option = document.createElement("option");
    option.value = code; option.textContent = label; crt.append(option);
  }
  crtLabel.append(crt);
  const exemptLabel = document.createElement("label");
  const exempt = document.createElement("input");
  exempt.type = "checkbox";
  exemptLabel.append(exempt, document.createTextNode(" Isento de inscrição estadual"));
  exempt.addEventListener("change", () => {
    fields.state_registration.disabled = exempt.checked;
    fields.state_registration.required = !exempt.checked;
    if (exempt.checked) fields.state_registration.value = "";
  });
  fields.state_registration.required = true;
  const submit = document.createElement("button");
  submit.type = "submit"; submit.className = "primary";
  submit.textContent = "Registrar perfil fiscal";
  const statusLine = document.createElement("p");
  statusLine.setAttribute("role", "status");
  statusLine.className = "form-error";
  form.append(crtLabel, exemptLabel, submit, statusLine);
  /** @type {{fingerprint:string,key:string}|null} */
  let attempt = null;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const payload = {
      unit_id: selectedFiscalUnit,
      environment: selectedFiscalEnvironment,
      cnpj: fields.cnpj.value.trim(),
      legal_name: fields.legal_name.value.trim(),
      crt: Number(crt.value),
      primary_cnae: fields.primary_cnae.value.trim(),
      state_registration: fields.state_registration.value.trim(),
      state_registration_exempt: exempt.checked,
      street: fields.street.value.trim(),
      number: fields.number.value.trim(),
      district: fields.district.value.trim(),
      municipality_name: fields.municipality_name.value.trim(),
      state_code: fields.state_code.value.trim().toUpperCase(),
      municipality_ibge_code: fields.municipality_ibge_code.value.trim(),
      postal_code: fields.postal_code.value.trim(),
    };
    const fingerprint = JSON.stringify(payload);
    if (!attempt || attempt.fingerprint !== fingerprint) {
      attempt = {fingerprint, key: crypto.randomUUID()};
    }
    submit.disabled = true;
    statusLine.textContent = "Registrando perfil fiscal na autoridade canônica...";
    try {
      await api("/v1/portal/operations/registerFiscalProfile", {
        method: "POST",
        headers: {"X-CSRF-Token": csrfToken(), "Idempotency-Key": attempt.key},
        body: JSON.stringify(payload),
      });
      attempt = null;
      await renderSurface("tax-reform");
    } catch (error) {
      statusLine.textContent = error instanceof Error
        ? error.message : "O cadastro foi rejeitado. Verifique dados e permissões.";
      submit.disabled = false;
    }
  });
  section.append(form);
}

/** RTC projection: display server-owned issuer data and explicit blockers.
 * @param {HTMLElement} article
 * @param {Array<Record<string, string|number|null>>} rows
 */
function appendRtcIssuerSummary(article, rows) {
  const section = document.createElement("section");
  section.className = "rtc-overview";
  section.setAttribute("aria-label", "Enquadramento e prontidão tributária");
  const issuer = rows.find((row) => row.record_type === "rtc_issuer");
  if (!issuer) {
    const error = document.createElement("p");
    error.className = "form-error";
    error.textContent = "A autoridade fiscal não retornou o enquadramento do emitente.";
    section.append(error);
    article.append(section);
    return;
  }
  const status = document.createElement("p");
  status.className = "rtc-status";
  status.setAttribute("role", "status");
  const configured = issuer.status === "profile_effective";
  status.textContent = configured
    ? "Perfil fiscal vigente encontrado na unidade e no ambiente selecionados."
    : "Perfil fiscal vigente não configurado. A classificação e os cálculos não estão liberados.";
  section.append(status);
  if (!configured) appendRtcProfileRegistration(section);
  if (configured) {
    const grid = document.createElement("div");
    grid.className = "grid-list";
    /** @type {Record<string,string>} */
    const crtLabels = {"1":"Simples Nacional", "2":"Simples — excesso de sublimite",
      "3":"Regime normal (CRT)", "4":"MEI"};
    grid.append(
      rowElement({item: "Estabelecimento", value: issuer.legal_name}),
      rowElement({item: "Código CRT (NF-e/NFC-e)", value: crtLabels[String(issuer.crt)] || "Não reconhecido"}),
      rowElement({item: "CNAE principal", value: issuer.primary_cnae}),
      rowElement({item: "UF / Município IBGE", value: `${issuer.state_code || "—"} / ${issuer.municipality_ibge_code || "—"}`}),
      rowElement({item: "Versão do perfil", value: issuer.profile_version}),
      rowElement({item: "Vigência inicial", value: issuer.effective_from}),
      rowElement({item: "Vigência final", value: issuer.effective_to || "Sem término definido"}),
    );
    section.append(grid);
  }
  const pending = document.createElement("p");
  pending.className = "empty-state";
  pending.textContent = "Regime federal (Lucro Real / Presumido / Simples): sem declaração validada e persistida. O CRT não define sozinho o regime de IRPJ/CSLL.";
  const calc = document.createElement("p");
  calc.className = "empty-state";
  calc.textContent = "IBS, CBS, IS e classificação CST/cClassTrib: cálculo e tabelas oficiais ainda não certificados para operação. O cadastro inicial exige permissão administrativa; nenhuma emissão ou cálculo fiscal é executado nesta tela.";
  section.append(pending, calc);
  article.append(section);
}

/** @param {string} viewId */
async function renderSurface(viewId) {
  const generation = ++surfaceGeneration;
  workspace.setAttribute("aria-busy", "false");
  if (currentView !== viewId) {
    fiscalPageOffset = 0;
    // Switching modules must reveal their tools, not preserve a scrolled hero.
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  currentView = viewId;
  // Branding belongs to the overview; backend readiness remains visible everywhere.
  appShell.classList.toggle("is-operational-view", viewId !== "overview");
  const label = navigation.flatMap((group) => group.items).find(([id]) => id === viewId)?.[1] || viewId;
  title.textContent = label;
  document.querySelectorAll(".nav-button").forEach((element) => {
    const button = /** @type {HTMLElement} */ (element);
    if (button.dataset.view === viewId) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  if (viewId === "overview") {
    renderOverview();
    return;
  }
  if (viewId === "webhook-egress") {
    workspace.replaceChildren();
    const egressPanel = panel(descriptions[viewId]);
    appendEgressReview(egressPanel); workspace.append(egressPanel); return;
  }
  if (viewId === "pricing-admin") {
    await renderPricingAdmin();
    return;
  }
  if (viewId === "commercial-release") {
    await renderCommercialRelease();
    return;
  }
  if (viewId === "checkout-admin") {
    await renderCheckoutAdmin();
    return;
  }
  workspace.replaceChildren();
  const article = panel(descriptions[viewId] || label);
  if (scopedViews.has(viewId)) appendFiscalFilters(article, viewId);
  const loading = document.createElement("p");
  loading.textContent = "Carregando dados autorizados...";
  loading.setAttribute("role", "status");
  workspace.setAttribute("aria-busy", "true");
  article.append(loading);
  workspace.append(article);
  try {
    const filters = scopedViews.has(viewId) ? `?${new URLSearchParams({
      ...(selectedFiscalUnit ? {unit_id: selectedFiscalUnit} : {}),
      environment: selectedFiscalEnvironment, limit: "100", offset: String(fiscalPageOffset),
    })}` : "";
    const response = await api(`/v1/portal/surfaces/${encodeURIComponent(viewId)}${filters}`);
    // A prior request cannot overwrite a newer navigation or unit selection.
    if (generation !== surfaceGeneration) return;
    const grid = document.createElement("div");
    grid.className = "grid-list";
    const rows = Array.isArray(response.rows) ? response.rows : [];
    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = scopedViews.has(viewId) ? "Nenhum registro nesta página do escopo autorizado." : "Nenhum registro disponível neste escopo autorizado.";
      grid.append(empty);
    } else {
      for (const row of rows) {
        const entry = scopedViews.has(viewId) || viewId === "support"
          ? fiscalRowElement(row)
          : ["onboarding", "companies", "units", "environments", "users", "audit", "billing", "plans", "usage"].includes(viewId)
            ? appendRecordDetails(rowElement(row), row)
            : rowElement(row);
        grid.append(entry);
      }
    }
    loading.remove();
    if (viewId === "tax-reform") {
      appendRtcIssuerSummary(article, rows);
    } else {
      article.append(grid);
    }
    if (viewId === "support") {
      const notice = document.createElement("p"); notice.className = "empty-state";
      notice.textContent = "Esta página mostra configuração do escopo autorizado. Atendimento, SLA, incidentes e saúde operacional externa ainda não estão certificados. Não envie senha, token, certificado ou conteúdo fiscal em solicitações de suporte.";
      article.append(notice);
    }
    if (["billing", "plans", "usage"].includes(viewId)) {
      const notice = document.createElement("p");
      notice.className = "empty-state";
      notice.textContent = "Estado lido das autoridades comerciais canônicas do NFCore. Gateways externos permanecem adaptadores e não definem assinatura, plano, entitlement ou uso.";
      article.append(notice);
    }
    if (configurationViews.has(viewId)) {
      const notice = document.createElement("p");
      notice.className = "form-error";
      notice.textContent = "Referência cadastrada não comprova segredo resolvido, entrega, homologação ou produção. Webhooks exigem aprovação vigente da plataforma.";
      appendCustomerConfiguration(article, viewId, rows);
      article.append(notice);
    }
    if (viewId === "onboarding" || viewId === "units") appendOnboardingControls(article);
    if (viewId === "documents") appendArchiveLookup(article);
    if (viewId === "users") appendUserAdministration(article, rows);
    if (viewId === "errors" || viewId === "reconciliation") appendCognitiveAdvisor(article, viewId);
    if (["inutilizations", "documents", "issuances", "reconciliation"].includes(viewId)) await appendFiscalRecovery(article);
    if (viewId === "inutilizations") appendInutilizationForm(article);
    if (["documents", "issuances", "reconciliation"].includes(viewId)) appendFiscalActions(article);
    if (scopedViews.has(viewId) && viewId !== "capabilities") {
      const previous = document.createElement("button");
      previous.type = "button"; previous.textContent = "Página anterior"; previous.disabled = fiscalPageOffset === 0;
      previous.addEventListener("click", () => { fiscalPageOffset = Math.max(0, fiscalPageOffset - 100); void renderSurface(viewId); });
      const next = document.createElement("button");
      next.type = "button"; next.textContent = "Próxima página";
      next.addEventListener("click", () => { fiscalPageOffset += 100; void renderSurface(viewId); });
      next.disabled = fiscalPageOffset >= 10000;
      article.append(previous, next);
    }
  } catch (error) {
    if (generation !== surfaceGeneration) return;
    loading.textContent = error instanceof Error ? error.message : "Falha ao carregar superfície";
    loading.className = "form-error";
    loading.setAttribute("role", "alert");
    const retry = document.createElement("button"); retry.type = "button";
    retry.textContent = "Tentar carregar novamente";
    retry.addEventListener("click", () => void renderSurface(viewId));
    article.append(retry);
  } finally {
    if (generation === surfaceGeneration) workspace.setAttribute("aria-busy", "false");
  }
}

/** @returns {Set<string>|null} */
function availableSurfaces() {
  const value = bootstrapState?.projection.available_surfaces;
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) return null;
  return new Set(["overview", ...value]);
}

function buildNavigation() {
  nav.replaceChildren();
  const allowed = availableSurfaces();
  for (const group of navigation) {
    const visibleItems = group.items.filter(([id]) => allowed === null || allowed.has(id));
    if (!visibleItems.length) continue;
    const section = document.createElement("section");
    section.className = "nav-group";
    const label = document.createElement("span");
    label.className = "nav-group-label";
    label.textContent = group.label;
    section.append(label);
    for (const [id, itemLabel] of visibleItems) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "nav-button";
      button.dataset.view = id;
      button.textContent = itemLabel;
      button.addEventListener("click", () => void renderSurface(id));
      section.append(button);
    }
    nav.append(section);
  }
}

/** @param {unknown} value */
function productionStateLabel(value) {
  const labels = {
    HUMAN_APPROVAL_REQUIRED: "Aguardando aprovação humana",
    BLOCKED_EXTERNAL: "Bloqueado por dependência externa",
    READY: "Pronto",
    APPROVED: "Aprovado",
  };
  const key = text(value);
  return /** @type {Record<string,string>} */ (labels)[key] || key;
}

/** @param {BootstrapState} state */
function applyBootstrap(state) {
  bootstrapState = state;
  showApp();
  authorityContext.textContent = `${state.tenant_id} · ${state.role}`;
  runtimeState.textContent = "API autenticada conectada";
  const productionState = state.projection.production_state || state.projection.readiness || safetyStates.approval;
  criticalTitle.textContent = productionStateLabel(productionState);
  criticalCopy.textContent = /^(READY|APPROVED)$/i.test(text(productionState))
    ? "Estado confirmado pelo sistema; as operações continuam sujeitas às permissões do seu perfil e às regras fiscais."
    : "Produção permanece bloqueada: a emissão real só é liberada depois que o sistema comprovar as condições necessárias e houver aprovação humana.";
  buildNavigation();
  appShell.classList.remove("is-operational-view");
  renderOverview();
}

async function bootstrap() {
  try {
    /** @type {BootstrapState} */
    const state = await api("/v1/portal/bootstrap");
    applyBootstrap(state);
  } catch (error) {
    const status = error instanceof Error && "status" in error ? error.status : null;
    if (status === 401) showLogin();
    else showLogin(error instanceof Error ? error.message : "Portal indisponível");
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  const email = loginEmail.value;
  const password = loginPassword.value;
  try {
    await api("/v1/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    loginPassword.value = "";
    await bootstrap();
  } catch (error) {
    showLogin(error instanceof Error ? error.message : "Falha ao autenticar");
  }
});

document.querySelectorAll("[data-password-toggle]").forEach((element) => {
  if (!(element instanceof HTMLButtonElement)) return;
  const button = element;
  button.addEventListener("click", () => {
    const targetId = button.getAttribute("data-password-toggle");
    if (!targetId) return;
    const input = document.getElementById(targetId);
    if (!(input instanceof HTMLInputElement)) return;
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.setAttribute("aria-pressed", String(show));
    button.setAttribute("aria-label", show ? "Ocultar senha" : "Mostrar senha");
    button.title = show ? "Ocultar senha" : "Mostrar senha";
  });
});

forgotPasswordAction.addEventListener("click", showPasswordResetRequest);
passwordResetRequestCancel.addEventListener("click", showRegularLogin);
passwordResetRequestForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  passwordResetRequestStatus.textContent = "";
  try {
    await api("/v1/auth/password-reset/request", {
      method: "POST",
      body: JSON.stringify({ email: passwordResetEmail.value }),
    });
    passwordResetRequestStatus.textContent = "Se a conta for elegível, as instruções de recuperação serão enviadas pelo canal configurado.";
  } catch (error) {
    passwordResetRequestStatus.textContent = error instanceof Error ? error.message : "Falha ao solicitar recuperação";
  }
});

passwordResetCompleteForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  passwordResetCompleteStatus.textContent = "";
  const resetToken = pendingPasswordResetToken;
  if (!resetToken) {
    passwordResetCompleteStatus.textContent = "Link de recuperação inválido.";
    return;
  }
  try {
    await api("/v1/auth/password-reset/complete", {
      method: "POST",
      body: JSON.stringify({
        reset_token: resetToken,
        new_password: passwordResetNewPassword.value,
      }),
    });
    passwordResetNewPassword.value = "";
    pendingPasswordResetToken = null;
    showRegularLogin();
    showLogin("Senha alterada. Entre novamente com a nova senha.");
  } catch (error) {
    if (passwordResetErrorCode(error) === "PASSWORD_RESET_NOT_USABLE") {
      pendingPasswordResetToken = null;
    }
    passwordResetCompleteStatus.textContent = passwordResetErrorMessage(error);
  }
});

logoutAction.addEventListener("click", async () => {
  try {
    await api("/v1/auth/logout", { method: "POST", headers: { "X-CSRF-Token": csrfToken() } });
  } finally {
    bootstrapState = null;
    pendingFiscalRequest = null; selectedFiscalIntent = null;
    showLogin();
  }
});

operationId.addEventListener("change", configureOperationForm);
operationCancel.addEventListener("click", () => operationDialog.close());
operationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = operationForm.querySelector('button[type="submit"]');
  if (!(submit instanceof HTMLButtonElement) || submit.disabled) return;
  submit.disabled = true;
  operationError.textContent = "";
  try {
    const selected = operationId.value;
    const unitId = operationUnit.value.trim();
    const prepared = usesPreparedReference();
    if (prepared && !operationDocument.value.trim()) {
      throw new Error("Informe a referência do documento preparado.");
    }
    const parsed = operationPayloadForSelection();
    const payload = { ...parsed, unit_id: unitId, environment: selectedFiscalEnvironment };
    const fingerprint = `${selected}:${JSON.stringify(payload)}`;
    const mutation = selected !== "queryFiscalDocument";
    /** @type {Record<string,string>} */
    const headers = { "X-CSRF-Token": csrfToken() };
    if (mutation) {
      if (pendingFiscalRequest && pendingFiscalRequest.fingerprint !== fingerprint) {
        throw new Error("Há uma tentativa pendente com outro conteúdo. Preserve o pedido original até confirmar seu resultado.");
      }
      pendingFiscalRequest ||= {fingerprint, key: crypto.randomUUID()};
      headers["Idempotency-Key"] = pendingFiscalRequest.key;
    }
    const submittedView = currentView;
    const submittedGeneration = surfaceGeneration;
    const result = mutation ? await sendFiscalMutation(selected, payload)
      : await api(`/v1/portal/operations/${encodeURIComponent(selected)}`, {
      method: "POST", headers, body: JSON.stringify(payload),
    });
    operationDialog.close();
    if (submittedGeneration !== surfaceGeneration) return;
    const rendering = renderSurface(submittedView);
    const resultGeneration = surfaceGeneration;
    await rendering;
    if (resultGeneration !== surfaceGeneration) return;
    const status = document.createElement("p");
    status.id = prepared ? "prepared-document-result" : "fiscal-operation-result";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    if (mutation) {
      status.textContent = "Resposta registrada. O recibo do pedido não confirma autorização fiscal. Confira o estado do documento em Emissões.";
      if (typeof result.reference_id === "string") status.textContent += ` Referência: ${result.reference_id}.`;
    } else {
      status.textContent = `Resultado da consulta: ${typeof result.status === "string" ? result.status : "não informado"}.`;
      if (typeof result.access_key === "string") status.textContent += ` Chave: ${result.access_key}.`;
      if (typeof result.protocol_reference === "string") status.textContent += ` Protocolo: ${result.protocol_reference}.`;
      else status.textContent += " Nenhum protocolo informado na resposta.";
    }
    workspace.prepend(status);
  } catch (error) {
    operationError.textContent = error instanceof Error ? error.message : "Operação rejeitada";
  } finally {
    submit.disabled = false;
  }
});

if (pendingPasswordResetToken) {
  showPasswordResetCompletion();
} else {
  void bootstrap();
}

const COGNITIVE_CAPABILITIES = {
  errors: {capability: "cognitive.explain_rejection", button: "Explicar estas falhas"},
  reconciliation: {capability: "cognitive.explain_reconciliation", button: "Explicar esta conciliação"},
};
const COGNITIVE_KIND_LABELS = {fact: "Fato", hypothesis: "Hipótese", action: "Ação sugerida", source: "Fonte"};
const COGNITIVE_ERRORS = {
  COGNITIVE_NOT_CONFIGURED: "O assistente consultivo não está configurado neste ambiente.",
  UNIT_REQUIRED: "Selecione uma unidade autorizada antes de pedir a explicação.",
};

/**
 * Advisory panel: shows deterministic facts first and clearly separates model hypotheses.
 * It never executes an operation; every suggested action needs a human decision.
 * @param {HTMLElement} article
 * @param {"errors"|"reconciliation"} viewId
 */
function appendCognitiveAdvisor(article, viewId) {
  const spec = COGNITIVE_CAPABILITIES[viewId];
  const box = document.createElement("section");
  box.className = "cognitive-advisor";
  box.setAttribute("aria-label", "Assistente fiscal consultivo");
  const heading = document.createElement("h3");
  heading.textContent = "Assistente fiscal consultivo";
  const intro = document.createElement("p");
  intro.className = "empty-state";
  intro.textContent = "Explica o que aconteceu com base nos registros acima. Apenas orienta: não emite, cancela, reenvia nem altera impostos. Qualquer ação exige decisão de uma pessoa.";
  const ask = document.createElement("button");
  ask.type = "button";
  ask.textContent = spec.button;
  const result = document.createElement("div");
  result.setAttribute("role", "status");
  result.setAttribute("aria-live", "polite");
  box.append(heading, intro, ask, result);
  article.append(box);
  /** @type {string|null} */
  let attemptKey = null;
  ask.addEventListener("click", async () => {
    if (!selectedFiscalUnit) {
      result.textContent = COGNITIVE_ERRORS.UNIT_REQUIRED;
      return;
    }
    // A network interruption must not mint a new key; a completed answer always does.
    attemptKey = attemptKey || crypto.randomUUID();
    ask.disabled = true;
    result.textContent = "Analisando registros autorizados...";
    try {
      const answer = await api("/v1/portal/cognitive/advise", {
        method: "POST",
        headers: {"X-CSRF-Token": csrfToken(), "Idempotency-Key": attemptKey},
        body: JSON.stringify({capability: spec.capability, unit_id: selectedFiscalUnit}),
      });
      attemptKey = null;
      renderCognitiveAnswer(result, answer);
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      result.textContent = message || "O assistente está indisponível. As telas e operações continuam funcionando normalmente.";
      result.className = "form-error";
      return;
    } finally {
      ask.disabled = false;
    }
    result.className = "";
  });
}

/**
 * @param {HTMLElement} target
 * @param {any} answer
 */
function renderCognitiveAnswer(target, answer) {
  target.replaceChildren();
  const sections = Array.isArray(answer?.sections) ? answer.sections : [];
  const banner = document.createElement("p");
  banner.className = "empty-state";
  if (answer?.status === "insufficient_basis") {
    banner.textContent = "Não há registros suficientes para explicar com segurança. Nada foi presumido.";
  } else if (answer?.status === "denied") {
    banner.textContent = "Acesso negado a este conteúdo no seu escopo.";
  } else {
    banner.textContent = answer?.aiEnabled
      ? "Resposta com apoio de IA, validada contra os registros. Revise antes de agir."
      : "Resposta determinística a partir do catálogo e dos registros (IA desligada).";
  }
  target.append(banner);
  for (const section of sections) {
    if (typeof section?.text !== "string") continue;
    const block = document.createElement("div");
    block.className = `cognitive-section cognitive-${String(section.kind)}`;
    const tag = document.createElement("strong");
    tag.textContent = COGNITIVE_KIND_LABELS[/** @type {keyof typeof COGNITIVE_KIND_LABELS} */ (section.kind)] || "Informação";
    const text = document.createElement("p");
    text.textContent = section.text;
    block.append(tag, text);
    const ids = Array.isArray(section.evidenceIds) ? section.evidenceIds.filter((/** @type {unknown} */ id) => typeof id === "string") : [];
    if (ids.length) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Evidências usadas";
      const list = document.createElement("small");
      list.textContent = ids.join(", ");
      details.append(summary, list);
      block.append(details);
    }
    target.append(block);
  }
  if (typeof answer?.disclaimer === "string") {
    const note = document.createElement("p");
    note.className = "empty-state";
    note.textContent = `${answer.disclaimer} Requer aprovação humana.`;
    target.append(note);
  }
}
