import { test as base, expect, type APIRequestContext, type Locator, type Page, type Route } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { mkdirSync, unlinkSync, writeFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import type { AudioAssetCatalog, ModelListResponse, SoundEffectResult, VoiceConversionJob } from '../src/lib/studio/types';
import type { SoundProject } from '../src/lib/studio/sound-projects';

const appUrl = process.env.APP_URL ?? 'http://127.0.0.1:5186';
const timestamp = '2026-10-23T03:00:00.000Z';
const coverTitle = '노래 커버 다운로드 점검';
const soundTitle = '짧은 버튼 효과음';

type ExportFixture = {
	path: string;
	filename: string;
	importedPath: string;
	imports: Array<{ url: string; isolate_voice: boolean }>;
	cover: VoiceConversionJob;
	sounds: SoundProject;
	unexpected: string[];
	errors: string[];
};

function sampleWav(): Buffer {
	const rate = 16000;
	const samples = rate / 2;
	const data = Buffer.alloc(44 + samples * 2);
	data.write('RIFF'); data.writeUInt32LE(data.length - 8, 4); data.write('WAVE', 8);
	data.write('fmt ', 12); data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22);
	data.writeUInt32LE(rate, 24); data.writeUInt32LE(rate * 2, 28); data.writeUInt16LE(2, 32);
	data.writeUInt16LE(16, 34); data.write('data', 36); data.writeUInt32LE(samples * 2, 40);
	for (let index = 0; index < samples; index += 1) {
		data.writeInt16LE(Math.round(Math.sin(index * 2 * Math.PI * 220 / rate) * 1800), 44 + index * 2);
	}
	return data;
}

const models: ModelListResponse = {
	models: [{
		id: 'voxcpm', label: 'VoxCPM2', provider: 'voxcpm', status: 'available', enabled: true,
		loaded: true, device: 'cpu', sample_rate: 48000, recommended_for: ['tts', 'voice_clone_tts'],
		capabilities: { tts: true, voice_clone_tts: true, voice_design: false, stt: false, voice_conversion: false }
	}, {
		id: 'soulx-singer', label: 'SoulX Singer', provider: 'soulx-singer', status: 'available', enabled: true,
		loaded: true, device: 'cpu', sample_rate: 44100, recommended_for: ['voice_conversion'],
		capabilities: { tts: false, voice_clone_tts: false, voice_design: false, stt: false, voice_conversion: true }
	}, {
		id: 'stable-audio-sfx', label: 'Stable Audio SFX', provider: 'stable-audio', status: 'available', enabled: true,
		loaded: true, device: 'cpu', sample_rate: 44100, recommended_for: ['sound_effect_generation'],
		capabilities: { tts: false, voice_clone_tts: false, voice_design: false, stt: false, voice_conversion: false, sound_effect_generation: true }
	}],
	model_preferences: {
		voxcpm: { id: 'voxcpm', enabled: true, order: 10 },
		'soulx-singer': { id: 'soulx-singer', enabled: true, order: 20 },
		'stable-audio-sfx': { id: 'stable-audio-sfx', enabled: true, order: 30 }
	}, default_tts_model: 'voxcpm', default_vc_model: 'soulx-singer'
};

// 수정이유: 모델 생성 없이 실제 변환을 검증하도록 목록만 고정하고 PCM 원본과
// /api/files 요청은 테스트 전용 backend를 사용합니다.
const test = base.extend<{ audioExport: ExportFixture }>({
	audioExport: async ({ page }, use) => {
		test.skip(!process.env.E2E_STORAGE_DIR, 'The audio export workflow requires the isolated Playwright storage directory.');
		const filename = `e2e-export-volume50%-${randomUUID()}.wav`;
		const outputDir = join(process.env.E2E_STORAGE_DIR!, 'outputs');
		const filePath = join(outputDir, filename);
		mkdirSync(outputDir, { recursive: true });
		writeFileSync(filePath, sampleWav());
		const uploadDir = join(process.env.E2E_STORAGE_DIR!, 'uploads');
		const importedFilePath = join(uploadDir, filename);
		mkdirSync(uploadDir, { recursive: true });
		writeFileSync(importedFilePath, sampleWav());
		const path = `/api/files/outputs/${filename}`;
		const result: SoundEffectResult = { id: 'export-sound-result', prompt: 'A short wooden button click.', negative_prompt: '',
			audio_url: path, duration_seconds: .5, seed: 42, model_id: 'stable-audio-sfx', created_at: timestamp };
		const state: ExportFixture = {
			path, filename, importedPath: `/api/files/uploads/${filename}`, imports: [],
			cover: { id: 'export-cover-result', model_id: 'soulx-singer', output_audio_url: path, transcript: '완성된 노래 커버입니다.', created_at: timestamp },
			sounds: { id: 'export-sound-project', title: '효과음 다운로드 점검', category: 'game', revision: 1, created_at: timestamp, updated_at: timestamp,
				assets: [{ id: 'export-sound-asset', title: soundTitle, category: 'ui', prompt: result.prompt,
					negative_prompt: '', duration_seconds: .5, auto_duration: false, variations: 1, guidance_scale: 3, seed: 42,
					results: [result], created_at: timestamp, updated_at: timestamp }] },
			unexpected: [], errors: []
		};
		const catalog: AudioAssetCatalog = { registered_voices: [], generated_files: [{
			id: 'export-library-result', kind: 'ai-cover', title: coverTitle, filename, audio_url: path,
			available: true, duration_seconds: .5, size_bytes: sampleWav().length, model_id: 'soulx-singer', created_at: timestamp
		}] };
		const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS' };
		const json = (route: Route, value: unknown) => route.fulfill({ headers: cors, json: value });
		page.on('pageerror', (error) => state.errors.push(error.message));
		await page.routeWebSocket('**/api/ws/generation-jobs', (socket) => {
			socket.send(JSON.stringify({ type: 'snapshot', sequence: 1, jobs: [], concurrency: 1 }));
		});
		await page.route('**/*', async (route) => {
			const request = route.request();
			const url = new URL(request.url());
			const routePath = url.pathname;
			if (!routePath.startsWith('/api/')) {
				if (url.origin === new URL(appUrl).origin) return route.continue();
				state.unexpected.push(`${request.method()} ${url.href}`);
				return route.abort('blockedbyclient');
			}
			if (routePath.startsWith('/api/files/')) return route.continue();
			if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
			if (request.method() === 'POST' && routePath === '/api/audio/media-import') {
				const body = request.postDataJSON();
				state.imports.push(body);
				return json(route, { platform: 'youtube', title: body.isolate_voice ? '주소로 가져온 음성' : '주소로 가져온 음악',
					webpage_url: body.url, duration_seconds: .5, audio_url: state.importedPath, filename, voice_isolated: body.isolate_voice });
			}
			if (request.method() === 'GET') {
				if (routePath === '/api/health') return json(route, { ok: true, model: { engine: 'fixture', loaded: true, device: 'cpu' } });
				if (routePath === '/api/models') return json(route, models);
				if (['/api/voices', '/api/contents'].includes(routePath)) return json(route, []);
				if (routePath === '/api/generation-jobs') return json(route, { jobs: [], concurrency: 1 });
				if (routePath === '/api/assets') return json(route, catalog);
				if (routePath === '/api/voice-conversion/jobs') return json(route, [state.cover]);
				if (routePath === '/api/sound-projects') return json(route, { projects: [state.sounds] });
				if (routePath === `/api/sound-projects/${state.sounds.id}`) return json(route, state.sounds);
				if (routePath === '/api/studio/preferences') return json(route, {
					preferences: { start_menu: 'home', source_language: 'ko', stt_provider: 'apple-speech', show_auxiliary_tools: true },
					platform: { is_mac: true, apple_speech_supported: true, apple_speech_message: '브라우저 회귀 테스트용 상태' }, generation_concurrency: 1
				});
				if (routePath === '/api/ai/providers') return json(route, {
					selection: { provider_id: 'apple', model_id: 'system' }, providers: [], api_providers: [],
					translation: { mode: 'auto', effective_provider: 'apple', effective_model: 'system', message: '', apple_available: true },
					connections: { local_only: true, translation_mode: 'auto', local: { base_url: '', model_id: '', has_api_key: false },
						nvidia: { base_url: '', model_id: '', has_api_key: false }, compatible: { base_url: '', model_id: '', has_api_key: false } }
				});
			}
			state.unexpected.push(`${request.method()} ${routePath}`);
			return route.fulfill({ status: 501, headers: cors, json: { detail: `Unmocked request: ${request.method()} ${routePath}` } });
		});
		try {
			await use(state);
			expect(state.unexpected, 'Every catalog/model request must be explicitly isolated').toEqual([]);
			expect(state.errors, 'No uncaught browser errors').toEqual([]);
		} finally {
			unlinkSync(filePath);
			unlinkSync(importedFilePath);
		}
	}
});

async function openWorkspace(page: Page, menu: string) {
	await page.goto(appUrl);
	await expect(page.getByRole('heading', { name: '작업실 홈', exact: true })).toBeVisible();
	await page.getByRole('button', { name: menu, exact: true }).first().click();
}

async function verifyDownload(page: Page, request: APIRequestContext, picker: Locator, label: string, path: string, filename: string, format: 'mp3' | 'wav') {
	await picker.selectOption(format);
	const responseEvent = page.waitForResponse((response) => {
		const url = new URL(response.url());
		return response.request().method() === 'GET' && decodeURIComponent(url.pathname) === `${path}/export` && url.searchParams.get('format') === format;
	});
	const downloadEvent = page.waitForEvent('download');
	await page.getByRole('button', { name: `${label} ${format.toUpperCase()} 다운로드`, exact: true }).click();
	const [response, download] = await Promise.all([responseEvent, downloadEvent]);
	expect(response.status()).toBe(200);
	expect(response.headers()['content-type']).toMatch(format === 'mp3' ? /^audio\/mpeg(?:;|$)/ : /^audio\/wav(?:;|$)/);
	expect(download.suggestedFilename()).toBe(`${filename}.${format}`);
	expect(download.suggestedFilename()).not.toContain('.wav.');
	// 수정이유: UI가 전달한 파일명과 실제 저장한 bytes를 변환 API 응답과 함께 검증합니다.
	const exported = await request.get(response.url());
	expect(exported.status()).toBe(200);
	expect(exported.headers()['content-type']).toMatch(format === 'mp3' ? /^audio\/mpeg(?:;|$)/ : /^audio\/wav(?:;|$)/);
	const body = await exported.body();
	expect(await download.failure()).toBeNull();
	const savedPath = await download.path();
	expect(savedPath).toBeTruthy();
	expect(await readFile(savedPath!)).toEqual(body);
	expect(body.length).toBeGreaterThan(100);
	if (format === 'wav') {
		expect(body.subarray(0, 4).toString('ascii')).toBe('RIFF');
		expect(body.subarray(8, 12).toString('ascii')).toBe('WAVE');
	} else {
		expect(body.subarray(0, 4).toString('ascii')).not.toBe('RIFF');
		expect(body.subarray(0, 3).toString('ascii') === 'ID3' || (body[0] === 0xff && (body[1] & 0xe0) === 0xe0)).toBe(true);
	}
	return download.suggestedFilename();
}

test('주소로 가져온 음성 전체는 목소리 등록 전에도 MP3와 WAV로 저장할 수 있다', async ({ page, request, audioExport }, testInfo) => {
	await openWorkspace(page, '목소리 클론');
	await page.getByRole('button', { name: '목소리 등록', exact: true }).click();
	await page.getByRole('tab', { name: 'YouTube·Instagram', exact: true }).click();
	const url = 'https://www.youtube.com/watch?v=imported-source';
	await page.getByRole('textbox', { name: '미디어 주소', exact: true }).fill(url);
	await page.getByRole('button', { name: '주소에서 가져오기', exact: true }).click();
	await expect(page.getByRole('button', { name: '말소리 구간 찾기', exact: true })).toBeEnabled();
	expect(audioExport.imports).toEqual([{ url, isolate_voice: true }]);
	const label = '가져온 음성 전체';
	const picker = page.getByRole('combobox', { name: `${label} 다운로드 형식`, exact: true });
	await expect(picker).toHaveValue('mp3');
	await verifyDownload(page, request, picker, label, audioExport.importedPath, '주소로 가져온 음성 · 말소리 정리 적용', 'mp3');
	await verifyDownload(page, request, picker, label, audioExport.importedPath, '주소로 가져온 음성 · 말소리 정리 적용', 'wav');
	await page.setViewportSize({ width: 390, height: 844 });
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
	await page.screenshot({ path: testInfo.outputPath('imported-voice-download-mobile.png'), fullPage: true });
});

test('주소로 가져온 음악 원곡은 변환 전과 프로젝트 재열기 후에도 MP3와 WAV로 저장할 수 있다', async ({ page, request, audioExport }, testInfo) => {
	await openWorkspace(page, '노래 커버');
	await page.getByRole('button', { name: '새 노래 커버', exact: true }).click();
	const url = 'https://www.youtube.com/watch?v=imported-music';
	await page.getByRole('textbox', { name: '원곡 미디어 주소', exact: true }).fill(url);
	await page.getByRole('button', { name: '주소에서 가져오기', exact: true }).click();
	await expect(page.locator('.cover-source-summary').getByText('주소로 가져온 음악', { exact: true })).toBeVisible();
	expect(audioExport.imports).toEqual([{ url, isolate_voice: false }]);
	const label = '가져온 원곡 전체';
	const picker = page.getByRole('combobox', { name: `${label} 다운로드 형식`, exact: true });
	await expect(picker).toHaveValue('mp3');
	await verifyDownload(page, request, picker, label, audioExport.importedPath, '주소로 가져온 음악', 'mp3');
	await page.reload();
	await expect(page.getByRole('heading', { name: '작업실 홈', exact: true })).toBeVisible();
	await page.getByRole('button', { name: '노래 커버', exact: true }).first().click();
	await page.getByRole('article').filter({ hasText: '주소로 가져온 음악' }).getByRole('button', { name: '편집', exact: true }).click();
	await expect(picker).toHaveValue('mp3');
	await verifyDownload(page, request, picker, label, audioExport.importedPath, '주소로 가져온 음악', 'wav');
	await page.screenshot({ path: testInfo.outputPath('imported-music-download.png'), fullPage: true });
});

test('파일 보관함은 기본 MP3와 선택한 WAV를 실제 형식으로 내려받는다', async ({ page, request, audioExport }, testInfo) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await openWorkspace(page, '파일 보관함');
	await expect(page.getByText(coverTitle, { exact: true })).toBeVisible();
	const label = `${coverTitle} 생성 결과`;
	const picker = page.getByLabel(`${label} 다운로드 형식`, { exact: true });
	await expect(picker).toHaveValue('mp3');
	const filename = audioExport.filename.replace(/\.wav$/, '');
	const mp3Name = await verifyDownload(page, request, picker, label, audioExport.path, filename, 'mp3');
	const wavName = await verifyDownload(page, request, picker, label, audioExport.path, filename, 'wav');
	expect(mp3Name.replace(/\.mp3$/, '')).toBe(wavName.replace(/\.wav$/, ''));
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
	await page.screenshot({ path: testInfo.outputPath('audio-export-library-mobile.png'), fullPage: true });
});

test('저장한 노래 커버 버전은 MP3와 WAV 다운로드를 제공한다', async ({ page, request, audioExport }) => {
	await page.addInitScript(({ title, version, timestamp }) => {
		localStorage.setItem('clonevoice.voiceChanger.projects.v1', JSON.stringify([{
			id: 'export-cover-project', title, voice_id: '', model_id: 'soulx-singer',
			versions: [version], created_at: timestamp, updated_at: timestamp
		}]));
	}, { title: coverTitle, version: audioExport.cover, timestamp });
	await openWorkspace(page, '노래 커버');
	await page.getByRole('article').filter({ hasText: coverTitle }).getByRole('button', { name: '편집', exact: true }).click();
	await expect(page.getByRole('heading', { name: '완성된 버전', exact: true })).toBeVisible();
	const modelPicker = page.getByRole('combobox', { name: '커버 모델', exact: true });
	await expect(modelPicker).toBeVisible();
	await expect(modelPicker).toContainText('SoulX');
	const label = 'v1 변환 결과';
	const picker = page.getByLabel(`${label} 다운로드 형식`, { exact: true });
	await expect(picker).toHaveValue('mp3');
	const filename = `cover-v1-${audioExport.cover.id.slice(0, 8)}`;
	await verifyDownload(page, request, picker, label, audioExport.path, filename, 'mp3');
	await verifyDownload(page, request, picker, label, audioExport.path, filename, 'wav');
});

test('효과음 생성 결과는 MP3와 WAV를 선택하고 다운로드 실패 뒤 재시도할 수 있다', async ({ page, request, audioExport }) => {
	await openWorkspace(page, '사운드 만들기');
	await page.locator('.project-card').filter({ hasText: audioExport.sounds.title }).click();
	const label = `${soundTitle} 버전 1`;
	const picker = page.getByLabel(`${label} 다운로드 형식`, { exact: true });
	await expect(picker).toHaveValue('mp3');
	const failedExport = (url: URL) => decodeURIComponent(url.pathname) === `${audioExport.path}/export` && url.searchParams.get('format') === 'mp3';
	await page.route(failedExport, (route) => route.fulfill({ status: 503, json: { detail: '다운로드 변환을 잠시 사용할 수 없습니다.' }, headers: { 'Access-Control-Allow-Origin': '*' } }));
	await page.getByRole('button', { name: `${label} MP3 다운로드`, exact: true }).click();
	await expect(page.getByRole('alert').filter({ hasText: '다운로드 변환을 잠시 사용할 수 없습니다.' })).toBeVisible();
	await expect(page.getByRole('button', { name: `${label} MP3 다운로드`, exact: true })).toBeEnabled();
	await page.unroute(failedExport);
	const filename = `${soundTitle}-${audioExport.sounds.assets[0].results[0].id.slice(0, 8)}`;
	await verifyDownload(page, request, picker, label, audioExport.path, filename, 'mp3');
	await expect(page.getByRole('alert').filter({ hasText: '다운로드 변환을 잠시 사용할 수 없습니다.' })).toHaveCount(0);
	await verifyDownload(page, request, picker, label, audioExport.path, filename, 'wav');
});

test('생성 품질 도움말은 키보드와 클릭으로 열고 닫으며 모바일 화면 안에 표시된다', async ({ page, audioExport }, testInfo) => {
	void audioExport;
	await page.setViewportSize({ width: 390, height: 844 });
	await openWorkspace(page, '목소리 클론');
	await page.getByRole('button', { name: '새 대본', exact: true }).first().click();
	const help = page.getByRole('button', { name: '생성 품질 도움말', exact: true });
	await help.scrollIntoViewIfNeeded();
	const popover = page.getByRole('note', { name: '생성 품질 설명', exact: true });
	await expect(popover).toHaveCount(0);
	await help.focus();
	await page.keyboard.press('Enter');
	await expect(popover).toHaveText('일반 제작에 적합합니다.');
	await expect(help).toHaveAttribute('aria-expanded', 'true');
	expect(await help.getAttribute('aria-controls')).toBe(await popover.getAttribute('id'));
	await page.keyboard.press('Escape');
	await expect(popover).toHaveCount(0);
	await expect(help).toBeFocused();
	await expect(help).toHaveAttribute('aria-expanded', 'false');
	await help.click();
	await expect(popover).toBeVisible();
	const bounds = await popover.boundingBox();
	expect(bounds).not.toBeNull();
	expect(bounds!.x).toBeGreaterThanOrEqual(0);
	expect(bounds!.y).toBeGreaterThanOrEqual(0);
	expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
	expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(844);
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
	await page.screenshot({ path: testInfo.outputPath('audio-export-help-mobile.png'), fullPage: true });
	await help.click();
	await expect(popover).toHaveCount(0);
});

test('대본에 포커스가 있어도 hover로 열린 도움말을 Escape로 닫을 수 있다', async ({ page, audioExport }) => {
	void audioExport;
	await openWorkspace(page, '목소리 클론');
	await page.getByRole('button', { name: '새 대본', exact: true }).first().click();
	const script = page.getByRole('textbox', { name: '대본', exact: true });
	const help = page.getByRole('button', { name: '생성 품질 도움말', exact: true });
	await script.focus();
	await help.hover();
	await expect(page.getByRole('note', { name: '생성 품질 설명', exact: true })).toBeVisible();
	await expect(script).toBeFocused();
	await page.keyboard.press('Escape');
	await expect(page.getByRole('note', { name: '생성 품질 설명', exact: true })).toHaveCount(0);
	await expect(help).toHaveAttribute('aria-expanded', 'false');
	await expect(script).toBeFocused();
});

test('포인터가 버튼과 도움말 사이 여백을 지나 패널에 머물러도 도움말은 유지된다', async ({ page, audioExport }) => {
	void audioExport;
	await openWorkspace(page, '목소리 클론');
	await page.getByRole('button', { name: '새 대본', exact: true }).first().click();
	const script = page.getByRole('textbox', { name: '대본', exact: true });
	const help = page.getByRole('button', { name: '생성 품질 도움말', exact: true });
	await script.focus();
	await help.hover();
	const tooltip = page.getByRole('note', { name: '생성 품질 설명', exact: true });
	await expect(tooltip).toBeVisible();
	const triggerBounds = await help.boundingBox();
	const panelBounds = await tooltip.boundingBox();
	expect(triggerBounds).not.toBeNull();
	expect(panelBounds).not.toBeNull();
	const x = Math.max(triggerBounds!.x, panelBounds!.x) + Math.min(triggerBounds!.width, panelBounds!.width) / 2;
	const gapY = panelBounds!.y > triggerBounds!.y
		? (triggerBounds!.y + triggerBounds!.height + panelBounds!.y) / 2
		: (panelBounds!.y + panelBounds!.height + triggerBounds!.y) / 2;
	await page.mouse.move(x, gapY);
	await expect(tooltip).toBeVisible();
	await page.mouse.move(panelBounds!.x + panelBounds!.width / 2, panelBounds!.y + panelBounds!.height / 2);
	// 수정이유: 버튼 이탈 지연보다 오래 패널 위에 머물러도 설명을 읽을 수 있어야 합니다.
	await page.waitForTimeout(300);
	await expect(tooltip).toBeVisible();
	await expect(script).toBeFocused();
});
