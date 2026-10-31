import { test, expect } from '@playwright/test';

const plan = { plan_id: 'growth', price_id: 'growth-monthly', display_name: 'Plano sintético', trial_days: 7 };
async function catalog(page, plans = [plan]) {
  await page.route('**/v1/public/trial-plans', async route => {
    expect(route.request().method()).toBe('POST');
    await route.fulfill({ json: { plans } });
  });
}
async function fill(page) {
  await page.getByLabel('Nome da empresa').fill('Empresa Sintética');
  await page.getByLabel('E-mail para ativação').fill('trial@example.test');
}

test('trial preserves request identity after response loss and reload without storing personal data', async ({ page }) => {
  await catalog(page);
  const requests = [];
  await page.context().addCookies([{ name: 'nfcore_session', value: 'existing-session', url: 'http://127.0.0.1:4173' }]);
  await page.route('**/v1/public/trials', async route => {
    requests.push({ headers: route.request().headers(), body: route.request().postDataJSON() });
    if (requests.length === 1) await route.abort();
    else await route.fulfill({ status: 200, json: { status: 'trial_activation_pending', replay: true } });
  });
  await page.goto('/trial.html');
  await fill(page);
  await page.getByRole('button', { name: 'Solicitar teste' }).click();
  await expect(page.locator('#trial-result')).toContainText('mesmos dados');
  await page.reload();
  await fill(page);
  await page.getByRole('button', { name: 'Solicitar teste' }).click();
  await expect(page.locator('#trial-result')).toContainText('Confira seu e-mail');
  expect(requests).toHaveLength(2);
  expect(requests[0].headers['idempotency-key']).toBe(requests[1].headers['idempotency-key']);
  for (const request of requests) {
    expect(request.headers.cookie).toBeUndefined();
    expect(request.headers.authorization).toBeUndefined();
    expect(request.headers['x-nfcore-signature']).toBeUndefined();
    expect(Object.keys(request.body).sort()).toEqual(['buyer_email', 'legal_name', 'plan_id', 'price_id']);
  }
  const stored = await page.evaluate(() => JSON.stringify(sessionStorage));
  expect(stored).not.toContain('trial@example.test');
  expect(stored).not.toContain('Empresa Sintética');
  await expect(page.locator('#trial-form')).toBeHidden();
});

for (const status of [403, 404, 503]) {
  test(`trial fails closed when catalog returns ${status}`, async ({ page }) => {
    await page.route('**/v1/public/trial-plans', route => route.fulfill({ status, json: { detail: 'unavailable' } }));
    await page.goto('/trial.html');
    await expect(page.locator('#trial-status')).toContainText('indisponíveis');
    await expect(page.locator('#trial-form')).toBeHidden();
    await expect(page.getByRole('link', { name: 'Já tenho uma conta / recuperar acesso' })).toHaveAttribute('href', 'index.html');
  });
}

test('empty catalog is honest and catalog names are rendered as text at mobile width', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 });
  await catalog(page, []);
  await page.goto('/trial.html');
  await expect(page.locator('#trial-status')).toContainText('Não há ofertas');
  await page.unroute('**/v1/public/trial-plans');
  await catalog(page, [{ ...plan, display_name: '<img src=x onerror=alert(1)>' }]);
  await page.getByRole('button', { name: 'Consultar ofertas novamente' }).click();
  await expect(page.locator('#trial-plan option')).toContainText('<img');
  await expect(page.locator('#trial-plan img')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

for (const status of [409, 429, 503]) {
  test(`trial handles ${status} without claiming activation`, async ({ page }) => {
    await catalog(page);
    await page.route('**/v1/public/trials', route => route.fulfill({ status, json: { detail: 'private-internal-message' } }));
    await page.goto('/trial.html');
    await fill(page);
    await page.getByRole('button', { name: 'Solicitar teste' }).click();
    await expect(page.locator('#trial-result')).not.toContainText('Enviando');
    await expect(page.locator('#trial-result')).not.toContainText('private-internal');
    await expect(page.locator('#trial-form')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Solicitar teste' })).toBeEnabled();
  });
}
