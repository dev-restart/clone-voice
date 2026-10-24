import { expect, test, type Page } from '@playwright/test';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';

const api = process.env.E2E_API_URL || 'http://127.0.0.1:8011';
let upstream: Server;
let base = '';
let calls: { path: string; model?: string }[] = [];

test.beforeAll(async () => {
 // Only the dedicated test ports may receive disposable profiles and fake keys.
 expect(['http://127.0.0.1:8011', 'http://127.0.0.1:8013']).toContain(api);
 upstream = createServer(async (req, res) => {
  let raw = ''; for await (const chunk of req) raw += chunk;
  const body = raw ? JSON.parse(raw) : {};
  calls.push({ path: req.url || '', model: body.model });
  res.setHeader('Content-Type', 'application/json');
  if (req.url?.endsWith('/models')) return res.end(JSON.stringify({ data: [{ id: 'qa-alpha', display_name: 'QA Alpha' }, { id: 'qa-beta', display_name: 'QA Beta' }] }));
  if (req.url?.endsWith('/messages')) return res.end(JSON.stringify({ content: [{ type: 'text', text: 'OK' }], stop_reason: 'end_turn' }));
  if (req.url?.endsWith('/responses')) return res.end(JSON.stringify({ status: 'completed', output: [{ type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'OK' }] }] }));
  res.end(JSON.stringify({ choices: [{ message: { content: 'OK' }, finish_reason: 'stop' }] }));
 });
 await new Promise<void>(resolve => upstream.listen(0, '127.0.0.1', resolve));
 base = `http://127.0.0.1:${(upstream.address() as AddressInfo).port}/v1`;
});
test.afterAll(async () => { await new Promise<void>(resolve => upstream.close(() => resolve())); });

async function openSettings(page: Page) {
 await page.goto(process.env.APP_URL || 'http://localhost:5186');
 await page.getByRole('button', { name: '설정', exact: true }).first().click();
 await page.getByRole('tab', { name: 'AI 연결', exact: true }).click();
 const panel = page.locator('.ai-connections');
 await expect(panel, 'API connections are available without opening advanced settings').toBeVisible();
 await expect(panel.getByRole('button', { name: '연결 추가', exact: true })).toBeEnabled();
 return panel;
}

async function addConnection(page: Page, name: string, protocol = 'openai_chat', keyed = false) {
 const panel = page.locator('.ai-connections');
 await panel.getByRole('button', { name: '연결 추가', exact: true }).click();
 await panel.getByLabel('연결 이름', { exact: true }).fill(name);
 await panel.getByLabel('API 형식', { exact: true }).selectOption(protocol);
 await panel.getByLabel('기본 API 주소', { exact: true }).fill(base);
 await panel.getByLabel('인증 방식', { exact: true }).selectOption(keyed ? 'bearer' : 'none');
 if (keyed) {
  await panel.getByLabel('키 보관 방식', { exact: true }).selectOption('private_file');
  await panel.getByLabel('API 키', { exact: true }).fill('fake-e2e-test-key');
 }
 await panel.getByRole('button', { name: '모델 직접 추가', exact: true }).click();
 await panel.getByLabel('1번째 모델 ID', { exact: true }).fill('qa-alpha');
 await panel.getByLabel('모델 표시 이름', { exact: true }).fill('QA Alpha');
 const responsePromise = page.waitForResponse(r => r.url() === `${api}/api/ai/connections` && r.request().method() === 'POST');
 await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
 const response = await responsePromise;
 expect(response.status()).toBe(201);
 const profile = (await response.json()).profile;
 await expect(panel.getByRole('button', { name: '응답 테스트', exact: true })).toBeEnabled();
 return profile;
}

async function cleanup(page: Page, ids: string[], originalSelection?: object) {
 const current = await (await page.request.get(`${api}/api/ai/connections`)).json();
 await page.request.put(`${api}/api/ai/routing`, { data: { expected_revision: current.revision } });
 if (originalSelection) await page.request.put(`${api}/api/ai/providers/selection`, { data: originalSelection });
 for (const p of (await (await page.request.get(`${api}/api/ai/connections`)).json()).profiles) {
  if (ids.includes(p.id)) await page.request.delete(`${api}/api/ai/connections/${p.id}?expected_revision=${p.revision}`);
 }
}

test('API profiles and task selection work while provider status is delayed or unavailable', async ({ page }) => {
 const ids: string[] = [];
 let release!: () => void;
 const pending = new Promise<void>(resolve => { release = resolve; });
 let holding = true;
 await page.route('**/api/ai/providers', async route => {
  if (route.request().method() === 'GET') {
   if (holding) await pending;
   return route.fulfill({ status: 503, json: { detail: 'QA delayed provider status unavailable' } });
  }
  await route.continue();
 });
 try {
  const panel = await openSettings(page);
  await expect(panel.getByText('로컬·구독 AI 상태를 확인하고 있습니다.', { exact: false })).toBeVisible();
  const profile = await addConnection(page, 'QA delayed provider status ' + Date.now());
  ids.push(profile.id);
  await panel.locator('summary').filter({ hasText: '작업별 AI 설정' }).click();
  const value = JSON.stringify({ provider_id: profile.id, model_id: 'qa-alpha' });
  await panel.locator('#task-sound_prompt').selectOption(value);
  await panel.getByRole('button', { name: '작업별 AI 저장', exact: true }).click();
  await expect(panel.getByRole('button', { name: '작업별 AI 저장', exact: true })).toBeDisabled();
  const persisted = await (await page.request.get(api + '/api/ai/connections')).json();
  expect(persisted.routing.sound_prompt).toEqual({ provider_id: profile.id, model_id: 'qa-alpha' });
  holding = false; release();
  await expect(panel.getByRole('status').filter({ hasText: 'API 연결은 계속 관리할 수 있습니다.' })).toBeVisible();
  await expect(panel.getByRole('button', { name: '연결 추가', exact: true })).toBeEnabled();
  await expect(panel.locator('#task-sound_prompt')).toHaveValue(value);
 } finally {
  holding = false; release();
  await cleanup(page, ids);
 }
});

test('named profiles persist, discover models, test three protocols and select a task', async ({ page }) => {
 const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
 const panel = await openSettings(page);
 const ids: string[] = [];
 const original = (await (await page.request.get(`${api}/api/ai/providers`)).json()).selection;
 try {
  for (const protocol of ['openai_chat', 'anthropic_messages', 'openai_responses']) {
   const name = `QA ${protocol} ${Date.now()}`;
   const p = await addConnection(page, name, protocol);
   ids.push(p.id);
   await panel.getByRole('button', { name: '응답 테스트', exact: true }).click();
   await expect(panel.getByText('확인 지시와 일치', { exact: false })).toBeVisible();
   await panel.getByRole('button', { name: '모델 목록 불러오기', exact: true }).click();
   await panel.getByLabel('조회한 모델', { exact: true }).selectOption('qa-beta');
   await panel.getByRole('button', { name: '모델 추가', exact: true }).click();
   await expect(panel.getByLabel('2번째 모델 ID', { exact: true })).toHaveValue('qa-beta');
   await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
   await expect(panel.getByRole('button', { name: '응답 테스트', exact: true })).toBeEnabled();
   await panel.getByRole('button', { name: '닫기', exact: true }).click();
  }
  expect(calls.some(c => c.path === '/v1/chat/completions')).toBe(true);
  expect(calls.some(c => c.path === '/v1/messages')).toBe(true);
  expect(calls.some(c => c.path === '/v1/responses')).toBe(true);
  await panel.getByLabel('기본 AI', { exact: true }).selectOption(JSON.stringify({ provider_id: ids[0], model_id: 'qa-alpha' }));
  await panel.getByRole('button', { name: '기본 AI 저장', exact: true }).click();
  await expect(panel.getByRole('button', { name: '기본 AI 저장', exact: true })).toBeDisabled();
  await panel.locator('summary').filter({ hasText: '작업별 AI 설정' }).click();
  const route = { provider_id: ids[1], model_id: 'qa-beta' };
  await panel.getByLabel('대본 작성·다듬기', { exact: true }).selectOption(JSON.stringify(route));
  await panel.getByRole('button', { name: '작업별 AI 저장', exact: true }).click();
  await expect(panel.getByRole('button', { name: '작업별 AI 저장', exact: true })).toBeDisabled();
  const fresh = await (await page.request.get(`${api}/api/ai/connections`)).json();
  expect(fresh.routing.writing).toEqual(route);
  await page.reload();
  await openSettings(page);
  await expect(panel.getByLabel('기본 AI', { exact: true })).toHaveValue(JSON.stringify({ provider_id: ids[0], model_id: 'qa-alpha' }));
  expect(errors).toEqual([]);
 } finally { await cleanup(page, ids, original); }
});

test('key is masked, copied settings omit key, unsaved edits survive refresh and save failure', async ({ page }) => {
 const panel = await openSettings(page); const ids: string[] = [];
 try {
  const name = `QA keyed ${Date.now()}`;
  const p = await addConnection(page, name, 'openai_chat', true); ids.push(p.id);
  await expect(panel.getByLabel('API 키', { exact: true })).toHaveValue('');
  await panel.getByLabel('연결 이름', { exact: true }).fill(name + ' unsaved');
  await panel.getByRole('button', { name: 'AI 연결 새로고침', exact: true }).click();
  await expect(panel.getByLabel('연결 이름', { exact: true })).toHaveValue(name + ' unsaved');
  await page.route(`**/api/ai/connections/${p.id}`, async route => {
   if (route.request().method() === 'PUT') await route.fulfill({ status: 503, json: { detail: 'Test save failure' } }); else await route.fallback();
  });
  await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('Test save failure');
  await expect(panel.getByLabel('연결 이름', { exact: true })).toHaveValue(name + ' unsaved');
  await page.unroute(`**/api/ai/connections/${p.id}`);
  await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
  await expect(panel.getByRole('button', { name: '응답 테스트', exact: true })).toBeEnabled();
  await panel.getByRole('button', { name: name + ' unsaved 설정 복사', exact: true }).click();
  await expect(panel.getByLabel('API 키', { exact: true })).toHaveValue('');
  await expect(panel.getByLabel('연결 이름', { exact: true })).toHaveValue(name + ' unsaved 복사');
  const publicText = await (await page.request.get(`${api}/api/ai/connections`)).text();
  expect(publicText).not.toContain('fake-e2e-test-key');
  expect(publicText).not.toContain('credential_ref');
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('fake-e2e-test-key');
  expect(await page.evaluate(() => JSON.stringify(sessionStorage))).not.toContain('fake-e2e-test-key');
 } finally { await cleanup(page, ids); }
});

test('destination change requires key confirmation and duplicate names preserve edits', async ({ page }) => {
 const panel = await openSettings(page); const ids: string[] = [];
 try {
  const name = `QA destination ${Date.now()}`;
  const p = await addConnection(page, name, 'openai_chat', true); ids.push(p.id);
  await panel.getByLabel('기본 API 주소', { exact: true }).fill(base+'/changed');
  await expect(panel.getByRole('button', { name: '연결 저장', exact: true })).toBeDisabled();
  await panel.getByLabel('주소·API 형식·인증 변경 확인', { exact: true }).check();
  await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
  await expect(panel.getByRole('alert')).toBeVisible();
  await panel.getByLabel('저장된 키 지우기', { exact: true }).check();
  await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
  await expect(panel.getByRole('button', { name: '연결 저장', exact: true })).toBeEnabled();
  await expect.poll(async () => (await (await page.request.get(`${api}/api/ai/connections`)).json()).profiles.find((x: { id: string }) => x.id === p.id)?.has_api_key).toBe(false);
  await panel.getByRole('button', { name: '닫기', exact: true }).click();
  await panel.getByRole('button', { name: '연결 추가', exact: true }).click();
  await panel.getByLabel('연결 이름', { exact: true }).fill(name);
  await panel.getByLabel('기본 API 주소', { exact: true }).fill(base);
  await panel.getByLabel('인증 방식', { exact: true }).selectOption('none');
  await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
  await expect(panel.getByRole('alert')).toBeVisible();
  await expect(panel.getByLabel('연결 이름', { exact: true })).toHaveValue(name);
 } finally { await cleanup(page, ids); }
});

test('saving a connection preserves staged task choices and advances their revision', async ({ page }) => {
 const panel = await openSettings(page); const ids: string[] = [];
 try {
  const name = `QA staged ${Date.now()}`;
  const p = await addConnection(page, name); ids.push(p.id);
  await panel.locator('summary').filter({ hasText: '작업별 AI 설정' }).click();
  const selection = { provider_id: p.id, model_id: 'qa-alpha' };
  await panel.getByLabel('대본 작성·다듬기', { exact: true }).selectOption(JSON.stringify(selection));
  await panel.getByLabel('연결 이름', { exact: true }).fill(name + ' renamed');
  await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
  await expect(panel.getByRole('button', { name: '응답 테스트', exact: true })).toBeEnabled();
  await expect(panel.getByLabel('대본 작성·다듬기', { exact: true })).toHaveValue(JSON.stringify(selection));
  await panel.getByRole('button', { name: '작업별 AI 저장', exact: true }).click();
  await expect(panel.getByRole('button', { name: '작업별 AI 저장', exact: true })).toBeDisabled();
  expect((await (await page.request.get(`${api}/api/ai/connections`)).json()).routing.writing).toEqual(selection);
  await panel.getByRole('button', { name: '응답 테스트', exact: true }).click();
  await expect(panel.locator('.profile-row').filter({ hasText: name + ' renamed' }).locator('.badge')).toHaveText('모델 응답 확인');
  await panel.getByLabel('연결 이름', { exact: true }).fill(name + ' revision');
  await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
  await expect(panel.locator('.profile-row').filter({ hasText: name + ' revision' }).locator('.badge')).toHaveText('등록됨 · 미검증');
 } finally { await cleanup(page, ids); }
});

test('successful save is not reported as failed when follow-up catalog refresh fails', async ({ page }) => {
 const panel = await openSettings(page); const ids: string[] = [];
 try {
  const name = `QA refresh ${Date.now()}`;
  const p = await addConnection(page, name, 'openai_chat', true); ids.push(p.id);
  await panel.getByLabel('연결 이름', { exact: true }).fill(name + ' saved');
  await page.route('**/api/ai/providers', route => route.fulfill({ status: 503, json: { detail: 'Simulated catalog outage' } }));
  await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
  await expect(panel.getByRole('status').filter({ hasText: '저장은 완료했지만' })).toBeVisible();
  await expect(panel.getByRole('alert')).toHaveCount(0);
  await expect(panel.getByLabel('API 키', { exact: true })).toHaveValue('');
  const stored = (await (await page.request.get(`${api}/api/ai/connections`)).json()).profiles.find((x: { id: string }) => x.id === p.id);
  expect(stored.name).toBe(name + ' saved');
  expect(stored.has_api_key).toBe(true);
 } finally { await page.unroute('**/api/ai/providers'); await cleanup(page, ids); }
});

test('mobile presets and model editor stay within viewport, persisted profile can be deleted', async ({ page }) => {
 await page.setViewportSize({ width: 390, height: 844 });
 const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
 const panel = await openSettings(page); const ids: string[] = [];
 try {
  await panel.getByRole('button', { name: '연결 추가', exact: true }).click();
  await panel.getByLabel('빠른 설정', { exact: true }).selectOption('deepseek');
  await expect(panel.getByLabel('기본 API 주소', { exact: true })).toHaveValue('https://api.deepseek.com');
  await expect(panel.getByLabel('API 형식', { exact: true })).toHaveValue('openai_chat');
  await expect(panel.getByLabel('인증 방식', { exact: true })).toHaveValue('bearer');
  await panel.getByLabel('빠른 설정', { exact: true }).selectOption('openrouter');
  await expect(panel.getByLabel('기본 API 주소', { exact: true })).toHaveValue('https://openrouter.ai/api/v1');
  await expect(panel.getByLabel('API 형식', { exact: true })).toHaveValue('openai_chat');
  await expect(panel.getByLabel('인증 방식', { exact: true })).toHaveValue('bearer');
  await panel.getByLabel('빠른 설정', { exact: true }).selectOption('anthropic');
  await expect(panel.getByLabel('API 형식', { exact: true })).toHaveValue('anthropic_messages');
  await expect(panel.getByLabel('인증 방식', { exact: true })).toHaveValue('x-api-key');
  await panel.getByLabel('기본 API 주소', { exact: true }).fill(base);
  await panel.getByLabel('인증 방식', { exact: true }).selectOption('none');
  const name = `QA mobile ${Date.now()}`;
  await panel.getByLabel('연결 이름', { exact: true }).fill(name);
  await panel.getByRole('button', { name: '모델 직접 추가', exact: true }).click();
  await panel.getByLabel('1번째 모델 ID', { exact: true }).fill('qa-alpha');
  const response = page.waitForResponse(r => r.url() === `${api}/api/ai/connections` && r.request().method() === 'POST');
  await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
  ids.push((await (await response).json()).profile.id);
  await expect(panel.getByRole('button', { name: '응답 테스트', exact: true })).toBeEnabled();
  await panel.getByRole('button', { name: '응답 테스트', exact: true }).click();
  await expect(panel.getByText('확인 지시와 일치', { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: 'test-results/ai-connections-mobile.png', fullPage: true });
  await panel.getByRole('button', { name: `${name} 삭제`, exact: true }).click();
  await panel.getByRole('button', { name: '연결 삭제 확인', exact: true }).click();
  await expect(panel.getByRole('button', { name: `${name} 편집`, exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
 } finally { await cleanup(page, ids); }
});
