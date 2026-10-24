import { expect, test as baseTest, type Page, type APIRequestContext } from '@playwright/test';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';

type Kind = 'sound_effect' | 'music' | 'song' | 'cover';
type CoverSettings = { quality: 'fast' | 'balanced' | 'quality'; cfg_scale: number; pitch_shift: number; auto_shift: boolean; separate_vocals: boolean; mix_accompaniment: boolean };
type Output = { generation_prompt: string; lyrics: string; structure: string; advice: string; settings: CoverSettings | null };
type PromptCatalog = { revision: number; templates: Array<{ id: Kind; label: string; prompt: string; default_prompt: string; customized: boolean }> };
type Call = { path: string; authorization: string | undefined; body: { model?: string; messages?: Array<{ role: string; content: string }> } };
type State = { ids: string[]; errors: string[] };
const api = process.env.E2E_API_URL ?? 'http://127.0.0.1:8011';
const appUrl = process.env.APP_URL ?? 'http://127.0.0.1:5186';
const promptPath = '/api/ai/production/prompts';
const assistPath = '/api/ai/production/assist';
const fakeKey = 'test-production-loopback-key';
let upstream: Server;
let upstreamBase = '';
let calls: Call[] = [];
let output: Output;
const defaultOutput = (): Output => ({ generation_prompt: 'Warm acoustic guitar and soft piano, intimate instrumental arrangement.', lyrics: '', structure: 'Intro, A, B, outro', advice: '악기 수와 다이내믹을 간결하게 유지하세요.', settings: null });

baseTest.beforeAll(async () => {
 expect(['http://127.0.0.1:8011', 'http://127.0.0.1:8013']).toContain(api);
 upstream = createServer(async (req, res) => {
  let raw = ''; for await (const chunk of req) raw += chunk;
  const body = raw ? JSON.parse(raw) : {};
  calls.push({ path: req.url ?? '', authorization: req.headers.authorization, body });
  res.setHeader('Content-Type', 'application/json');
  if (req.url?.endsWith('/models')) return res.end(JSON.stringify({ data: [{ id: 'qa-production' }] }));
  res.end(JSON.stringify({ choices: [{ message: { role: 'assistant', content: JSON.stringify(output) }, finish_reason: 'stop' }] }));
 });
 await new Promise<void>(resolve => upstream.listen(0, '127.0.0.1', resolve));
 upstreamBase = 'http://127.0.0.1:' + (upstream.address() as AddressInfo).port + '/v1';
});
baseTest.afterAll(async () => { await new Promise<void>(resolve => upstream.close(() => resolve())); });

async function getPrompts(request: APIRequestContext): Promise<PromptCatalog> {
 const response = await request.get(api + promptPath); expect(response.ok()).toBe(true); return response.json();
}
async function putPrompts(request: APIRequestContext, updates: Partial<Record<Kind, string | null>>) {
 const current = await getPrompts(request);
 const response = await request.put(api + promptPath, { data: { expected_revision: current.revision, updates } });
 expect(response.ok()).toBe(true); return response.json() as Promise<PromptCatalog>;
}

const test = baseTest.extend<{ state: State }>({ state: async ({ page }, use) => {
 const savedPrompts = await getPrompts(page.request);
 const savedConnections = await (await page.request.get(api + '/api/ai/connections')).json();
 const state: State = { ids: [], errors: [] }; calls = []; output = defaultOutput();
 page.on('pageerror', e => state.errors.push(e.message));
 await page.route('**/api/studio/preferences', route => route.request().method() === 'GET' ? route.fulfill({ json: {
  preferences: { start_menu: 'sfx', source_language: 'ko', stt_provider: 'apple-speech', show_auxiliary_tools: true },
  platform: { is_mac: true, apple_speech_supported: true, apple_speech_message: '격리 브라우저 검사' }, generation_concurrency: 1
 } }) : route.fallback());
 try { await use(state); }
 finally {
  const latest = await (await page.request.get(api + '/api/ai/connections')).json();
  const restored = await page.request.put(api + '/api/ai/routing', { data: { expected_revision: latest.revision, ...savedConnections.routing } });
  expect(restored.ok()).toBe(true);
  for (const profile of (await (await page.request.get(api + '/api/ai/connections')).json()).profiles) {
   if (state.ids.includes(profile.id)) expect((await page.request.delete(api + '/api/ai/connections/' + profile.id + '?expected_revision=' + profile.revision)).ok()).toBe(true);
  }
  await putPrompts(page.request, Object.fromEntries(savedPrompts.templates.map(t => [t.id, t.customized ? t.prompt : null])));
  expect(state.errors, 'No uncaught browser errors').toEqual([]);
 }
} });

async function openSettings(page: Page) {
 await page.goto(appUrl);
 await page.getByRole('button', { name: '설정', exact: true }).first().click();
 await page.getByRole('tab', { name: 'AI 연결', exact: true }).click();
 await expect(page.locator('.ai-connections')).toBeVisible();
 const manager = page.getByRole('region', { name: '제작 시스템 프롬프트', exact: true });
 await expect(manager.getByLabel('프롬프트 용도', { exact: true })).toBeEnabled();
 return manager;
}
function assist(page: Page) { return page.getByRole('region', { name: 'AI 제작 도우미', exact: true }); }
async function openSounds(page: Page) {
 await page.goto(appUrl);
 await expect(page.getByRole('heading', { name: '내 사운드 프로젝트', exact: true })).toBeVisible();
 await expect(assist(page)).toBeVisible();
 return assist(page);
}
async function connectProduction(page: Page, state: State) {
 await openSettings(page);
 const panel = page.locator('.ai-connections');
 await panel.getByRole('button', { name: '연결 추가', exact: true }).click();
 await panel.getByLabel('연결 이름', { exact: true }).fill('QA 제작 API ' + Date.now());
 await panel.getByLabel('API 형식', { exact: true }).selectOption('openai_chat');
 await panel.getByLabel('기본 API 주소', { exact: true }).fill(upstreamBase);
 await panel.getByLabel('인증 방식', { exact: true }).selectOption('bearer');
 await panel.getByLabel('키 보관 방식', { exact: true }).selectOption('private_file');
 await panel.getByLabel('API 키', { exact: true }).fill(fakeKey);
 await panel.getByRole('button', { name: '모델 직접 추가', exact: true }).click();
 await panel.getByLabel('1번째 모델 ID', { exact: true }).fill('qa-production');
 const saving = page.waitForResponse(r => r.url() === api + '/api/ai/connections' && r.request().method() === 'POST');
 await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
 const response = await saving; expect(response.status()).toBe(201);
 const profile = (await response.json()).profile; state.ids.push(profile.id);
 await expect(panel.getByLabel('API 키', { exact: true })).toHaveValue('');
 await panel.getByRole('button', { name: '닫기', exact: true }).click();
 await panel.locator('summary').filter({ hasText: '작업별 AI 설정' }).click();
 const route = { provider_id: profile.id, model_id: 'qa-production' };
 await panel.locator('#task-sound_prompt').selectOption(JSON.stringify(route));
 await panel.getByRole('button', { name: '작업별 AI 저장', exact: true }).click();
 await expect(panel.getByRole('button', { name: '작업별 AI 저장', exact: true })).toBeDisabled();
 expect((await (await page.request.get(api + '/api/ai/connections')).json()).routing.sound_prompt).toEqual(route);
 return profile;
}
async function requestAssist(page: Page, kind: Kind, brief: string) {
 const panel = assist(page);
 if (kind !== 'cover') await panel.getByLabel('제작 도움 종류', { exact: true }).selectOption(kind);
 await panel.getByLabel('제작 요청', { exact: true }).fill(brief);
 const pending = page.waitForResponse(r => r.url() === api + assistPath && r.request().method() === 'POST');
 await panel.getByRole('button', { name: 'AI 제작 도움 받기', exact: true }).click();
 return pending;
}

test('system prompts persist after reopening and restore built-in content', async ({ page, state }) => {
 const manager = await openSettings(page);
 await manager.getByLabel('프롬프트 용도', { exact: true }).selectOption('song');
 const original = (await getPrompts(page.request)).templates.find(t => t.id === 'song')!;
 const custom = 'QA 노래 작사 규칙: 짧은 한국어 문장으로 시작하고 후렴은 두 줄로 작성하세요.';
 await manager.getByLabel('시스템 프롬프트', { exact: true }).fill(custom);
 const saving = page.waitForResponse(r => r.url() === api + promptPath && r.request().method() === 'PUT');
 await manager.getByRole('button', { name: '프롬프트 저장', exact: true }).click();
 expect((await saving).ok()).toBe(true);
 await expect(manager.getByRole('status')).toContainText('프롬프트를 저장했습니다.');
 expect((await getPrompts(page.request)).templates.find(t => t.id === 'song')).toMatchObject({ prompt: custom, customized: true });
 await openSettings(page);
 await manager.getByLabel('프롬프트 용도', { exact: true }).selectOption('song');
 await expect(manager.getByLabel('시스템 프롬프트', { exact: true })).toHaveValue(custom);
 const resetting = page.waitForResponse(r => r.url() === api + promptPath && r.request().method() === 'PUT');
 await manager.getByRole('button', { name: '기본값 복원', exact: true }).click();
 expect((await resetting).ok()).toBe(true);
 await expect(manager.getByLabel('시스템 프롬프트', { exact: true })).toHaveValue(original.default_prompt);
 expect((await getPrompts(page.request)).templates.find(t => t.id === 'song')).toMatchObject({ prompt: original.default_prompt, customized: false });
});

test('conflicting revision and failed saves preserve the user draft', async ({ page, state }) => {
 const manager = await openSettings(page);
 await manager.getByLabel('프롬프트 용도', { exact: true }).selectOption('music');
 const draft = 'QA 편집 중인 음악 프롬프트: 리듬을 차분하게 유지하세요.';
 await manager.getByLabel('시스템 프롬프트', { exact: true }).fill(draft);
 await putPrompts(page.request, { cover: 'QA 다른 창에서 변경한 커버 설정 안내입니다.' });
 const conflict = page.waitForResponse(r => r.url() === api + promptPath && r.request().method() === 'PUT');
 await manager.getByRole('button', { name: '프롬프트 저장', exact: true }).click();
 expect((await conflict).status()).toBe(409);
 await expect(manager.getByLabel('시스템 프롬프트', { exact: true })).toHaveValue(draft);
 await manager.getByRole('button', { name: '내 편집 유지하고 최신 버전 반영', exact: true }).click();
 await expect(manager.getByLabel('시스템 프롬프트', { exact: true })).toHaveValue(draft);
 await manager.getByRole('button', { name: '프롬프트 저장', exact: true }).click();
 await expect(manager.getByRole('status')).toContainText('프롬프트를 저장했습니다.');
 const stored = await getPrompts(page.request);
 expect(stored.templates.find(t => t.id === 'music')?.prompt).toBe(draft);
 expect(stored.templates.find(t => t.id === 'cover')?.prompt).toContain('다른 창');
 const unsaved = draft + '\n저장 장애 중에도 보존할 새 문장입니다.';
 await manager.getByLabel('시스템 프롬프트', { exact: true }).fill(unsaved);
 await page.route('**' + promptPath, route => route.request().method() === 'PUT' ? route.fulfill({ status: 503, json: { detail: 'QA 저장 장애' } }) : route.fallback());
 await manager.getByRole('button', { name: '프롬프트 저장', exact: true }).click();
 await expect(manager.getByRole('alert')).toContainText('QA 저장 장애');
 await expect(manager.getByLabel('시스템 프롬프트', { exact: true })).toHaveValue(unsaved);
 expect((await getPrompts(page.request)).templates.find(t => t.id === 'music')?.prompt).toBe(draft);
 await page.unroute('**' + promptPath);
});

test('registered API and task model receive saved music and song system prompts', async ({ page, state }) => {
 await connectProduction(page, state);
 const musicRule = 'QA_MUSIC_SYSTEM: 기승전결 있는 짧은 연주곡을 기획하세요.';
 const songRule = 'QA_SONG_SYSTEM: 자연스러운 한국어 가사와 두 줄 후렴을 만드세요.';
 const catalog = await putPrompts(page.request, { music: musicRule, song: songRule });
 const panel = await openSounds(page);
 let nativeCalls = 0;
 await page.route('**/api/sound-effects/generate', route => { nativeCalls++; return route.fulfill({ status: 503, json: { detail: 'Unexpected audio generation' } }); });
 const musicBrief = '비 오는 오후에 어울리는 잔잔한 피아노 연주곡';
 expect((await requestAssist(page, 'music', musicBrief)).ok()).toBe(true);
 await expect(panel.getByLabel('제작 프롬프트', { exact: true })).toHaveValue(output.generation_prompt);
 await expect(panel.getByLabel('곡 구성', { exact: true })).toHaveValue(output.structure);
 let current = calls.filter(c => c.path === '/v1/chat/completions').at(-1)!;
 expect(current.body.model).toBe('qa-production');
 expect(current.authorization).toBe('Bearer ' + fakeKey);
 expect(current.body.messages?.find(m => m.role === 'system')?.content).toContain(musicRule);
 expect(current.body.messages?.find(m => m.role === 'user')?.content).toContain(musicBrief);
 output = { ...defaultOutput(), lyrics: '[Verse]\n창가에 내려앉은 오후\n[Chorus]\n천천히 걸어가\n함께 걸어가', structure: 'Verse, Chorus, Verse, Chorus' };
 const songResponse = await requestAssist(page, 'song', '위로를 전하는 한국어 노래 초안');
 expect(songResponse.ok()).toBe(true);
 expect(await songResponse.json()).toMatchObject({ kind: 'song', model: 'qa-production', prompt_id: 'song', prompt_revision: catalog.revision });
 await expect(panel.getByLabel('가사 초안', { exact: true })).toHaveValue(output.lyrics);
 await expect(panel.getByLabel('곡 구성', { exact: true })).toHaveValue(output.structure);
 current = calls.filter(c => c.path === '/v1/chat/completions').at(-1)!;
 expect(current.body.messages?.find(m => m.role === 'system')?.content).toContain(songRule);
 expect(calls.filter(c => c.path === '/v1/chat/completions')).toHaveLength(2);
 expect(nativeCalls).toBe(0);
 expect(await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage))).not.toContain(fakeKey);
});

async function mockSoundProject(page: Page) {
 const stamp = '2026-10-20T13:00:00.000Z';
 let project = { id: 'qa-production-prompt-project', title: 'QA 제작 사운드', category: 'game', revision: 1, created_at: stamp, updated_at: stamp,
  assets: [{ id: 'qa-production-asset', title: '버튼 소리', category: 'ui', prompt: 'Original short wooden click.', negative_prompt: 'speech, music', duration_seconds: 2, auto_duration: false, variations: 1, guidance_scale: 3, seed: 123, results: [], created_at: stamp, updated_at: stamp }] };
 let puts = 0, generations = 0;
 await page.route('**/api/sound-projects', route => route.request().method() === 'GET' ? route.fulfill({ json: { projects: [project] } }) : route.fallback());
 await page.route('**/api/sound-projects/' + project.id, async route => {
  if (route.request().method() === 'PUT') { const body = route.request().postDataJSON(); puts++; project = { ...body, revision: body.revision + 1, updated_at: new Date().toISOString() }; }
  await route.fulfill({ json: project });
 });
 await page.route('**/api/sound-effects/generate', route => { generations++; return route.fulfill({ status: 503, json: { detail: 'Audio synthesis is not part of this prompt test' } }); });
 return { project: () => project, puts: () => puts, generations: () => generations };
}
async function openSoundAsset(page: Page) {
 await openSounds(page);
 await page.locator('.project-card').filter({ hasText: 'QA 제작 사운드' }).click();
 const editor = page.getByRole('region', { name: '사운드 편집', exact: true });
 await expect(editor.getByLabel('사운드 프롬프트', { exact: true })).toHaveValue('Original short wooden click.');
 return editor;
}

test('effect advice changes the selected asset only on explicit apply and can be saved', async ({ page, state }) => {
 await connectProduction(page, state);
 const mocked = await mockSoundProject(page);
 const editor = await openSoundAsset(page);
 output = { generation_prompt: 'A dry single wooden click with a gentle short tail, no voice or music.', lyrics: '', structure: '', advice: '한 번의 어택과 짧은 잔향만 사용하세요.', settings: null };
 expect((await requestAssist(page, 'sound_effect', '부드러운 나무 버튼 클릭 소리를 다듬어 주세요.')).ok()).toBe(true);
 await expect(editor.getByLabel('사운드 프롬프트', { exact: true })).toHaveValue('Original short wooden click.');
 expect(mocked.generations()).toBe(0);
 await assist(page).getByRole('button', { name: '사운드 프롬프트에 적용', exact: true }).click();
 await expect(editor.getByLabel('사운드 프롬프트', { exact: true })).toHaveValue(output.generation_prompt);
 await page.getByRole('button', { name: '프로젝트 저장', exact: true }).click();
 await expect.poll(() => mocked.project().assets[0].prompt).toBe(output.generation_prompt);
 expect(mocked.puts()).toBe(1);
 expect(mocked.generations()).toBe(0);
});

function sampleWav() {
 const rate = 24000, samples = rate;
 const wav = Buffer.alloc(44 + samples * 2);
 wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
 wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
 wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34);
 wav.write('data', 36); wav.writeUInt32LE(samples * 2, 40);
 for (let i = 0; i < samples; i++) wav.writeInt16LE(Math.round(Math.sin(i * 2 * Math.PI * 220 / rate) * 1000), 44 + i * 2);
 return wav;
}

test('cover recommendations require apply and reach the next conversion request', async ({ page, state }) => {
 await connectProduction(page, state);
 const stamp = '2026-10-20T13:00:00.000Z', wav = sampleWav();
 const fields: Array<Record<string, string>> = [];
 await page.route('**/api/voices', route => route.fulfill({ json: [{ id: 'qa-cover-voice', name: 'QA 기준 목소리', transcript: '검사용 기준 발화', audio_url: '/api/files/uploads/qa-cover.wav', created_at: stamp, updated_at: stamp }] }));
 await page.route('**/api/voice-conversion/jobs', route => route.fulfill({ json: [] }));
 await page.route('**/api/models', route => route.fulfill({ json: {
  models: [{ id: 'soulx-singer', label: 'SoulX-Singer', provider: 'soulx', status: 'available', enabled: true, loaded: true, device: 'mps', sample_rate: 24000, recommended_for: ['voice_conversion'],
   capabilities: { tts: false, voice_clone_tts: false, voice_design: false, stt: false, voice_conversion: true, sound_effect_generation: false }, message: '합성 없는 UI 검사용 준비 상태' }],
  model_preferences: { 'soulx-singer': { id: 'soulx-singer', enabled: true, order: 20 } }, default_tts_model: 'voxcpm', default_vc_model: 'soulx-singer'
 } }));
 await page.route('**/api/audio/uploads', route => route.fulfill({ json: { audio_url: '/api/files/uploads/qa-cover.wav', filename: 'qa-cover.wav' } }));
 await page.route('**/api/files/uploads/qa-cover.wav', route => route.fulfill({ contentType: 'audio/wav', body: wav }));
 await page.route('**/api/voice-conversion', route => {
  const raw = route.request().postDataBuffer()?.toString('utf8') ?? '';
  fields.push(Object.fromEntries([...raw.matchAll(/name="([^"]+)"\r\n\r\n([^\r\n]*)/g)].map(match => [match[1], match[2]])));
  return route.fulfill({ status: 503, json: { detail: 'QA: 변환 입력 검증 완료, 오디오 추론은 실행하지 않았습니다.' } });
 });
 await page.goto(appUrl);
 await page.getByRole('button', { name: '노래 커버', exact: true }).first().click();
 await page.getByRole('button', { name: /새 노래 커버/ }).first().click();
 const uploaded = page.waitForResponse(r => r.url() === api + '/api/audio/uploads' && r.request().method() === 'POST');
 await page.locator('input[type=file]').first().setInputFiles({ name: 'qa-cover.wav', mimeType: 'audio/wav', buffer: wav });
 expect((await uploaded).ok()).toBe(true);
 await page.getByRole('combobox', { name: /대상 목소리/ }).selectOption('qa-cover-voice');
 const quality = page.locator('[aria-label="노래 커버 생성 품질"]');
 await quality.getByRole('button', { name: '빠름', exact: true }).click();
 await expect(page.getByRole('button', { name: '노래 커버 만들기', exact: true })).toBeEnabled();
 const recommended: CoverSettings = { quality: 'quality', cfg_scale: 3, pitch_shift: 2, auto_shift: false, separate_vocals: true, mix_accompaniment: true };
 output = { generation_prompt: '', lyrics: '', structure: '', advice: '두 반음 올려 음역을 맞추고 분리한 보컬을 고품질로 변환하세요.', settings: recommended };
 const response = await requestAssist(page, 'cover', '밝은 음색으로 바꾸되 반주는 그대로 유지하고 싶습니다.');
 expect(response.ok()).toBe(true);
 expect(response.request().postDataJSON()).toMatchObject({ kind: 'cover', current_settings: { quality: 'fast' } });
 await expect(quality.getByRole('button', { name: '빠름', exact: true })).toHaveClass(/\bactive\b/);
 expect(fields).toEqual([]);
 const savedBeforeApply = await page.evaluate(() => localStorage.getItem('clonevoice.voiceChanger.projects.v1'));
 await page.evaluate(() => {
  const original = Storage.prototype.setItem;
  Storage.prototype.setItem = function(key: string, value: string) {
   if (key === 'clonevoice.voiceChanger.projects.v1') { Storage.prototype.setItem = original; throw new DOMException('QA quota', 'QuotaExceededError'); }
   return original.call(this, key, value);
  };
 });
 await assist(page).getByRole('button', { name: '추천 설정 적용', exact: true }).click();
 await expect(assist(page).getByRole('alert')).toContainText('기존 설정을 유지했습니다');
 await expect(quality.getByRole('button', { name: '빠름', exact: true })).toHaveClass(/\bactive\b/);
 expect(await page.evaluate(() => localStorage.getItem('clonevoice.voiceChanger.projects.v1'))).toBe(savedBeforeApply);
 await assist(page).getByRole('button', { name: '추천 설정 적용', exact: true }).click();
 await expect(quality.getByRole('button', { name: '고품질', exact: true })).toHaveClass(/\bactive\b/);
 expect(fields).toEqual([]);
 const conversion = page.waitForResponse(r => r.url() === api + '/api/voice-conversion' && r.request().method() === 'POST');
 await page.getByRole('button', { name: '노래 커버 만들기', exact: true }).click();
 expect((await conversion).status()).toBe(503);
 expect(fields).toHaveLength(1);
 expect(fields[0]).toMatchObject({ voice_id: 'qa-cover-voice', model_id: 'soulx-singer', conversion_mode: 'singing', steps: '8', cfg_scale: '3', pitch_shift: '2', auto_shift: 'false', separate_vocals: 'true', mix_accompaniment: 'true' });
});

test('a delayed reply cannot overwrite a changed request or asset at 390px', async ({ page, state }, testInfo) => {
 const profile = await connectProduction(page, state);
 const mocked = await mockSoundProject(page);
 await page.setViewportSize({ width: 390, height: 844 });
 const editor = await openSoundAsset(page), panel = assist(page);
 let start!: () => void, release!: () => void;
 const started = new Promise<void>(resolve => { start = resolve; });
 const gate = new Promise<void>(resolve => { release = resolve; });
 await page.route('**' + assistPath, async route => {
  start(); await gate;
  await route.fulfill({ json: { kind: 'sound_effect', ...defaultOutput(), provider: profile.id, model: 'qa-production', prompt_revision: 1, prompt_id: 'sound_effect' } });
 });
 try {
  await panel.getByLabel('제작 도움 종류', { exact: true }).selectOption('sound_effect');
  await panel.getByLabel('제작 요청', { exact: true }).fill('처음 요청한 버튼 소리');
  const response = page.waitForResponse(r => r.url() === api + assistPath && r.request().method() === 'POST');
  await panel.getByRole('button', { name: 'AI 제작 도움 받기', exact: true }).click();
  await started;
  await panel.getByLabel('제작 요청', { exact: true }).fill('응답 대기 중 새로 바꾼 요구사항');
  await editor.getByLabel('사운드 프롬프트', { exact: true }).fill('User edited asset while the request was running.');
  release(); expect((await response).ok()).toBe(true);
  await expect(panel.getByRole('button', { name: 'AI 제작 도움 받기', exact: true })).toBeEnabled();
  await expect(panel.getByLabel('제작 요청', { exact: true })).toHaveValue('응답 대기 중 새로 바꾼 요구사항');
  await expect(editor.getByLabel('사운드 프롬프트', { exact: true })).toHaveValue('User edited asset while the request was running.');
  await expect(panel.locator('button:not(:disabled)').filter({ hasText: '사운드 프롬프트에 적용' })).toHaveCount(0);
  expect(mocked.generations()).toBe(0);
  expect(mocked.puts()).toBe(0);
  const size = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
  expect(size.document).toBeLessThanOrEqual(size.viewport + 1);
  await page.screenshot({ path: testInfo.outputPath('production-assist-mobile.png'), fullPage: true });
 } finally { release(); await page.unroute('**' + assistPath); }
});
