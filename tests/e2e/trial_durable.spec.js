import { test, expect } from '@playwright/test';

test('browser trial survives committed response loss and provisions one canonical owner/subscription', async ({ page }) => {
  test.skip(!process.env.NFCORE_TEST_POSTGRES_DSN, 'Disposable PostgreSQL required; mandatory in CI');
  const origin = 'https://127.0.0.1:4176';
  let lost = false;
  let firstKey;
  await page.route('**/v1/public/trials', async route => {
    const key = route.request().headers()['idempotency-key'];
    const upstream = await route.fetch();
    if (!lost) {
      expect(upstream.status()).toBe(201);
      expect(await upstream.text()).not.toContain('reset_token');
      firstKey = key;
      lost = true;
      await route.fulfill({ status: 503, json: { detail: 'synthetic response loss after commit' } });
    } else {
      expect(key).toBe(firstKey);
      expect(upstream.status()).toBe(200);
      expect((await upstream.json()).replay).toBe(true);
      await route.fulfill({ response: upstream });
    }
  });
  await page.goto(`${origin}/trial.html`);
  await page.getByLabel('Nome da empresa').fill('Empresa Browser Sintética');
  await page.getByLabel('E-mail para ativação').fill('browser-owner@example.test');
  await page.getByRole('button', { name: 'Solicitar teste' }).click();
  await expect(page.locator('#trial-result')).toContainText('mesmos dados');
  const before = await (await page.request.get(`${origin}/__test/trial-proof`)).json();
  expect(Object.values(before.counts)).toEqual([1, 1, 1, 1]);
  expect(before.deliveries).toBe(1);
  expect(before.owner_role).toBe('owner');
  expect(before.subscription_status).toBe('trial');
  expect(Date.parse(before.period_end) - Date.parse(before.period_start)).toBe(7 * 86400000);
  await page.reload();
  await page.getByLabel('Nome da empresa').fill('Empresa Browser Sintética');
  await page.getByLabel('E-mail para ativação').fill('browser-owner@example.test');
  await page.getByRole('button', { name: 'Solicitar teste' }).click();
  await expect(page.locator('#trial-result')).toContainText('Confira seu e-mail');
  const after = await (await page.request.get(`${origin}/__test/trial-proof`)).json();
  expect(after.counts).toEqual(before.counts);
  expect(after.subscription_id).toBe(before.subscription_id);
  expect(after.period_end).toBe(before.period_end);
  expect(after.deliveries).toBe(2);
  expect(await page.content()).not.toContain(after.reset_token);
  const password = 'Synthetic-Trial-Browser-2026';
  await page.goto(`${origin}/index.html#token=${encodeURIComponent(after.reset_token)}`);
  await expect(page).not.toHaveURL(/token=/);
  await page.locator('#password-reset-new-password').fill(password);
  await page.getByRole('button', { name: 'Alterar senha' }).click();
  await expect(page.locator('#login-error')).toContainText('Senha alterada');
  await page.locator('#login-email').fill('browser-owner@example.test');
  await page.locator('#login-password').fill(password);
  const loggedIn = page.waitForResponse(response => response.url().endsWith('/v1/auth/login'));
  await page.getByRole('button', { name: 'Entrar', exact: true }).click();
  expect((await loggedIn).status()).toBe(200);
  await expect(page.locator('#app-shell')).toBeVisible();
  const final = await (await page.request.get(`${origin}/__test/trial-proof`)).json();
  expect(final.counts).toEqual(before.counts);
});
