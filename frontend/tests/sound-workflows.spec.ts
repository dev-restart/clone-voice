import { test as base, expect, type Page, type Route } from '@playwright/test';
import type { ModelListResponse, SoundEffectResult } from '../src/lib/studio/types';
import type { SoundAsset, SoundProject } from '../src/lib/studio/sound-projects';

// UI/state regression only. API responses and synthesis are mocked; playback
// uses a valid two-second PCM WAV, without loading any actual sound model.
const appUrl = process.env.APP_URL ?? 'http://127.0.0.1:5186';
const timestamp = '2026-10-18T14:00:00.000Z';
type GenerateBody = Pick<SoundAsset, 'prompt' | 'negative_prompt' | 'duration_seconds' | 'auto_duration' | 'variations' | 'guidance_scale' | 'seed'> & { project_id: string; asset_id: string; steps: number };
type MockSounds = {
  projects: SoundProject[]; ready: boolean; puts: SoundProject[];
  generations: Array<{ body: GenerateBody; savedProject: SoundProject }>;
  unexpected: string[]; errors: string[];
};

function wavFile(): Buffer {
  const sampleRate = 16000, samples = sampleRate * 2;
  const data = Buffer.alloc(44 + samples * 2);
  data.write('RIFF'); data.writeUInt32LE(data.length - 8, 4); data.write('WAVE', 8);
  data.write('fmt ', 12); data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22);
  data.writeUInt32LE(sampleRate, 24); data.writeUInt32LE(sampleRate * 2, 28); data.writeUInt16LE(2, 32);
  data.writeUInt16LE(16, 34); data.write('data', 36); data.writeUInt32LE(samples * 2, 40);
  for (let index = 0; index < samples; index += 1) data.writeInt16LE(Math.round(Math.sin(index * 2 * Math.PI * 220 / sampleRate) * 1600), 44 + index * 2);
  return data;
}

function initialProject(): SoundProject {
  return { id: 'sound-workflow-project', title: '버튼 효과음 프로젝트', category: 'game', revision: 1, created_at: timestamp, updated_at: timestamp,
    assets: [{ id: 'click-asset', title: '버튼 클릭', category: 'ui', prompt: 'A warm wooden button click.', negative_prompt: 'speech, music',
      duration_seconds: 2, auto_duration: false, variations: 2, guidance_scale: 3, seed: 400, results: [], created_at: timestamp, updated_at: timestamp }] };
}

function modelCatalog(ready: boolean): ModelListResponse {
  return { models: [{ id: 'stable-audio-sfx', label: 'Stable Audio SFX', provider: 'stable-audio', status: ready ? 'available' : 'unavailable', enabled: true,
    loaded: ready, device: 'mps', sample_rate: 44100, recommended_for: ['sound_effect_generation'],
    capabilities: { tts: false, voice_clone_tts: false, voice_design: false, stt: false, voice_conversion: false, sound_effect_generation: true },
    message: ready ? '브라우저 회귀 테스트용 상태' : '테스트에서 사운드 모델을 준비하지 않은 상태입니다.' }],
    model_preferences: { 'stable-audio-sfx': { id: 'stable-audio-sfx', enabled: true, order: 30 } }, default_tts_model: 'voxcpm', default_vc_model: 'soulx-singer' };
}

async function installMock(page: Page): Promise<MockSounds> {
  const state: MockSounds = { projects: [], ready: true, puts: [], generations: [], unexpected: [], errors: [] };
  const wav = wavFile(); let serial = 0; let resultNumber = 0;
  const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS' };
  const json = (route: Route, value: unknown, status = 200) => route.fulfill({ status, headers: cors, json: value });
  const updatedAt = () => new Date(Date.parse(timestamp) + (++serial) * 1000).toISOString();
  page.on('pageerror', (error) => state.errors.push(error.message));
  await page.route('**/*', async (route) => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
    if (!path.startsWith('/api/')) {
      if (url.origin === new URL(appUrl).origin) return route.continue();
      state.unexpected.push(`${method} ${url.href}`); return route.abort('blockedbyclient');
    }
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    if (method === 'GET' && path === '/api/health') return json(route, { ok: true, model: { engine: 'stable-audio-sfx', loaded: state.ready, device: 'mps' } });
    if (method === 'GET' && path === '/api/models') return json(route, modelCatalog(state.ready));
    if (method === 'GET' && ['/api/voices', '/api/contents'].includes(path)) return json(route, []);
    if (method === 'GET' && path === '/api/generation-jobs') return json(route, { jobs: [], concurrency: 1 });
    if (method === 'GET' && path === '/api/studio/preferences') return json(route, { preferences: { start_menu: 'sfx', source_language: 'ko', stt_provider: 'apple-speech', show_auxiliary_tools: false },
      platform: { is_mac: true, apple_speech_supported: true, apple_speech_message: '브라우저 회귀 테스트용 상태' }, generation_concurrency: 1 });
    if (method === 'GET' && path === '/api/ai/providers') return json(route, { selection: { provider_id: 'apple', model_id: 'system' }, providers: [], api_providers: [],
      translation: { mode: 'auto', effective_provider: 'apple', effective_model: 'system', message: '브라우저 회귀 테스트용 상태', apple_available: true },
      connections: { local_only: true, translation_mode: 'auto', local: { base_url: '', model_id: '', has_api_key: false }, nvidia: { base_url: '', model_id: '', has_api_key: false }, compatible: { base_url: '', model_id: '', has_api_key: false } } });
    if (method === 'GET' && path.startsWith('/api/files/outputs/')) return route.fulfill({ status: 200, headers: { ...cors, 'Content-Type': 'audio/wav', 'Content-Length': String(wav.length) }, body: wav });
    if (method === 'GET' && path === '/api/sound-projects') return json(route, { projects: state.projects });

    const projectRoute = path.match(/^\/api\/sound-projects\/([^/]+)$/);
    if (projectRoute) {
      const existing = state.projects.find((project) => project.id === projectRoute[1]);
      if (method === 'GET') return existing ? json(route, existing) : json(route, { detail: '프로젝트가 없습니다.' }, 404);
      if (method === 'PUT') {
        const body = request.postDataJSON() as SoundProject;
        if ((existing?.revision ?? 0) !== body.revision) return json(route, { detail: '프로젝트가 변경되었습니다.' }, 409);
        state.puts.push(structuredClone(body));
        const saved = { ...body, revision: body.revision + 1, created_at: existing?.created_at ?? timestamp, updated_at: updatedAt() };
        state.projects = [saved, ...state.projects.filter((project) => project.id !== saved.id)];
        return json(route, saved);
      }
    }
    if (method === 'POST' && path === '/api/sound-effects/generate') {
      const body = request.postDataJSON() as GenerateBody;
      const current = state.projects.find((project) => project.id === body.project_id);
      const asset = current?.assets.find((item) => item.id === body.asset_id);
      if (!current || !asset) return json(route, { detail: '사운드가 없습니다.' }, 404);
      state.generations.push({ body: structuredClone(body), savedProject: structuredClone(current) });
      const results: SoundEffectResult[] = Array.from({ length: body.variations }, (_, index) => {
        const id = `result-${++resultNumber}`;
        return { id, prompt: body.prompt, generation_prompt: `Planned: ${body.prompt}`, negative_prompt: body.negative_prompt,
          audio_url: `/api/files/outputs/${id}.wav`, duration_seconds: 2, seed: (body.seed ?? 100) + index, model_id: 'stable-audio-sfx', created_at: updatedAt() };
      });
      const project = { ...current, revision: current.revision + 1, updated_at: updatedAt(), assets: current.assets.map((item) => item.id === asset.id ? { ...item, results: [...item.results, ...results] } : item) };
      state.projects = [project, ...state.projects.filter((item) => item.id !== project.id)];
      return json(route, { results, project, storage_warning: null, plan: { source_prompt: body.prompt, generation_prompt: `Planned: ${body.prompt}`, duration_seconds: 2, duration_mode: 'manual', translated: false, planner: 'direct' } });
    }
    state.unexpected.push(`${method} ${path}`); return json(route, { detail: `Unmocked request: ${method} ${path}` }, 501);
  });
  return state;
}

const test = base.extend<{ sounds: MockSounds }>({ sounds: async ({ page }, use) => {
  const state = await installMock(page); await use(state);
  expect(state.unexpected, 'Every API/model request must be mocked').toEqual([]);
  expect(state.errors, 'No uncaught browser errors').toEqual([]);
} });

async function openWorkspace(page: Page) {
  await page.goto(appUrl);
  await expect(page.getByRole('heading', { name: '내 사운드 프로젝트', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '새로고침', exact: true }).last()).toBeEnabled();
}
async function openProject(page: Page, title: string) {
  await page.locator('.project-card').filter({ hasText: title }).click();
  await expect(page.getByLabel('프로젝트 이름', { exact: true })).toHaveValue(title);
}
function editor(page: Page) { return page.getByRole('region', { name: '사운드 편집', exact: true }); }
function versions(page: Page) { return page.getByRole('region', { name: '선택한 사운드 생성 결과', exact: true }); }

test('starter project prompts can be selected, edited, saved and reopened', async ({ page, sounds }) => {
  await openWorkspace(page);
  const pack = page.getByRole('article').filter({ has: page.getByRole('heading', { name: '게임 UI', exact: true }) });
  await pack.getByRole('button', { name: '이 예제로 프로젝트 만들기', exact: true }).click();
  await expect(page.getByLabel('프로젝트 이름', { exact: true })).toHaveValue('게임 UI 프로젝트');
  await expect.poll(() => sounds.projects[0]?.assets.length).toBe(4);
  expect(sounds.projects[0].assets.every((asset) => asset.results.length === 0)).toBe(true);
  const list = page.getByRole('complementary', { name: '프로젝트의 사운드', exact: true });
  await list.getByRole('button', { name: /동전 획득/ }).click();
  const prompt = 'A bright single coin ping with a short sparkling tail, no voice or music.';
  await editor(page).getByRole('textbox', { name: '사운드 프롬프트', exact: true }).fill(prompt);
  await page.getByRole('button', { name: '프로젝트 저장', exact: true }).click();
  await expect.poll(() => sounds.projects[0]?.assets.find((asset) => asset.title === '동전 획득')?.prompt).toBe(prompt);
  await page.getByRole('button', { name: '사운드 프로젝트', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await openProject(page, '게임 UI 프로젝트');
  await expect(page.getByLabel('프로젝트 이름', { exact: true })).toBeFocused();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await list.getByRole('button', { name: /동전 획득/ }).click();
  await expect(editor(page).getByRole('textbox', { name: '사운드 프롬프트', exact: true })).toHaveValue(prompt);
  await expect(versions(page).locator('audio')).toHaveCount(0);
  expect(sounds.generations).toEqual([]);
});

test('multiple versions play and download, reuse their settings, and make an independent similar asset', async ({ page, sounds }) => {
  sounds.projects = [initialProject()];
  await openWorkspace(page); await openProject(page, sounds.projects[0].title);
  const prompt = 'A clear, dry metallic button click with a very short decay.';
  await editor(page).getByRole('textbox', { name: '사운드 프롬프트', exact: true }).fill(prompt);
  await editor(page).getByRole('button', { name: '사운드 만들기', exact: true }).click();
  const cards = versions(page).getByRole('article');
  await expect(cards).toHaveCount(2);
  expect(sounds.generations).toHaveLength(1);
  expect(sounds.generations[0].savedProject.assets[0].prompt).toBe(prompt);
  expect(sounds.generations[0].body.variations).toBe(2);
  const latest = cards.first(); const audio = latest.locator('audio');
  await audio.evaluate(async (element: HTMLAudioElement) => { await element.play(); });
  await expect.poll(() => audio.evaluate((element: HTMLAudioElement) => element.currentTime)).toBeGreaterThan(.05);
  await audio.evaluate((element: HTMLAudioElement) => element.pause());
  const format = latest.getByRole('combobox', { name: '버튼 클릭 버전 2 다운로드 형식', exact: true });
  await expect(format).toHaveValue('mp3');
  await format.selectOption('wav');
  const exportResponse = page.waitForResponse(response => response.url().endsWith('/export?format=wav'));
  const pendingDownload = page.waitForEvent('download');
  await latest.getByRole('button', { name: '버튼 클릭 버전 2 WAV 다운로드', exact: true }).click();
  expect((await exportResponse).status()).toBe(200);
  const download = await pendingDownload;
  expect(download.suggestedFilename()).toMatch(/\.wav$/);
  // OS completion is a separate browser capability check; keep this flow focused on the asset actions.

  await editor(page).getByRole('textbox', { name: '사운드 프롬프트', exact: true }).fill('Temporary next draft');
  await editor(page).locator('summary').filter({ hasText: '세부 설정' }).click();
  await editor(page).getByRole('spinbutton', { name: '사운드 시드', exact: true }).fill('999');
  await latest.getByRole('button', { name: '이 설정으로 다시 만들기', exact: true }).click();
  await expect(editor(page).getByRole('textbox', { name: '사운드 프롬프트', exact: true })).toHaveValue(prompt);
  await expect(editor(page).getByRole('spinbutton', { name: '사운드 시드', exact: true })).toHaveValue('401');
  expect(sounds.generations).toHaveLength(1);
  await latest.getByRole('button', { name: '비슷하게 만들기', exact: true }).click();
  await expect(editor(page).getByRole('textbox', { name: '사운드 이름', exact: true })).toHaveValue('버튼 클릭 · 변형');
  await expect(editor(page).getByRole('spinbutton', { name: '사운드 시드', exact: true })).toHaveValue('');
  await expect(versions(page).locator('audio')).toHaveCount(0);
  await page.getByRole('button', { name: '프로젝트 저장', exact: true }).click();
  await expect.poll(() => sounds.projects[0].assets.length).toBe(2);
  expect(sounds.projects[0].assets[0].results).toHaveLength(2);
  expect(sounds.projects[0].assets[1].results).toEqual([]);
  expect(sounds.projects[0].assets[1].seed).toBeNull();
});

test('an unavailable model still allows project and prompt saving without overflow at 390px', async ({ page, sounds }, testInfo) => {
  sounds.ready = false;
  await page.setViewportSize({ width: 390, height: 844 });
  await openWorkspace(page);
  await page.getByRole('textbox', { name: '새 사운드 프로젝트 이름', exact: true }).fill('모델 없이 준비하는 영상 효과음');
  await page.getByRole('button', { name: '프로젝트 만들기', exact: true }).click();
  await page.getByRole('button', { name: '사운드 추가', exact: true }).click();
  await editor(page).getByRole('textbox', { name: '사운드 이름', exact: true }).fill('조용한 화면 전환');
  const prompt = 'A soft airy transition whoosh with a gentle finish, no voice or music.';
  await editor(page).getByRole('textbox', { name: '사운드 프롬프트', exact: true }).fill(prompt);
  await expect(editor(page).getByRole('button', { name: '사운드 만들기', exact: true })).toBeDisabled();
  await expect(editor(page).getByText('사운드 모델 준비 필요', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '프로젝트 저장', exact: true }).click();
  await expect.poll(() => sounds.projects[0]?.assets[0]?.prompt).toBe(prompt);
  expect(sounds.generations).toEqual([]);
  const width = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
  expect(width.document).toBeLessThanOrEqual(width.viewport + 1);
  await page.screenshot({ path: testInfo.outputPath('sound-workspace-mobile.png'), fullPage: true });
});
