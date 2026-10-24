import { test as base, expect, type Page, type Route } from '@playwright/test';
import type { AiTextProviderCatalog, ModelListResponse } from '../src/lib/studio/types';
import type { StudioPreferences } from '../src/lib/studio/preferences';

// UI/request-contract tests only: every API response is fixed or held in memory.
// These tests do not call Apple Intelligence, a speech engine, or any provider.
const appUrl = process.env.APP_URL ?? 'http://127.0.0.1:5186';
const appleFailure = 'Apple 내장 모델이 준비되지 않아 번역을 실행하지 못했습니다.';
type TranslationMode = 'auto' | 'apple' | 'selected';
type PreferencesMock = {
  preferences: StudioPreferences;
  catalog: AiTextProviderCatalog;
  preferencePuts: Record<string, unknown>[];
  connectionPuts: Record<string, unknown>[];
  translationTests: number;
  unexpected: string[];
  errors: string[];
};

function providerFixture(): AiTextProviderCatalog {
  return {
    selection: { provider_id: 'compatible', model_id: 'gemini-fixture' },
    providers: [{ id: 'apple', label: 'Apple 내장', connection_type: 'local', available: false,
      authenticated: false, message: appleFailure, models: [] }],
    api_providers: [{ id: 'compatible', label: 'Gemini 테스트 연결', connection_type: 'api', available: true,
      authenticated: true, message: '고정된 브라우저 테스트용 연결', models: [{ id: 'gemini-fixture', label: 'Gemini 테스트 모델' }] }],
    translation: { mode: 'auto', effective_provider: 'gemini', effective_model: 'gemini-fixture', apple_available: false,
      message: '테스트 상태: Apple 준비가 필요하여 저장된 Gemini 연결을 사용합니다.' },
    connections: { local_only: false, translation_mode: 'auto',
      local: { base_url: 'http://127.0.0.1:11434/v1', model_id: 'local-fixture', has_api_key: false },
      nvidia: { base_url: 'https://nvidia.example.invalid/v1', model_id: 'nvidia-fixture', has_api_key: true },
      compatible: { base_url: 'https://gemini.example.invalid/v1', model_id: 'gemini-fixture', has_api_key: true } }
  };
}

const modelCatalog: ModelListResponse = {
  models: [{ id: 'voxcpm', label: 'VoxCPM2', provider: 'voxcpm', status: 'available', enabled: true,
    loaded: false, device: 'mps', sample_rate: 48000, recommended_for: ['tts', 'voice_clone_tts'],
    capabilities: { tts: true, voice_clone_tts: true, voice_design: false, stt: false, voice_conversion: false } }],
  model_preferences: { voxcpm: { id: 'voxcpm', enabled: true, order: 10 } },
  default_tts_model: 'voxcpm', default_vc_model: 'soulx-singer'
};

async function installMock(page: Page): Promise<PreferencesMock> {
  const state: PreferencesMock = {
    preferences: { start_menu: 'tts', source_language: 'ko', stt_provider: 'apple-speech', show_auxiliary_tools: false },
    catalog: providerFixture(), preferencePuts: [], connectionPuts: [], translationTests: 0, unexpected: [], errors: []
  };
  const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': 'GET, POST, PUT, OPTIONS' };
  const json = (route: Route, value: unknown, status = 200) => route.fulfill({ status, headers: cors, json: value });
  const preferencesResponse = () => ({ preferences: state.preferences, generation_concurrency: 1,
    platform: { is_mac: true, apple_speech_supported: true, apple_speech_message: '브라우저 테스트용 Mac 환경 상태' } });
  page.on('pageerror', (error) => state.errors.push(error.message));
  await page.route('**/*', async (route) => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
    if (!path.startsWith('/api/')) {
      if (url.origin === new URL(appUrl).origin) return route.continue();
      state.unexpected.push(`${method} ${url.href}`); return route.abort('blockedbyclient');
    }
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    if (method === 'GET' && path === '/api/health') return json(route, { ok: true, model: { engine: 'voxcpm', loaded: false, device: 'mps' } });
    if (method === 'GET' && path === '/api/models') return json(route, modelCatalog);
    if (method === 'GET' && ['/api/voices', '/api/contents'].includes(path)) return json(route, []);
    if (method === 'GET' && path === '/api/generation-jobs') return json(route, { jobs: [], concurrency: 1 });
    if (method === 'GET' && path === '/api/sound-projects') return json(route, { projects: [] });
    if (method === 'GET' && path === '/api/studio/preferences') return json(route, preferencesResponse());
    if (method === 'GET' && path === '/api/ai/production/prompts') return json(route, { revision: 0, templates: [
      ['sound_effect', '효과음'], ['music', '음악'], ['song', '노래'], ['cover', '커버']
    ].map(([id, label]) => ({ id, label, description: '설정 화면 검사 기본값', default_prompt: 'QA production prompt', prompt: 'QA production prompt', customized: false })) });
    if (method === 'GET' && path === '/api/ai/providers') return json(route, state.catalog);
    if (method === 'GET' && path === '/api/ai/connections') return json(route, { revision: 0, profiles: [], routing: { translation: null, writing: null, sound_prompt: null }, local_only: state.catalog.connections.local_only });
    if (method === 'PUT' && path === '/api/studio/preferences') {
      const body = request.postDataJSON() as StudioPreferences;
      state.preferencePuts.push(structuredClone(body)); state.preferences = structuredClone(body);
      return json(route, preferencesResponse());
    }
    if (method === 'PUT' && path === '/api/ai/providers/connections') {
      const body = request.postDataJSON() as Record<string, unknown>;
      state.connectionPuts.push(structuredClone(body));
      const mode = body.translation_mode as TranslationMode;
      state.catalog.connections.translation_mode = mode;
      state.catalog.translation = { mode, apple_available: false,
        effective_provider: mode === 'apple' ? 'apple' : 'gemini',
        effective_model: mode === 'apple' ? 'system' : 'gemini-fixture', message: appleFailure };
      return json(route, state.catalog);
    }
    if (method === 'POST' && path === '/api/ai/translation/test') {
      state.translationTests += 1;
      return json(route, { detail: appleFailure }, 503);
    }
    state.unexpected.push(`${method} ${path}`);
    return json(route, { detail: `Unmocked request: ${method} ${path}` }, 501);
  });
  return state;
}

const test = base.extend<{ settings: PreferencesMock }>({ settings: async ({ page }, use) => {
  const state = await installMock(page); await use(state);
  expect(state.unexpected, 'Every API/model request must be explicitly mocked').toEqual([]);
  expect(state.errors, 'No uncaught browser errors').toEqual([]);
} });

async function openSettings(page: Page) {
  await page.getByRole('button', { name: '설정', exact: true }).click();
  const panel = page.getByRole('region', { name: '기본 설정', exact: true });
  await expect(panel.getByRole('combobox', { name: '기본 번역 방식', exact: true })).toBeEnabled();
  return panel;
}

test('core menus and Korean/Apple defaults can be changed and persist after reload', async ({ page, settings }) => {
  await page.goto(appUrl);
  for (const name of ['목소리 클론', '사운드 만들기', '노래 커버']) {
    await expect(page.getByRole('button', { name, exact: true })).toBeVisible();
  }
  for (const name of ['대화 오디오', '받아쓰기']) await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0);
  let panel = await openSettings(page);
  await expect(panel.getByRole('combobox', { name: '시작 메뉴', exact: true })).toHaveValue('tts');
  await expect(panel.getByRole('combobox', { name: '원본 언어', exact: true })).toHaveValue('ko');
  await expect(panel.getByRole('combobox', { name: '받아쓰기 방식', exact: true })).toHaveValue('apple-speech');
  await expect(panel.getByRole('combobox', { name: '기본 번역 방식', exact: true })).toHaveValue('auto');
  await expect(panel.getByRole('switch', { name: /보조 도구 표시/ })).not.toBeChecked();
  await expect(panel.getByText('Mac 환경', { exact: true })).toBeVisible();
  await panel.getByRole('combobox', { name: '시작 메뉴', exact: true }).selectOption('sfx');
  await panel.getByRole('combobox', { name: '원본 언어', exact: true }).selectOption('en');
  await panel.getByRole('combobox', { name: '받아쓰기 방식', exact: true }).selectOption('whisper');
  await panel.getByRole('switch', { name: /보조 도구 표시/ }).check();
  await panel.getByRole('button', { name: '기본 설정 저장', exact: true }).click();
  const saved: StudioPreferences = { start_menu: 'sfx', source_language: 'en', stt_provider: 'whisper', show_auxiliary_tools: true };
  await expect.poll(() => settings.preferencePuts).toEqual([saved]);
  await expect(panel.getByRole('button', { name: '기본 설정 저장', exact: true })).toBeDisabled();
  for (const name of ['대화 오디오', '받아쓰기']) await expect(page.getByRole('button', { name, exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: '내 사운드 프로젝트', exact: true })).toBeVisible();
  panel = await openSettings(page);
  await expect(panel.getByRole('combobox', { name: '시작 메뉴', exact: true })).toHaveValue('sfx');
  await expect(panel.getByRole('combobox', { name: '원본 언어', exact: true })).toHaveValue('en');
  await expect(panel.getByRole('combobox', { name: '받아쓰기 방식', exact: true })).toHaveValue('whisper');
  await expect(panel.getByRole('switch', { name: /보조 도구 표시/ })).toBeChecked();
  expect(settings.connectionPuts).toEqual([]);
});

test('Apple mode changes only translation_mode and shows an unavailable test as a failure', async ({ page, settings }) => {
  const originalConnections = structuredClone(settings.catalog.connections);
  const originalSelection = structuredClone(settings.catalog.selection);
  await page.goto(appUrl);
  const panel = await openSettings(page);
  await expect(panel.getByText('Apple 준비 필요', { exact: true })).toBeVisible();
  await expect(panel.getByText('Gemini', { exact: true })).toBeVisible();
  await panel.getByRole('combobox', { name: '기본 번역 방식', exact: true }).selectOption('apple');
  await expect(panel.getByRole('button', { name: '번역 확인', exact: true })).toBeDisabled();
  await panel.getByRole('button', { name: '번역 방식 저장', exact: true }).click();
  await expect.poll(() => settings.connectionPuts).toEqual([{ translation_mode: 'apple' }]);
  await expect(panel.getByRole('button', { name: '번역 확인', exact: true })).toBeEnabled();
  await expect(panel.getByRole('combobox', { name: '기본 번역 방식', exact: true })).toHaveValue('apple');
  await expect(panel.getByText('Apple 준비 필요', { exact: true })).toBeVisible();
  await panel.getByRole('button', { name: '번역 확인', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText(appleFailure);
  await expect(panel.getByText('번역 확인 완료', { exact: true })).toHaveCount(0);
  expect(settings.translationTests).toBe(1);
  expect(settings.catalog.connections).toEqual({ ...originalConnections, translation_mode: 'apple' });
  expect(settings.catalog.selection).toEqual(originalSelection);
  expect(settings.preferencePuts).toEqual([]);
});
