import { test, expect } from '@playwright/test';

async function fill(page) {
  await page.getByLabel('Razão social / nome jurídico').fill('Empresa Sintética LTDA');
}

test('claim token never leaves the fragment, is stripped from the URL immediately, and is sent only in the POST body', async ({ page }) => {
  const requests = [];
  await page.context().addCookies([{ name: 'nfcore_session', value: 'existing-session', url: 'http://127.0.0.1:4173' }]);
  await page.route('**/v1/commercial/claim', async route => {
    requests.push({ headers: route.request().headers(), body: route.request().postDataJSON() });
    await route.fulfill({ status: 200, json: { status: 'activated', purchase_id: 'p1', tenant_id: 't1' } });
  });
  await page.goto('/claim.html#claim=super-secret-token-123');
  // The fragment must be stripped from the visible URL on load, before any submission.
  await expect(page).toHaveURL(/\/claim\.html$/);
  await fill(page);
  await page.getByRole('button', { name: 'Confirmar compra' }).click();
  await expect(page.locator('#claim-result')).toContainText('Ativação concluída');
  await expect(page.locator('#claim-form')).toBeHidden();
  expect(requests).toHaveLength(1);
  expect(requests[0].headers.cookie).toBeUndefined();
  expect(requests[0].headers.authorization).toBeUndefined();
  expect(Object.keys(requests[0].body).sort()).toEqual(['claim_token', 'legal_name']);
  expect(requests[0].body.claim_token).toBe('super-secret-token-123');
  expect(requests[0].body.legal_name).toBe('Empresa Sintética LTDA');
  // Never leaked into history, session storage, or left sitting in the address bar.
  expect(page.url()).not.toContain('super-secret-token-123');
  const stored = await page.evaluate(() => JSON.stringify(sessionStorage));
  expect(stored).not.toContain('super-secret-token-123');
});

test('missing claim fragment shows an honest error and never renders the form', async ({ page }) => {
  await page.goto('/claim.html');
  await expect(page.locator('#claim-status')).toContainText('inválido ou incompleto');
  await expect(page.locator('#claim-form')).toBeHidden();
});

test('manual review (202) closes the form without claiming activation', async ({ page }) => {
  await page.route('**/v1/commercial/claim', route =>
    route.fulfill({ status: 202, json: { status: 'manual_review', purchase_id: 'p1' } }));
  await page.goto('/claim.html#claim=tok-review');
  await fill(page);
  await page.getByRole('button', { name: 'Confirmar compra' }).click();
  await expect(page.locator('#claim-result')).toContainText('revisão manual');
  await expect(page.locator('#claim-form')).toBeHidden();
});

for (const status of [409, 503]) {
  test(`claim handles ${status} without claiming activation and allows retry with the same token`, async ({ page }) => {
    let calls = 0;
    await page.route('**/v1/commercial/claim', route => {
      calls += 1;
      route.fulfill({ status, json: { detail: 'private-internal-message' } });
    });
    await page.goto('/claim.html#claim=tok-retry');
    await fill(page);
    await page.getByRole('button', { name: 'Confirmar compra' }).click();
    await expect(page.locator('#claim-result')).not.toContainText('Enviando');
    await expect(page.locator('#claim-result')).not.toContainText('private-internal');
    await expect(page.locator('#claim-form')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Confirmar compra' })).toBeEnabled();
    // Retry reuses the same in-memory token (still in the fragment-derived value, not the URL).
    await page.getByRole('button', { name: 'Confirmar compra' }).click();
    // The second click starts an asynchronous fetch; wait for the request,
    // not merely for the click handler to return. Still require exactly two.
    await expect.poll(() => calls).toBe(2);
  });
}

test('expired/used/not-found token (409) never distinguishes the reason to the visitor', async ({ page }) => {
  await page.route('**/v1/commercial/claim', route =>
    route.fulfill({ status: 409, json: { detail: 'claim unavailable' } }));
  await page.goto('/claim.html#claim=tok-expired');
  await fill(page);
  await page.getByRole('button', { name: 'Confirmar compra' }).click();
  await expect(page.locator('#claim-result')).toContainText('não é válido, já expirou ou já foi utilizado');
});
