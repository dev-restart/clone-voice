import { expect, test, type APIRequestContext } from '@playwright/test';
import { randomUUID } from 'node:crypto';

const appUrl = process.env.APP_URL ?? 'http://127.0.0.1:18185/';
const backendUrl = process.env.E2E_API_URL ?? 'http://127.0.0.1:18109';
let voiceIds: string[] = [];
let contentIds: string[] = [];

test.beforeEach(async ({ page }) => {
	await page.route('**/api/studio/preferences', async (route) => {
		if (route.request().method() !== 'GET') return route.fallback();
		await route.fulfill({ status: 200, contentType: 'application/json', json: {
			preferences: { start_menu: 'home', source_language: 'ko', stt_provider: 'apple-speech', show_auxiliary_tools: true },
			platform: { is_mac: true, apple_speech_supported: true, apple_speech_message: 'UI 회귀 테스트용 상태' },
			generation_concurrency: 1
		} });
	});
	expect(['http://127.0.0.1:8011', 'http://127.0.0.1:8013'], 'Disposable fixtures require a dedicated E2E port.').toContain(backendUrl);
	voiceIds = [];
	contentIds = [];
});

test.afterEach(async ({ request }) => {
	const projects = await (await request.get(`${backendUrl}/api/story-studio/projects`)).json();
	for (const project of projects) {
		if (project.segments.some((segment: { voice_id?: string }) => voiceIds.includes(segment.voice_id ?? ''))) {
			await request.delete(`${backendUrl}/api/story-studio/projects/${project.id}?revision=${project.revision}`);
		}
	}
	for (const id of contentIds) await request.delete(`${backendUrl}/api/contents/${id}`);
	for (const id of voiceIds) await request.delete(`${backendUrl}/api/voices/${id}`);
});

async function registerVoice(request: APIRequestContext, label: string) {
	const wav = Buffer.alloc(44 + 24000 * 2);
	wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
	wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
	wav.writeUInt32LE(24000, 24); wav.writeUInt32LE(48000, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34);
	wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40);
	const response = await request.post(`${backendUrl}/api/voices`, { multipart: {
		name: `${label} ${randomUUID().slice(0, 8)}`, transcript: '기준 샘플의 실제 발화입니다.',
		audio: { name: 'sample.wav', mimeType: 'audio/wav', buffer: wav }
	} });
	expect(response.status()).toBe(201);
	const voice = await response.json();
	voiceIds.push(voice.id);
	return voice;
}

test('a chosen existing voice starts narration and survives reload without changing saved work', async ({ page, request }) => {
	const original = await registerVoice(request, '기존 작업 목소리');
	const preferred = await registerVoice(request, '선택한 목소리');
	const response = await request.post(`${backendUrl}/api/contents`, { data: {
		title: `목소리 보존 ${randomUUID().slice(0, 8)}`, source_text: '저장해 둔 대본입니다.',
		production_settings: { model_id: 'voxcpm', voice_id: original.id }
	} });
	expect(response.status()).toBe(201);
	const content = await response.json();
	contentIds.push(content.id);
	await page.goto(appUrl);
	await page.getByLabel('새 작업의 기본 목소리').selectOption(preferred.id);
	await page.getByRole('button', { name: '이 목소리로 내레이션', exact: true }).click();
	await expect(page.getByLabel('목소리', { exact: true })).toHaveValue(preferred.id);
	await page.reload();
	await expect(page.getByLabel('새 작업의 기본 목소리')).toHaveValue(preferred.id);
	await page.getByRole('button', { name: content.title, exact: false }).first().click();
	await expect(page.getByLabel('목소리', { exact: true })).toHaveValue(original.id);
	await expect(page.getByLabel('대본', { exact: true })).toHaveValue(content.source_text);
});

test('existing voice casting reaches a new conversation while the guest remains explicit', async ({ page, request }) => {
	const voice = await registerVoice(request, '대담 진행자');
	await page.goto(appUrl);
	await page.getByRole('button', { name: '목소리 클론', exact: true }).first().click();
	await page.getByRole('navigation', { name: '목소리 클론 작업', exact: true }).getByRole('button', { name: '내 목소리', exact: true }).click();
	const selectedVoice = page.getByRole('button', { name: `${voice.name} 목소리 선택`, exact: true });
	await selectedVoice.click();
	await expect(selectedVoice).toHaveAttribute('aria-pressed', 'true');
	await page.locator('.voice-use-bar').getByRole('button', { name: '대담 만들기', exact: true }).click();
	await expect(page.getByLabel('진행자 전체 목소리', { exact: true })).toHaveValue(voice.id);
	await expect(page.getByLabel('게스트 전체 목소리', { exact: true })).toHaveValue('');
	await expect(page.getByText('이 컴퓨터에 저장됨', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'AI 대화 만들기', exact: true }).click();
	await expect(page.getByLabel('화자 1 목소리', { exact: true })).toHaveValue(voice.id);
	await expect(page.getByLabel('화자 2 목소리', { exact: true })).toHaveValue('');
});

test('reference transcript can be corrected in the existing voice library', async ({ page, request }) => {
	const voice = await registerVoice(request, '샘플 대본 수정');
	await page.goto(appUrl);
	await page.getByRole('button', { name: '목소리 클론', exact: true }).first().click();
	await page.getByRole('navigation', { name: '목소리 클론 작업', exact: true }).getByRole('button', { name: '내 목소리', exact: true }).click();
	const card = page.locator('.voice-card').filter({ hasText: voice.name });
	await card.getByRole('button', { name: '목소리 수정', exact: true }).click();
	await card.getByLabel('샘플 대본', { exact: true }).fill('현재 기준 음성에 정확히 대응하는 샘플 대본입니다.');
	await card.getByRole('button', { name: '수정 저장', exact: true }).click();
	await expect(card.getByText('현재 기준 음성에 정확히 대응하는 샘플 대본입니다.', { exact: true })).toBeVisible();
	const saved = await (await request.get(`${backendUrl}/api/voices/${voice.id}`)).json();
	expect(saved.transcript).toBe('현재 기준 음성에 정확히 대응하는 샘플 대본입니다.');
	expect(saved.audio_url).toBe(voice.audio_url);
});

test('local policy gates external API usage and credentials never reappear in the UI', async ({ page, request }) => {
	await request.put(`${backendUrl}/api/ai/providers/connections`, { data: { local_only: true } });
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto(appUrl);
	await page.getByRole('button', { name: '설정', exact: true }).first().click();
	await page.getByRole('tab', { name: 'AI 연결', exact: true }).click();
	const panel = page.locator('.ai-connections');
	await expect(panel.getByLabel('로컬 전용', { exact: true })).toBeChecked();
	await panel.getByRole('button', { name: '연결 추가', exact: true }).click();
	await panel.getByLabel('빠른 설정', { exact: true }).selectOption('nvidia');
	await panel.getByLabel('연결 이름', { exact: true }).fill(`NVIDIA QA ${randomUUID().slice(0,8)}`);
	await panel.getByLabel('키 보관 방식', { exact: true }).selectOption('private_file');
	await panel.getByLabel('API 키', { exact: true }).fill('test-private-ui-key');
	await panel.getByRole('button', { name: '모델 직접 추가', exact: true }).click();
	await panel.getByLabel('1번째 모델 ID', { exact: true }).fill('chosen-test-model');
	const savedResponse = page.waitForResponse(r => r.url() === `${backendUrl}/api/ai/connections` && r.request().method() === 'POST');
	await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
	const saved = (await (await savedResponse).json()).profile;
	await expect(panel.getByLabel('API 키', { exact: true })).toHaveValue('');
	await expect(panel.getByLabel('API 키', { exact: true })).toHaveAttribute('placeholder', /저장된 키 유지/);
	const catalog = await (await request.get(`${backendUrl}/api/ai/providers`)).json();
	expect(JSON.stringify(catalog)).not.toContain('test-private-ui-key');
	const value = JSON.stringify({ provider_id: saved.id, model_id: 'chosen-test-model' });
	await expect(panel.locator('#default-ai option').filter({ hasText: saved.name })).toBeDisabled();
	await panel.getByLabel('로컬 전용', { exact: true }).uncheck();
	await expect(panel.locator('#default-ai option').filter({ hasText: saved.name })).toBeEnabled();
	await panel.getByLabel('기본 AI', { exact: true }).selectOption(value);
	await expect(panel.getByRole('button', { name: '기본 AI 저장', exact: true })).toBeEnabled();
	await panel.getByLabel('로컬 전용', { exact: true }).check();
	await expect(panel.getByLabel('로컬 전용', { exact: true })).toBeChecked();
	await expect(panel.locator('#default-ai option').filter({ hasText: saved.name })).toBeDisabled();
	await request.delete(`${backendUrl}/api/ai/connections/${saved.id}?expected_revision=${saved.revision}`);
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
