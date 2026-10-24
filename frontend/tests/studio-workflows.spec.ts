import { test as base, expect, type Page, type Route, type WebSocketRoute } from '@playwright/test';
import type { ContentItem, ContentProductionSettings, ContentResult, AiTextProviderCatalog, ModelListResponse } from '../src/lib/studio/types';
import type { GenerationJob } from '../src/lib/studio/generation';

const appUrl = process.env.APP_URL ?? 'http://127.0.0.1:5186';
const timestamp = '2026-10-18T14:00:00.000Z';
const languageLabels: Record<string, string> = {
	ko: '한국어', en: '영어', ja: '일본어', zh: '중국어', es: '스페인어', fr: '프랑스어', de: '독일어'
};
const translatedSamples: Record<string, string> = {
	en: 'Welcome to our studio. Today we will introduce a new project.',
	ja: '私たちのスタジオへようこそ。今日は新しい企画をご紹介します。',
	es: 'Te damos la bienvenida a nuestro estudio. Hoy presentamos un nuevo proyecto.',
	zh: '欢迎来到我们的工作室。今天我们将介绍一个新项目。',
	fr: 'Bienvenue dans notre studio. Nous présentons un nouveau projet.',
	de: 'Willkommen in unserem Studio. Heute stellen wir ein neues Projekt vor.'
};

function productionSettings(language: ContentProductionSettings['language'] = 'ko'): ContentProductionSettings {
	return {
		model_id: 'voxcpm', voice_id: null, language, accent: '', tone_prompt: '', style_prompt: '',
		speed: 1, normalize_output: true, quality: 'balanced', pronunciation_rules: []
	};
}

function contentFixture(overrides: Partial<ContentItem> = {}): ContentItem {
	return {
		id: 'content-workflow-test', title: '스튜디오 안내', source_language: 'ko',
		source_text: '안녕하세요. 이번 영상에서는 새롭게 만든 작업실을 소개합니다.',
		translations: {}, results: [], production_settings: productionSettings(),
		created_at: timestamp, updated_at: timestamp, ...overrides
	};
}

function resultFixture(language: 'ko' | 'en' | 'ja', text: string): ContentResult {
	return {
		id: `result-${language}`, language, text, spoken_text: text,
		voice_id: null, voice_name: '테스트 목소리', model_id: 'voxcpm',
		audio_url: `/api/files/outputs/workflow-${language}.wav`, duration_seconds: 3,
		production_settings: productionSettings(language), created_at: timestamp
	};
}

function makeWav(): Buffer {
	// A real, short PCM file exercises browser playback without loading a voice model.
	const sampleRate = 16000;
	const samples = sampleRate * 3;
	const data = Buffer.alloc(44 + samples * 2);
	data.write('RIFF', 0); data.writeUInt32LE(data.length - 8, 4); data.write('WAVE', 8);
	data.write('fmt ', 12); data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20);
	data.writeUInt16LE(1, 22); data.writeUInt32LE(sampleRate, 24); data.writeUInt32LE(sampleRate * 2, 28);
	data.writeUInt16LE(2, 32); data.writeUInt16LE(16, 34); data.write('data', 36); data.writeUInt32LE(samples * 2, 40);
	for (let index = 0; index < samples; index += 1) {
		data.writeInt16LE(Math.round(Math.sin(index * Math.PI * 2 * 220 / sampleRate) * 1800), 44 + index * 2);
	}
	return data;
}

type TranslateRequest = { text: string; languages: string[] };
type EnqueueRequest = {
	languages: string[]; text_overrides: Record<string, string>; model_id: string; batch_id: string;
	voice_id?: string | null; speed?: number;
};
type CapturedEnqueue = { contentId: string; body: EnqueueRequest; savedContent: ContentItem };
type MockStudio = {
	emitJobs: () => void;
	disconnectStream: () => void;
	socketsOpened: number;
	jobReads: number;
	content: ContentItem;
	jobs: GenerationJob[];
	translationError: string;
	translations: TranslateRequest[];
	saves: Array<{ method: string; body: Record<string, unknown> }>;
	enqueues: CapturedEnqueue[];
	exports: Array<{ resultId: string; format: string }>;
	deletedResults: string[];
	deletedContents: string[];
	unexpected: string[];
	pageErrors: string[];
};

const modelCatalog: ModelListResponse = {
	models: [{
		id: 'voxcpm', label: 'VoxCPM2', provider: 'voxcpm', status: 'available', enabled: true,
		loaded: true, device: 'mps', sample_rate: 48000, recommended_for: ['tts', 'voice_clone_tts'],
		capabilities: { tts: true, voice_clone_tts: true, voice_design: false, stt: false, voice_conversion: false }
	}],
	model_preferences: { voxcpm: { id: 'voxcpm', enabled: true, order: 10 } },
	default_tts_model: 'voxcpm', default_vc_model: 'soulx-singer'
};
const providerCatalog: AiTextProviderCatalog = {
	selection: { provider_id: 'apple', model_id: 'system' },
	providers: [{ id: 'apple', label: 'Apple 내장', connection_type: 'local', available: true,
		authenticated: true, message: '브라우저 흐름 테스트용 상태', models: [{ id: 'system', label: 'Apple 내장 모델' }] }],
	api_providers: [],
	translation: { mode: 'auto', effective_provider: 'apple', effective_model: 'system',
		message: '브라우저 흐름 테스트용 상태', apple_available: true },
	connections: { local_only: true, translation_mode: 'auto',
		local: { base_url: '', model_id: '', has_api_key: false },
		nvidia: { base_url: '', model_id: '', has_api_key: false },
		compatible: { base_url: '', model_id: '', has_api_key: false } }
};

async function installMockStudio(page: Page): Promise<MockStudio> {
	const state: MockStudio = {
		emitJobs: () => {}, disconnectStream: () => {}, socketsOpened: 0, jobReads: 0,
		content: contentFixture(), jobs: [], translationError: '', translations: [], saves: [],
		enqueues: [], exports: [], deletedResults: [], deletedContents: [], unexpected: [], pageErrors: []
	};
	const streams = new Set<WebSocketRoute>();
	let sequence = 0;
	state.emitJobs = () => { for (const ws of streams) ws.send(JSON.stringify({ type: 'snapshot', sequence: ++sequence, jobs: state.jobs, concurrency: 1 })); };
	state.disconnectStream = () => { for (const ws of streams) ws.close({ code: 1012, reason: 'Synthetic restart' }); streams.clear(); };
	await page.routeWebSocket('**/api/ws/generation-jobs', ws => {
		state.socketsOpened++; streams.add(ws); state.emitJobs();
		ws.onMessage(message => { if (message === 'resync') state.emitJobs(); });
		ws.onClose(() => streams.delete(ws));
	});
	const wav = makeWav();
	let revision = 0;
	let jobNumber = 0;
	const updatedAt = () => new Date(Date.parse(timestamp) + (++revision) * 1000).toISOString();
	const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': 'GET, POST, PATCH, PUT, DELETE, OPTIONS' };
	const json = (route: Route, value: unknown, status = 200) => route.fulfill({ status, headers: cors, json: value });
	page.on('pageerror', (error) => state.pageErrors.push(error.message));

	await page.route('**/*', async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		const path = url.pathname;
		const method = request.method();
		if (!path.startsWith('/api/')) {
			if (url.origin === new URL(appUrl).origin) return route.continue();
			state.unexpected.push(`${method} ${url.href}`);
			return route.abort('blockedbyclient');
		}
		if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
		if (method === 'GET' && path === '/api/health') return json(route, { ok: true, model: { engine: 'voxcpm', loaded: true, device: 'mps' } });
		if (method === 'GET' && path === '/api/models') return json(route, modelCatalog);
		if (method === 'GET' && path === '/api/voices') return json(route, []);
		if (method === 'GET' && path === '/api/ai/providers') return json(route, providerCatalog);
		if (method === 'GET' && path === '/api/studio/preferences') return json(route, {
			preferences: { start_menu: 'tts', source_language: 'ko', stt_provider: 'apple-speech', show_auxiliary_tools: false },
			platform: { is_mac: true, apple_speech_supported: true, apple_speech_message: '브라우저 흐름 테스트용 상태' }, generation_concurrency: 1
		});
		if (method === 'GET' && path === '/api/contents') return json(route, state.deletedContents.includes(state.content.id) ? [] : [state.content]);
		if (method === 'GET' && path === '/api/generation-jobs') {
			state.jobReads++;
			const contentId = url.searchParams.get('content_id');
			return json(route, { jobs: state.jobs.filter((job) => !contentId || job.content_id === contentId), concurrency: 1 });
		}
		if (method === 'POST' && path === '/api/translate') {
			const body = request.postDataJSON() as TranslateRequest;
			state.translations.push(structuredClone(body));
			if (state.translationError) return json(route, { detail: state.translationError }, 503);
			return json(route, { translations: Object.fromEntries(body.languages.map((code) => [code, translatedSamples[code]])) });
		}
		if (method === 'GET' && path.startsWith('/api/files/')) {
			return route.fulfill({ status: 200, headers: { ...cors, 'Content-Type': 'audio/wav', 'Content-Length': String(wav.length) }, body: wav });
		}

		const contentRoute = path.match(/^\/api\/contents\/([^/]+)$/);
		if (contentRoute && contentRoute[1] === state.content.id) {
			if (method === 'GET') return json(route, state.content);
			if (method === 'PATCH') {
				const body = request.postDataJSON() as Partial<ContentItem>;
				state.saves.push({ method, body: structuredClone(body) });
				state.content = { ...state.content, ...body, updated_at: updatedAt() };
				return json(route, state.content);
			}
			if (method === 'DELETE') {
				state.deletedContents.push(state.content.id);
				return json(route, { ok: true });
			}
		}
		if (method === 'POST' && path === '/api/contents') {
			const body = request.postDataJSON() as Partial<ContentItem>;
			state.saves.push({ method, body: structuredClone(body) });
			state.content = contentFixture({ ...body, updated_at: updatedAt() });
			return json(route, state.content);
		}
		const enqueueRoute = path.match(/^\/api\/contents\/([^/]+)\/jobs$/);
		if (method === 'POST' && enqueueRoute) {
			const body = request.postDataJSON() as EnqueueRequest;
			state.enqueues.push({ contentId: enqueueRoute[1], body: structuredClone(body), savedContent: structuredClone(state.content) });
			const jobs: GenerationJob[] = body.languages.map((language) => ({
				id: `job-${++jobNumber}`, batch_id: body.batch_id, content_id: enqueueRoute[1], language,
				status: 'queued', message: '앞선 작업을 기다립니다.', result_ids: [], created_at: timestamp, updated_at: updatedAt()
			}));
			state.jobs.push(...jobs);
			state.emitJobs();
			return json(route, { jobs, concurrency: 1 });
		}
		const exportRoute = path.match(/^\/api\/contents\/([^/]+)\/results\/([^/]+)\/export$/);
		if (method === 'GET' && exportRoute) {
			state.exports.push({ resultId: exportRoute[2], format: url.searchParams.get('format') || '' });
			return route.fulfill({ status: 200, headers: { ...cors, 'Content-Type': 'audio/wav' }, body: wav });
		}
		const resultRoute = path.match(/^\/api\/contents\/([^/]+)\/results\/([^/]+)$/);
		if (method === 'DELETE' && resultRoute) {
			state.deletedResults.push(resultRoute[2]);
			state.content = { ...state.content, results: state.content.results.filter((result) => result.id !== resultRoute[2]), updated_at: updatedAt() };
			return json(route, state.content);
		}
		state.unexpected.push(`${method} ${path}`);
		return json(route, { detail: `Unmocked request: ${method} ${path}` }, 501);
	});
	return state;
}

const test = base.extend<{ studio: MockStudio }>({
	studio: async ({ page }, use) => {
		const studio = await installMockStudio(page);
		await use(studio);
		expect(studio.unexpected, 'Every API/model request must be explicitly mocked').toEqual([]);
		expect(studio.pageErrors, 'The workflow should not throw an uncaught browser error').toEqual([]);
	}
});

async function openSavedContent(page: Page, studio: MockStudio, initial = true) {
	if (initial) await page.goto(appUrl);
	await expect(page.getByRole('heading', { name: '저장한 대본', exact: true })).toBeVisible();
	await page.getByRole('article').filter({ hasText: studio.content.title }).getByRole('button', { name: '편집', exact: true }).click();
	await expect(page.getByRole('textbox', { name: '대본', exact: true })).toHaveValue(studio.content.source_text);
}

async function selectTranslationTargets(page: Page, codes: string[]) {
	const picker = page.locator('#tts-language-picker');
	if (!(await picker.isVisible())) await page.getByRole('button', { name: '언어 추가', exact: true }).click();
	await expect(picker).toBeVisible();
	for (const [code, label] of Object.entries(languageLabels)) {
		const checkbox = picker.getByRole('checkbox', { name: new RegExp(`^${label}(?:\\s|$)`) });
		if (await checkbox.count()) await checkbox.setChecked(codes.includes(code));
	}
	return picker;
}

async function selectGenerationTargets(page: Page, codes: string[]) {
	const group = page.getByRole('group', { name: '함께 만들 언어', exact: true });
	for (const [code, label] of Object.entries(languageLabels)) {
		const checkbox = group.getByRole('checkbox', { name: new RegExp(`^${label}(?:\\s|$)`) });
		if (await checkbox.count() && await checkbox.isEnabled()) await checkbox.setChecked(codes.includes(code));
	}
}

test('source language and manually edited tabs are saved before only the selected languages are queued', async ({ page, studio }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await openSavedContent(page, studio);
	await expect(page.getByLabel('원본 언어', { exact: true })).toHaveValue('ko');
	await page.getByLabel('원본 언어', { exact: true }).selectOption('en');
	const original = 'Hello from our studio. This is the final English original.';
	await page.getByRole('textbox', { name: '대본', exact: true }).fill(original);
	const picker = await selectTranslationTargets(page, ['ja', 'es']);
	await picker.getByRole('button', { name: '직접 입력할 탭 추가', exact: true }).click();
	await page.getByRole('tab', { name: /^일본어/ }).click();
	await page.getByRole('textbox', { name: '일본어 번역본', exact: true }).fill('手直しした日本語の原稿です。');
	await page.getByRole('tab', { name: /^스페인어/ }).click();
	const spanish = 'Este es el texto en español, revisado y listo para grabar.';
	await page.getByRole('textbox', { name: '스페인어 번역본', exact: true }).fill(spanish);
	await selectGenerationTargets(page, ['en', 'es']);
	await page.getByRole('button', { name: '선택한 2개 음성 만들기', exact: true }).click();
	await expect.poll(() => studio.enqueues.length).toBe(1);
	const submission = studio.enqueues[0];
	expect(submission.body.languages).toEqual(['en', 'es']);
	expect(submission.savedContent.source_language).toBe('en');
	expect(submission.savedContent.production_settings?.language).toBe('en');
	expect(submission.savedContent.source_text).toBe(original);
	expect(submission.savedContent.translations.es).toBe(spanish);
	expect(studio.translations).toEqual([]);
	await expect(page.getByRole('list', { name: '언어별 음성 생성 작업' }).getByRole('listitem')).toHaveCount(2);
	const width = await page.evaluate(() => ({ viewport: window.innerWidth, document: document.documentElement.scrollWidth }));
	expect(width.document).toBeLessThanOrEqual(width.viewport + 1);
});

test('automatic translations stay editable in separate tabs and the saved revision is used for generation', async ({ page, studio }) => {
	await openSavedContent(page, studio);
	const picker = await selectTranslationTargets(page, ['en', 'ja']);
	await picker.getByRole('button', { name: '2개 언어 번역하기', exact: true }).click();
	await expect(page.getByRole('tab', { name: '영어', exact: true })).toBeVisible();
	await expect(page.getByRole('tab', { name: '일본어', exact: true })).toBeVisible();
	expect(studio.translations[0]).toEqual({ text: studio.content.source_text, languages: ['en', 'ja'] });
	await page.getByRole('tab', { name: '영어', exact: true }).click();
	const english = 'This English version was reviewed and changed by the author.';
	await page.getByRole('textbox', { name: '영어 번역본', exact: true }).fill(english);
	await page.getByRole('button', { name: '번역본 저장', exact: true }).click();
	await expect.poll(() => studio.content.translations.en).toBe(english);
	const englishTab = page.getByRole('tab', { name: '영어', exact: true });
	await englishTab.focus();
	await englishTab.press('ArrowRight');
	await expect(page.getByRole('tab', { name: '일본어', exact: true })).toHaveAttribute('aria-selected', 'true');
	await expect(page.getByRole('textbox', { name: /번역본$/ })).toHaveCount(1);
	const japanese = '作者が確認して修正した日本語の文章です。';
	await page.getByRole('textbox', { name: '일본어 번역본', exact: true }).fill(japanese);
	await page.getByRole('button', { name: '번역본 저장', exact: true }).click();
	await expect.poll(() => studio.content.translations.ja).toBe(japanese);
	await page.getByRole('tab', { name: '영어', exact: true }).click();
	await expect(page.getByRole('textbox', { name: '영어 번역본', exact: true })).toHaveValue(english);
	await page.getByRole('button', { name: '이 언어 음성 만들기', exact: true }).click();
	await expect.poll(() => studio.enqueues.length).toBe(1);
	expect(studio.enqueues[0].body.languages).toEqual(['en']);
	expect(studio.enqueues[0].savedContent.translations).toEqual({ en: english, ja: japanese });
	await page.getByRole('button', { name: '콘텐츠 목록으로 돌아가기', exact: true }).click();
	await openSavedContent(page, studio, false);
	await page.getByRole('tab', { name: '영어', exact: true }).click();
	await expect(page.getByRole('textbox', { name: '영어 번역본', exact: true })).toHaveValue(english);
});

test('adding languages preserves an existing human translation unless overwrite is explicitly selected', async ({ page, studio }) => {
	const editedEnglish = 'Keep this carefully reviewed English translation.';
	studio.content = contentFixture({ translations: { en: editedEnglish } });
	await openSavedContent(page, studio);
	let picker = await selectTranslationTargets(page, ['en', 'ja']);
	await expect(picker.getByRole('checkbox', { name: '기존 번역본도 다시 번역', exact: true })).not.toBeChecked();
	await picker.getByRole('button', { name: '1개 언어 번역하기', exact: true }).click();
	await expect.poll(() => studio.translations.length).toBe(1);
	expect(studio.translations[0].languages).toEqual(['ja']);
	await page.getByRole('tab', { name: '영어', exact: true }).click();
	await expect(page.getByRole('textbox', { name: '영어 번역본', exact: true })).toHaveValue(editedEnglish);
	picker = await selectTranslationTargets(page, ['en']);
	await picker.getByRole('checkbox', { name: '기존 번역본도 다시 번역', exact: true }).check();
	await picker.getByRole('button', { name: '1개 언어 번역하기', exact: true }).click();
	await expect.poll(() => studio.translations.length).toBe(2);
	expect(studio.translations[1].languages).toEqual(['en']);
	await expect(page.getByRole('textbox', { name: '영어 번역본', exact: true })).toHaveValue(translatedSamples.en);
	await page.getByRole('tab', { name: '일본어', exact: true }).click();
	await expect(page.getByRole('textbox', { name: '일본어 번역본', exact: true })).toHaveValue(translatedSamples.ja);
});

test('a translation failure leaves manual language editing and voice generation usable', async ({ page, studio }) => {
	studio.translationError = '번역 연결이 준비되지 않았습니다.';
	await openSavedContent(page, studio);
	let picker = await selectTranslationTargets(page, ['ja']);
	await picker.getByRole('button', { name: '1개 언어 번역하기', exact: true }).click();
	await expect(page.getByText(/번역 연결이 준비되지 않았습니다/)).toBeVisible();
	picker = await selectTranslationTargets(page, ['ja']);
	await picker.getByRole('button', { name: '직접 입력할 탭 추가', exact: true }).click();
	const manual = '自分で入力した日本語の文章を音声にします。';
	await page.getByRole('textbox', { name: '일본어 번역본', exact: true }).fill(manual);
	await page.getByRole('button', { name: '이 언어 음성 만들기', exact: true }).click();
	await expect.poll(() => studio.enqueues.length).toBe(1);
	expect(studio.enqueues[0].body.languages).toEqual(['ja']);
	expect(studio.enqueues[0].savedContent.translations.ja).toBe(manual);
	await expect(page.getByRole('textbox', { name: '대본', exact: true })).toBeEnabled();
});

test('a generated result can be played and downloaded, then deleted without deleting the script or other results', async ({ page, studio }) => {
	const english = resultFixture('en', translatedSamples.en);
	const japanese = resultFixture('ja', translatedSamples.ja);
	studio.content = contentFixture({ translations: { en: translatedSamples.en, ja: translatedSamples.ja }, results: [english, japanese] });
	const original = studio.content.source_text;
	await openSavedContent(page, studio);
	const result = page.getByRole('article').filter({ has: page.getByText('영어', { exact: true }) });
	await expect(result).toHaveCount(1);
	await expect(result).not.toContainText('voxcpm');
	const audio = result.locator('audio');
	await audio.evaluate(async (element: HTMLAudioElement) => { await element.play(); });
	await expect.poll(() => audio.evaluate((element: HTMLAudioElement) => element.currentTime)).toBeGreaterThan(0.05);
	await audio.evaluate((element: HTMLAudioElement) => element.pause());
	await page.getByLabel('내보내기 형식', { exact: true }).selectOption('wav');
	const downloadPromise = page.waitForEvent('download');
	await result.getByRole('button', { name: 'WAV 다운로드', exact: true }).click();
	const download = await downloadPromise;
	expect(download.suggestedFilename()).toBe(`${studio.content.title}-en.wav`);
	// OS download completion is checked separately by browser-downloads.spec.ts.
	// This workflow verifies the export request, filename, and independent deletion.
	expect(studio.exports).toEqual([{ resultId: english.id, format: 'wav' }]);
	page.once('dialog', (dialog) => dialog.accept());
	await result.getByRole('button', { name: '생성 결과 삭제', exact: true }).click();
	await expect(result).toHaveCount(0);
	await expect(page.getByRole('article').filter({ has: page.getByText('일본어', { exact: true }) })).toHaveCount(1);
	expect(studio.deletedResults).toEqual([english.id]);
	expect(studio.deletedContents).toEqual([]);
	await expect(page.getByRole('textbox', { name: '대본', exact: true })).toHaveValue(original);
});

test('queue state survives moving to another menu and completion refreshes results without discarding new edits', async ({ page, studio }) => {
	await openSavedContent(page, studio);
	await page.getByRole('button', { name: '원본 음성 만들기', exact: true }).click();
	await expect.poll(() => studio.enqueues.length).toBe(1);
	const queue = page.getByRole('list', { name: '언어별 음성 생성 작업' });
	await expect(queue.getByText('대기 중', { exact: true })).toBeVisible();
	const navigation = page.getByRole('navigation', { name: '목소리 클론 작업', exact: true });
	await navigation.getByRole('button', { name: '내 목소리', exact: true }).click();
	await expect(page.getByRole('heading', { name: '원본 작성', exact: true })).toHaveCount(0);
	studio.jobs[0] = { ...studio.jobs[0], status: 'running', message: '음성을 만들고 있습니다.', updated_at: '2026-10-18T14:01:00.000Z' };
	studio.emitJobs();
	await navigation.getByRole('button', { name: '음성 만들기', exact: true }).click();
	await openSavedContent(page, studio, false);
	await expect(queue.getByText('생성 중', { exact: true })).toBeVisible();
	expect(studio.enqueues).toHaveLength(1);
	const newDraft = '작업이 끝나는 동안 다음 버전의 원본을 편집하고 있습니다.';
	await page.getByRole('textbox', { name: '대본', exact: true }).fill(newDraft);
	const finished = resultFixture('ko', studio.content.source_text);
	studio.content = { ...studio.content, results: [finished] };
	studio.jobs[0] = { ...studio.jobs[0], status: 'completed', message: '생성 완료', result_ids: [finished.id], updated_at: '2026-10-18T14:02:00.000Z' };
	studio.emitJobs();
	await expect(queue.getByText('완료', { exact: true })).toBeVisible({ timeout: 10_000 });
	await expect(page.getByRole('article').filter({ has: page.getByText('한국어', { exact: true }) }).locator('audio')).toBeVisible();
	await expect(page.getByRole('textbox', { name: '대본', exact: true })).toHaveValue(newDraft);
	await expect(page.getByText('대본 수정됨 · 이전 생성본', { exact: true })).toBeVisible();
	expect(studio.enqueues).toHaveLength(1);
});

test('idle editor and menu navigation share one stream without recurring job GET requests', async ({ page, studio }) => {
 await openSavedContent(page, studio);
 await expect(page.getByLabel('음성 작업 연결 상태')).toContainText('실시간 연결');
 const reads = studio.jobReads;
 await page.waitForTimeout(4000);
 expect(studio.jobReads).toBe(reads);
 await page.getByRole('button', { name: '콘텐츠 목록으로 돌아가기', exact: true }).click();
 await openSavedContent(page, studio, false);
 const navigation = page.getByRole('navigation', { name: '목소리 클론 작업', exact: true });
 await navigation.getByRole('button', { name: '내 목소리', exact: true }).click();
 await page.waitForTimeout(1800);
 expect(studio.jobReads).toBe(reads);
 expect(studio.socketsOpened).toBe(1);
});

test('completion after stream interruption is reconciled once while another menu is open', async ({ page, studio }) => {
 await openSavedContent(page, studio);
 await page.getByRole('button', { name: '원본 음성 만들기', exact: true }).click();
 await expect.poll(() => studio.enqueues.length).toBe(1);
 const navigation = page.getByRole('navigation', { name: '목소리 클론 작업', exact: true });
 await navigation.getByRole('button', { name: '내 목소리', exact: true }).click();
 studio.jobs[0] = { ...studio.jobs[0], status: 'running', progress: { percent: 42, message: '합성 중', timestamp }, updated_at: '2026-10-18T14:01:00.000Z' };
 studio.emitJobs();
 await expect(page.getByRole('progressbar', { name: '음성 생성 진행률' })).toHaveAttribute('value', '42');
 studio.disconnectStream();
 const result = resultFixture('ko', studio.content.source_text);
 studio.content.results = [result];
 studio.jobs[0] = { ...studio.jobs[0], status: 'completed', result_ids: [result.id], updated_at: '2026-10-18T14:02:00.000Z' };
 await expect(page.getByLabel('음성 작업 완료 알림')).toContainText('생성 완료');
 await expect(page.getByLabel('음성 작업 연결 상태')).toContainText('실시간 연결');
 await page.getByLabel('음성 작업 완료 알림').getByRole('button', { name: '작업 열기', exact: true }).click();
 await expect(page.getByRole('article').filter({ has: page.getByText('한국어', { exact: true }) }).locator('audio')).toBeVisible();
 expect(studio.enqueues.length).toBe(1);
 await page.getByRole('button', { name: '완료 알림 닫기', exact: true }).click();
 studio.emitJobs();
 await expect(page.getByLabel('음성 작업 완료 알림')).toHaveCount(0);
 await page.reload();
 await expect(page.getByLabel('음성 작업 연결 상태')).toContainText('실시간 연결');
 await expect(page.getByLabel('음성 작업 완료 알림')).toHaveCount(0);
});

test('system completion notification requires opt-in and does not repeat on duplicate events', async ({ page, studio }) => {
 await page.setViewportSize({ width: 390, height: 844 });
 await page.addInitScript(() => {
  const scope = window as typeof window & { notificationsForTest: { title: string; body: string }[] };
  scope.notificationsForTest = [];
  class FakeNotification {
   static permission = 'default';
   static async requestPermission() { FakeNotification.permission = 'granted'; return 'granted'; }
   onclick = null; onclose = null;
   constructor(title: string, options: { body: string }) { scope.notificationsForTest.push({ title, body: options.body }); }
   close() {}
  }
  Object.defineProperty(window, 'Notification', { configurable: true, value: FakeNotification });
  Object.defineProperty(document, 'hasFocus', { configurable: true, value: () => false });
 });
 await openSavedContent(page, studio);
 expect(await page.evaluate(() => Notification.permission)).toBe('default');
 await page.getByRole('button', { name: '완료 알림 켜기', exact: true }).click();
 await expect(page.getByRole('button', { name: '완료 알림 끄기', exact: true })).toHaveAttribute('aria-pressed', 'true');
 await page.getByRole('button', { name: '원본 음성 만들기', exact: true }).click();
 await expect.poll(() => studio.jobs.length).toBe(1);
 studio.jobs[0] = { ...studio.jobs[0], status: 'completed', updated_at: '2026-10-18T14:02:00.000Z' };
 studio.emitJobs();
 await expect.poll(() => page.evaluate(() => (window as any).notificationsForTest.length)).toBe(1);
 studio.emitJobs(); await page.waitForTimeout(200);
 const notifications = await page.evaluate(() => (window as any).notificationsForTest);
 expect(notifications).toHaveLength(1);
 expect(JSON.stringify(notifications)).not.toContain(studio.content.source_text);
 expect(JSON.stringify(notifications)).not.toContain(studio.content.title);
 expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
