export {};
// First-party anonymous intake. The canonical API owns eligibility and identity.
/** @template {HTMLElement} T @param {string} id @returns {T} */
function element(id) {
  const value = document.getElementById(id);
  if (!value) throw new Error(`Missing trial element: ${id}`);
  return /** @type {T} */ (value);
}
const form = /** @type {HTMLFormElement} */ (element('trial-form'));
const fields = /** @type {HTMLFieldSetElement} */ (element('trial-fields'));
const select = /** @type {HTMLSelectElement} */ (element('trial-plan'));
const email = /** @type {HTMLInputElement} */ (element('trial-email'));
const legalName = /** @type {HTMLInputElement} */ (element('trial-name'));
const status = element('trial-status');
const result = element('trial-result');
const offer = element('trial-offer');
const reload = /** @type {HTMLButtonElement} */ (element('trial-reload'));
/** @typedef {{plan_id: string, price_id: string, display_name: string, trial_days: number}} TrialPlan */
/** @type {TrialPlan[]} */
let plans = [];
let busy = false;
let completed = false;
// Keep only a digest and random request key in tab storage; never name/email/tokens.
const storageKey = 'nfcore.public-trial.request.v1';
/** @type {{digest: string, key: string} | null} */
let attempt = null;
try {
  const stored = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
  if (stored && /^[a-f0-9]{64}$/.test(stored.digest) &&
      /^trial-[a-f0-9-]{36}$/.test(stored.key)) attempt = stored;
} catch { /* Storage unavailable: retain in-memory recovery within this page. */ }

/** @param {unknown} value @returns {value is TrialPlan} */
function isPlan(value) {
  if (!value || typeof value !== 'object') return false;
  const plan = /** @type {Record<string, unknown>} */ (value);
  return ['plan_id', 'price_id', 'display_name'].every(
    (key) => typeof plan[key] === 'string' && plan[key].trim().length > 0
  ) && typeof plan.trial_days === 'number' && Number.isInteger(plan.trial_days) && plan.trial_days > 0;
}
function showOffer() {
  const plan = plans[Number(select.value)];
  offer.textContent = plan ? `${plan.trial_days} dias de teste. A ativação será enviada ao e-mail informado.` : '';
}
async function loadPlans() {
  if (busy || completed) return;
  busy = true;
  form.hidden = true;
  reload.hidden = true;
  status.textContent = 'Consultando ofertas disponíveis…';
  try {
    const response = await fetch('/v1/public/trial-plans', {
      method: 'POST', credentials: 'omit', cache: 'no-store',
      redirect: 'error', signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) throw new Error('catalog unavailable');
    const payload = await response.json();
    if (!Array.isArray(payload.plans) || !payload.plans.every(isPlan)) throw new Error('invalid catalog');
    plans = payload.plans;
    select.replaceChildren();
    plans.forEach((plan, index) => {
      const option = document.createElement('option');
      option.value = String(index);
      option.textContent = `${plan.display_name} · ${plan.trial_days} dias`;
      select.append(option);
    });
    status.textContent = plans.length ? 'Selecione a oferta para continuar.' : 'Não há ofertas de teste disponíveis no momento.';
    form.hidden = !plans.length;
    reload.hidden = !!plans.length;
    showOffer();
  } catch {
    status.textContent = 'As ofertas de teste estão indisponíveis no momento. Tente novamente mais tarde.';
    reload.hidden = false;
  } finally { busy = false; }
}
select.addEventListener('change', showOffer);
reload.addEventListener('click', () => { void loadPlans(); });
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (busy || completed || !form.reportValidity()) return;
  const plan = plans[Number(select.value)];
  if (!plan) return;
  busy = true;
  fields.disabled = true;
  result.textContent = 'Enviando solicitação…';
  const body = JSON.stringify({
    plan_id: plan.plan_id, price_id: plan.price_id,
    buyer_email: email.value.trim().toLowerCase(), legal_name: legalName.value.trim(),
  });
  try {
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(body))))
      .map((byte) => byte.toString(16).padStart(2, '0')).join('');
    if (!attempt || attempt.digest !== digest) {
      attempt = { digest, key: `trial-${crypto.randomUUID()}` };
    }
    try { sessionStorage.setItem(storageKey, JSON.stringify(attempt)); } catch { /* In-memory retry remains safe. */ }
    const response = await fetch('/v1/public/trials', {
      method: 'POST', credentials: 'omit', cache: 'no-store', redirect: 'error',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': attempt.key },
      body, signal: AbortSignal.timeout(15000),
    });
    if (response.status === 429) {
      result.textContent = 'Limite de tentativas atingido. Aguarde antes de tentar novamente.';
      return;
    }
    if (response.status === 409) {
      result.textContent = 'Não foi possível iniciar este teste. Confira os dados e a oferta. Se já possui conta, use o acesso ou a recuperação abaixo.';
      return;
    }
    if (!response.ok) throw new Error('trial unavailable');
    const payload = await response.json();
    if (payload.status !== 'trial_activation_pending') throw new Error('unexpected response');
    completed = true;
    form.hidden = true;
    status.textContent = 'Solicitação recebida';
    result.textContent = 'Confira seu e-mail para ativar a conta. Caso não encontre as instruções, utilize a recuperação de acesso.';
    // Keep the opaque key for retry after reload; the form's personal data is cleared.
    form.reset();
  } catch {
    result.textContent = 'Não foi possível confirmar a solicitação. Tente novamente com os mesmos dados para recuperar o resultado com segurança.';
  } finally {
    busy = false;
    fields.disabled = completed;
  }
});
void loadPlans();
