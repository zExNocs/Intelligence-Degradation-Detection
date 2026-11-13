import { test, expect, type Page } from '@playwright/test';

const token = 'browser-fixture-token-not-a-secret';

async function login(page: Page) {
  await page.goto('/');
  await page.getByLabel('Access token').fill(token);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
}

async function navigate(page: Page, name: string) {
  await page.locator('nav').getByText(name, { exact: true }).click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
}

test('model pickers reopen the full cache after selection, refresh and manual entry', async ({
  page,
}) => {
  await login(page);
  const created = await page.request.post('/api/v1/accounts', {
    data: { name: 'Model switcher', api_key: 'fixture-key', default_model: 'fixture-model' },
  });
  const account = await created.json();
  await page.request.post(`/api/v1/accounts/${account.id}/models/refresh`);
  await navigate(page, 'Models');
  await page.getByRole('button', { name: 'Edit Model switcher', exact: true }).click();
  let dialog = page.getByRole('dialog');
  let model = dialog.getByLabel('Default model');
  await model.click();
  await expect(page.getByRole('option')).toHaveCount(3);
  await page.getByRole('option', { name: 'fixture-partial', exact: true }).click();
  await model.click();
  await expect(page.getByRole('option')).toHaveCount(3);
  await dialog.getByRole('button', { name: 'Refresh model catalogue' }).click();
  await model.click();
  await expect(page.getByRole('option')).toHaveCount(3);
  await expect(model).toHaveValue('fixture-partial');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.getByRole('button', { name: 'Edit Model switcher', exact: true }).click();
  dialog = page.getByRole('dialog');
  model = dialog.getByLabel('Default model');
  await model.click();
  await expect(page.getByRole('option')).toHaveCount(3);
  await model.fill('manual-deployment');
  await dialog.getByRole('textbox', { name: 'Name', exact: true }).click();
  await model.click();
  await expect(model).toHaveValue('manual-deployment');
  await expect(page.getByRole('option')).toHaveCount(3);
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();

  for (const name of ['Pelican', 'Comparison', 'ModelTrace', 'Other checks']) {
    await navigate(page, name);
    await page.getByRole('button', { name: 'Create test group' }).click();
    dialog = page.getByRole('dialog');
    await dialog.getByLabel('Select accounts').click();
    await page.getByRole('option', { name: 'Model switcher', exact: true }).click();
    await dialog.getByRole('textbox', { name: 'Name', exact: true }).click();
    model = dialog.getByRole('textbox', { name: 'Model', exact: true });
    await expect(model).toHaveValue('fixture-partial');
    await model.click();
    await expect(page.getByRole('option')).toHaveCount(3);
    await page.getByRole('option', { name: 'fixture-model', exact: true }).click();
    await model.click();
    await expect(page.getByRole('option')).toHaveCount(3);
    await dialog.getByRole('button', { name: 'Refresh model catalogue' }).click();
    await model.click();
    await expect(page.getByRole('option')).toHaveCount(3);
    await model.fill('slow');
    await expect(page.getByRole('option')).toHaveCount(1);
    await expect(page.getByRole('option', { name: 'fixture-slow', exact: true })).toBeVisible();
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  }
});

test('model-specific reasoning options require an explicit correction after switching models', async ({
  page,
}) => {
  await login(page);
  await page.request.post('/api/v1/accounts', {
    data: {
      name: 'Reasoning choices',
      api_key: 'fixture-key',
      default_model: 'fixture-model',
      default_effort: 'minimal',
    },
  });
  await navigate(page, 'Models');
  await page.getByRole('button', { name: 'Edit Reasoning choices', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Default model').fill('gpt-6.1-sol');
  await expect(
    dialog.getByText(
      'This model does not support the saved reasoning effort. Select a supported value or upstream default.',
    ),
  ).toBeVisible();
  await dialog.getByLabel('Reasoning effort').click();
  for (const value of ['low', 'medium', 'high', 'xhigh', 'max']) {
    await expect(page.getByRole('option', { name: value, exact: true })).toBeVisible();
  }
  await expect(page.getByRole('option', { name: 'none', exact: true })).toHaveCount(0);
  await expect(page.getByRole('option', { name: 'minimal', exact: true })).toHaveCount(0);
  await page.getByRole('option', { name: 'low', exact: true }).click();
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await navigate(page, 'Comparison');
  await page.getByRole('button', { name: 'Create test group' }).click();
  await dialog.getByLabel('Select accounts').click();
  await page.getByRole('option', { name: 'Reasoning choices', exact: true }).click();
  await dialog.getByRole('textbox', { name: 'Name', exact: true }).click();
  await expect(dialog.getByLabel('Reasoning effort')).toHaveValue('low');
  await dialog.getByLabel('Reasoning effort').click();
  await expect(page.getByRole('option', { name: 'minimal', exact: true })).toHaveCount(0);
  await expect(page.getByRole('option', { name: 'none', exact: true })).toHaveCount(0);
  await page.getByRole('option', { name: 'Upstream default', exact: true }).click();
});

test('accounts without a default model guide setup before a metered probe', async ({ page }) => {
  await login(page);
  await page.request.post('/api/v1/accounts', {
    data: { name: 'Needs a model', api_key: 'fixture-key' },
  });
  await navigate(page, 'Models');
  const card = page
    .locator('.account-card')
    .filter({ has: page.getByText('Needs a model', { exact: true }) });
  const before = await (await page.request.get('/api/v1/fixture/calls')).json();
  await expect(
    card.getByText('No default model yet. Choose a model and save before probing.'),
  ).toBeVisible();
  await card.getByRole('button', { name: 'Choose a model to probe' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Refresh model catalogue' }).click();
  await dialog.getByLabel('Default model').fill('fixture-model');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(await (await page.request.get('/api/v1/fixture/calls')).json()).toEqual(before);
  await card.getByRole('button', { name: 'Probe connection' }).click();
  await expect(card.getByText(/^Duration: \d+\.\d{2}s$/)).toBeVisible();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect
    .poll(async () => await (await page.request.get('/api/v1/fixture/calls')).json())
    .not.toEqual(before);
  await card.getByRole('button', { name: 'View probe' }).click();
  await expect(page.getByRole('dialog', { name: 'Result details' })).toBeVisible();
});

test('background probes stay visible across navigation and show failures on cards', async ({
  page,
}) => {
  await login(page);
  await page.evaluate(() => localStorage.setItem('idd-refresh', '0'));
  await page.reload();
  const account = await (
    await page.request.post('/api/v1/accounts', {
      data: { name: 'Background probe', api_key: 'fixture-key', default_model: 'fixture-slow' },
    })
  ).json();
  await navigate(page, 'Models');
  const card = page.locator(`[data-account-id="${account.id}"]`);
  await card.getByRole('button', { name: 'Probe connection' }).click();
  await expect(card.getByRole('button', { name: 'Probe connection' })).toBeDisabled();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await navigate(page, 'Dashboard');
  await navigate(page, 'Models');
  await expect(card.getByRole('button', { name: 'Probe connection' })).toBeDisabled();
  const probes = await (await page.request.get(`/api/v1/accounts/${account.id}/probes`)).json();
  expect(probes).toHaveLength(1);
  await page.request.post(`/api/v1/runs/${probes[0].id}/cancel`);
  await expect(card.getByText('cancelled', { exact: true })).toBeVisible();
  await expect(card.getByRole('button', { name: 'Probe connection' })).toBeEnabled();
  await page.request.put(`/api/v1/accounts/${account.id}`, {
    data: { name: account.name, default_model: 'fixture-failure' },
  });
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await card.getByRole('button', { name: 'Probe connection' }).click();
  await expect(card.getByText('Fixture upstream unavailable.')).toBeVisible();
  await expect(card.getByText('failed', { exact: true })).toBeVisible();
  await expect(page.getByRole('dialog')).not.toBeVisible();
});

test('account deletion confirms local cleanup and removes cards and empty groups', async ({
  page,
}) => {
  await login(page);
  const account = await (
    await page.request.post('/api/v1/accounts', {
      data: { name: 'Disposable account', api_key: 'fixture-key', default_model: 'fixture-model' },
    })
  ).json();
  const group = await (
    await page.request.post('/api/v1/groups', {
      data: {
        name: 'Disposable group',
        kind: 'other',
        prompt: 'Fixture',
        enabled: false,
        targets: [{ account_id: account.id, model: 'fixture-model' }],
      },
    })
  ).json();
  await navigate(page, 'Models');
  const card = page.locator(`[data-account-id="${account.id}"]`);
  await card.getByRole('button', { name: 'Delete Disposable account', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Delete account' });
  await expect(dialog.getByText(/Historical results are retained/)).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: 'Delete Disposable account', exact: true }).click();
  await dialog.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(card).toHaveCount(0);
  expect(
    (await (await page.request.get('/api/v1/groups')).json()).map(
      (item: { id: string }) => item.id,
    ),
  ).not.toContain(group.id);
  await page.reload();
  await navigate(page, 'Models');
  await expect(card).toHaveCount(0);
});

test('account cards drag by handle, persist after reload, and recover from save failure', async ({
  page,
}) => {
  await login(page);
  await navigate(page, 'Models');
  const cards = page.locator('.account-card');
  const original = await cards.evaluateAll((items) =>
    items.map((item) => item.getAttribute('data-account-id')),
  );
  const before = await (await page.request.get('/api/v1/fixture/calls')).json();
  const first = cards.nth(0).getByRole('button', { name: /^Move / });
  const second = cards.nth(1);
  const start = (await first.boundingBox())!;
  const end = (await second.boundingBox())!;
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith('/accounts/order') && response.request().method() === 'PUT',
  );
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.mouse.move(end.x + end.width / 2, end.y + 40, { steps: 15 });
  await page.mouse.up();
  expect((await saved).status()).toBe(204);
  const expected = [original[1], original[0], ...original.slice(2)];
  await expect
    .poll(() =>
      cards.evaluateAll((items) => items.map((item) => item.getAttribute('data-account-id'))),
    )
    .toEqual(expected);
  await page.reload();
  await navigate(page, 'Models');
  await expect
    .poll(() =>
      cards.evaluateAll((items) => items.map((item) => item.getAttribute('data-account-id'))),
    )
    .toEqual(expected);
  await page.route('**/api/v1/accounts/order', (route) =>
    route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({ message: 'Fixture stale order.' }),
    }),
  );
  const handle = cards.nth(0).getByRole('button', { name: /^Move / });
  await handle.focus();
  // Allow the keyboard sensor's deferred listener to attach before arrow input.
  await page.keyboard.press('Space', { delay: 50 });
  await expect(handle).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('status')).toHaveText('Card position 1.');
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('status')).toHaveText('Card position 2.');
  await page.keyboard.press('Space');
  await expect(page.getByText('Fixture stale order.')).toBeVisible();
  await expect
    .poll(() =>
      cards.evaluateAll((items) => items.map((item) => item.getAttribute('data-account-id'))),
    )
    .toEqual(expected);
  expect(await (await page.request.get('/api/v1/fixture/calls')).json()).toEqual(before);
});

test('all four check pages support keyboard card ordering without running checks', async ({
  page,
}) => {
  await login(page);
  for (const [kind, name] of [
    ['pelican', 'Pelican'],
    ['comparison', 'Comparison'],
    ['modeltrace', 'ModelTrace'],
    ['other', 'Other checks'],
  ]) {
    const account = await (
      await page.request.post('/api/v1/accounts', {
        data: { name: `Sorting ${kind}`, api_key: 'fixture-key' },
      })
    ).json();
    const groups: string[] = [];
    for (let index = 0; index < 2; index++) {
      const group = await (
        await page.request.post('/api/v1/groups', {
          data: {
            name: `Sorting ${kind} ${index}`,
            kind,
            prompt: 'Fixture',
            enabled: false,
            targets: [{ account_id: account.id, model: 'fixture-model' }],
          },
        })
      ).json();
      groups.push(group.id);
    }
    const before = await (await page.request.get('/api/v1/fixture/calls')).json();
    await navigate(page, name);
    const handle = page.getByRole('button', { name: `Move Sorting ${kind} 1`, exact: true });
    await handle.scrollIntoViewIfNeeded();
    await handle.focus();
    await page.keyboard.press('Space', { delay: 50 });
    await expect(handle).toHaveAttribute('aria-pressed', 'true');
    const position = (await page.locator('[data-group-id]').count()) - 1;
    await expect(page.getByRole('status')).toHaveText(`Card position ${position + 1}.`);
    await page.keyboard.press('ArrowUp');
    await expect(page.getByRole('status')).toHaveText(`Card position ${position}.`);
    await page.keyboard.press('Space');
    const ordered = () =>
      page
        .locator('[data-group-id]')
        .evaluateAll((items) => items.map((item) => item.getAttribute('data-group-id')));
    await expect.poll(async () => (await ordered()).slice(-2)).toEqual(groups.slice().reverse());
    await page.reload();
    await navigate(page, name);
    await expect.poll(async () => (await ordered()).slice(-2)).toEqual(groups.slice().reverse());
    expect(await (await page.request.get('/api/v1/fixture/calls')).json()).toEqual(before);
  }
});

test('source connection fields explain URL, credentials, and saved sync configuration', async ({
  page,
}) => {
  await login(page);
  await navigate(page, 'Settings');
  await expect(page.getByText(/Include any reverse-proxy prefix/)).toBeVisible();
  await expect(page.getByText(/accounts.read alone is insufficient/)).toBeVisible();
  await expect(page.getByText(/Sync now uses the saved connection/)).toBeVisible();
  await page.getByRole('button', { name: 'Language', exact: true }).click();
  await page.getByRole('menuitem', { name: '简体中文' }).click();
  await expect(page.getByText(/不要附加 \/api\/v1/)).toBeVisible();
  await expect(page.getByText(/仅 accounts.read 不足/)).toBeVisible();
});

test('accounts, shared catalogue, group creation, results, and read-only refresh', async ({
  page,
}) => {
  await login(page);
  await navigate(page, 'Models');
  await page.getByRole('button', { name: 'Add account' }).click();
  await page.getByRole('menuitem', { name: 'Direct API' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Name').fill('Browser account');
  await dialog.getByLabel('API key').fill('fixture-not-a-real-key');
  await dialog.getByRole('button', { name: 'Refresh model catalogue' }).click();
  await dialog.getByLabel('Default model').fill('fixture-model');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByText('Browser account', { exact: true })).toBeVisible();
  await navigate(page, 'Comparison');
  await page.getByRole('button', { name: 'Create test group' }).click();
  await dialog.getByLabel('Name').fill('Browser comparison');
  await dialog.getByLabel('Select accounts').click();
  await page.getByRole('option', { name: 'Browser account', exact: true }).click();
  await dialog.getByLabel('Name').click();
  await expect(dialog.getByRole('textbox', { name: 'Model', exact: true })).toHaveValue(
    'fixture-model',
  );
  await dialog.getByRole('button', { name: 'Preview schedule' }).click();
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const group = page
    .locator('.matrix-panel')
    .filter({ has: page.getByRole('heading', { name: 'Browser comparison' }) });
  await group.getByRole('button', { name: 'Run group' }).click();
  await expect
    .poll(
      async () =>
        (await (await page.request.get('/api/v1/groups')).json()).find(
          (g: { recipe: { name: string } }) => g.recipe.name === 'Browser comparison',
        ).active_runs,
    )
    .toEqual({});
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(group.locator('.result-cell.good')).toHaveCount(1);
  await group.locator('.result-cell.good').click();
  await expect(dialog.getByText('Tokens: 118', { exact: true })).toBeVisible();
  await dialog.getByRole('tab', { name: 'Prompt', exact: true }).click();
  await expect(dialog.getByText(/Return only JSON/)).toBeVisible();
  await dialog.locator('.mantine-Modal-close').click();
  const before = await (await page.request.get('/api/v1/fixture/calls')).json();
  await page.getByRole('button', { name: 'Auto refresh: 15s' }).click();
  await page.getByRole('menuitem', { name: '5 seconds', exact: true }).click();
  let reads = 0;
  page.on('request', (request) => {
    if (request.method() === 'GET' && request.url().endsWith('/groups')) reads++;
  });
  await expect.poll(() => reads, { timeout: 8_000 }).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  expect(await (await page.request.get('/api/v1/fixture/calls')).json()).toEqual(before);
  const baseline = page
    .locator('.matrix-panel')
    .filter({ has: page.getByRole('heading', { name: 'JSON baseline' }) });
  await expect(baseline.getByRole('button', { name: 'More history' })).toBeEnabled();
  await baseline.getByRole('button', { name: 'More history' }).click();
  await expect(baseline.getByRole('button', { name: 'Newer' })).toBeEnabled();
  await page.screenshot({
    path: '../../../temp/doc/validation/browser/comparison-desktop.png',
    fullPage: true,
    animations: 'disabled',
  });
});

test('language, dark mode, mobile navigation and containment', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: 'Language', exact: true }).click();
  await page.getByRole('menuitem', { name: '简体中文' }).click();
  await expect(page.getByRole('heading', { name: '主页', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '外观', exact: true }).click();
  await page.getByText('深色', { exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-mantine-color-scheme', 'dark');
  await page.getByRole('button', { name: '外观', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await page.locator('nav').getByText('鹈鹕检测', { exact: true }).click();
  await expect(page.getByRole('heading', { name: '鹈鹕检测', exact: true })).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
  await expect(page.frameLocator('iframe').first().locator('#script-status')).toHaveText(
    'JavaScript is active',
  );
  await page.screenshot({
    path: '../../../temp/doc/validation/browser/pelican-mobile-zh-dark.png',
    fullPage: true,
  });
});

test('cancellation preserves evidence and excludes dashboard metrics; fingerprint candidates render', async ({
  page,
}) => {
  await login(page);
  const accounts = await (await page.request.get('/api/v1/accounts')).json();
  const account = accounts.find((item: { name: string }) => item.name === 'North API');
  const before = await (await page.request.get('/api/v1/dashboard')).json();
  const slow = await (
    await page.request.post('/api/v1/groups', {
      data: {
        name: 'Cancellable fixture',
        kind: 'other',
        prompt: 'Wait until cancelled',
        enabled: false,
        targets: [{ account_id: account.id, model: 'fixture-slow' }],
      },
    })
  ).json();
  const queued = await (await page.request.post(`/api/v1/groups/${slow.id}/run`)).json();
  await navigate(page, 'Other checks');
  await page.getByRole('button', { name: 'Cancel run North API' }).click();
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/v1/runs/${queued.queued[0]}`)).json()).status,
    )
    .toBe('cancelled');
  await expect(page.locator('.result-cell.exception')).toHaveCount(1);
  const after = await (await page.request.get('/api/v1/dashboard')).json();
  expect(after.runs_24h).toBe(before.runs_24h);
  expect(after.total_tokens).toBe(before.total_tokens);
  const fingerprint = await (
    await page.request.post('/api/v1/groups', {
      data: {
        name: 'Fingerprint fixture',
        kind: 'modeltrace',
        challenge_ids: ['intuition-294'],
        enabled: false,
        expected_identity: 'gpt',
        targets: [{ account_id: account.id, model: 'fixture-fingerprint' }],
      },
    })
  ).json();
  const batch = await (await page.request.post(`/api/v1/groups/${fingerprint.id}/run`)).json();
  await expect
    .poll(
      async () => (await (await page.request.get(`/api/v1/runs/${batch.queued[0]}`)).json()).status,
    )
    .toBe('completed');
  await navigate(page, 'ModelTrace');
  await page.locator(`[data-group-id="${fingerprint.id}"] .result-cell`).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('columnheader', { name: 'Probability within bank' })).toBeVisible();
  await expect(dialog.locator('tbody tr')).toHaveCount(18);
  await expect(dialog).toHaveCSS('opacity', '1');
  await page.screenshot({
    path: '../../../temp/doc/validation/browser/fingerprint-detail.png',
    animations: 'disabled',
  });
});

test('first visit follows browser language and falls back to English', async ({ browser }) => {
  for (const [locale, heading] of [
    ['zh-CN', '私有工作台'],
    ['fr-FR', 'Private workspace'],
  ]) {
    const context = await browser.newContext({ locale });
    try {
      const page = await context.newPage();
      await page.goto('http://127.0.0.1:8765');
      await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
    } finally {
      await context.close();
    }
  }
});

test('preview executes inline JS while host access, requests and navigation are blocked', async ({
  page,
  context,
}) => {
  await login(page);
  await navigate(page, 'Pelican');
  await page.locator('.result-cell').first().click();
  const dialog = page.getByRole('dialog');
  const frame = dialog.frameLocator('iframe');
  await expect(frame.locator('#script-status')).toHaveText('JavaScript is active');
  await frame.getByRole('button', { name: 'Try animation' }).click();
  await expect(frame.locator('#script-status')).toHaveText('Interactive preview works');
  await expect(dialog).toHaveCSS('opacity', '1');
  await page.screenshot({
    path: '../../../temp/doc/validation/browser/pelican-detail.png',
    animations: 'disabled',
  });
  const element = await dialog.locator('iframe').elementHandle();
  const preview = await element!.contentFrame();
  const outbound: string[] = [];
  const blocked = new Map<string, string>();
  page.on('request', (request) => {
    if (request.url().includes('isolation-probe')) outbound.push(request.url());
  });
  page.on('requestfailed', (request) => {
    if (request.url().includes('isolation-probe'))
      blocked.set(request.url(), request.failure()?.errorText ?? '');
  });
  const outcome = await preview!.evaluate(async () => {
    let host = false,
      storage = false,
      network = false,
      popup = false,
      cookies = false,
      privateApi = false;
    try {
      void parent.document.body;
      host = true;
    } catch {}
    try {
      localStorage.setItem('probe', 'value');
      storage = true;
    } catch {}
    try {
      void document.cookie;
      cookies = true;
    } catch {}
    try {
      await fetch('https://example.invalid/isolation-probe');
      network = true;
    } catch {}
    try {
      await fetch('http://127.0.0.1:8765/api/v1/settings', { credentials: 'include' });
      privateApi = true;
    } catch {}
    try {
      popup = !!window.open('https://example.invalid/isolation-probe');
    } catch {}
    const img = document.createElement('img');
    img.src = 'https://example.invalid/isolation-probe.png';
    document.body.append(img);
    const script = document.createElement('script');
    script.src = 'https://example.invalid/isolation-probe.js';
    document.body.append(script);
    const form = document.createElement('form');
    form.action = 'https://example.invalid/isolation-probe';
    document.body.append(form);
    form.submit();
    try {
      top!.location.href = 'https://example.invalid/isolation-probe';
    } catch {}
    return { host, storage, network, popup, cookies, privateApi };
  });
  expect(outcome).toEqual({
    host: false,
    storage: false,
    network: false,
    popup: false,
    cookies: false,
    privateApi: false,
  });
  await preview!.evaluate(() => {
    location.href = 'https://example.invalid/isolation-probe';
  });
  // Chromium emits request intentions even when CSP blocks them before network dispatch.
  await expect
    .poll(() =>
      outbound.every(
        (url) => blocked.get(url) === 'csp' || blocked.get(url)?.includes('ERR_BLOCKED_BY_CSP'),
      ),
    )
    .toBeTruthy();
  expect(context.pages()).toHaveLength(1);
  expect(page.url()).toBe('http://127.0.0.1:8765/');
});
