import { expect, test, type Page, type Route } from '@playwright/test';

const appUrl = process.env.APP_URL ?? 'http://127.0.0.1:5186/';
type SttProvider = 'apple-speech' | 'whisper';
type TranscriptRequest = { path: string; provider: string; language: string };

const mediaUrl = 'https://www.youtube.com/watch?v=stt-fixture';
const audioPath = '/api/files/uploads/stt-preference-fixture.wav';
const filename = 'stt-preference-fixture.wav';
const storyTranscript = '자료 영상에서 받아쓴 문장을 대화 초안의 원문으로 사용합니다.';
const coverTranscript = '가사 인식 요청에서 받아온 테스트 가사입니다.';

function pcmFixture() {
	// Two seconds of valid PCM audio allow the cover waveform to decode normally.
	const sampleRate = 16000;
	const samples = sampleRate * 2;
	const wav = Buffer.alloc(44 + samples * 2);
	wav.write('RIFF', 0); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
	wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
	wav.writeUInt32LE(sampleRate, 24); wav.writeUInt32LE(sampleRate * 2, 28);
	wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34);
	wav.write('data', 36); wav.writeUInt32LE(samples * 2, 40);
	return wav;
}

const modelCatalog = {
	models: [
		{
			id: 'voxcpm', label: 'VoxCPM2', provider: 'voxcpm', status: 'available',
			enabled: true, loaded: true, device: 'mps', sample_rate: 48000,
			recommended_for: ['tts', 'voice_clone_tts'],
			capabilities: { tts: true, voice_clone_tts: true, voice_design: false, stt: false, voice_conversion: false, sound_effect_generation: false }
		},
		{
			id: 'soulx-singer', label: 'SoulX-Singer', provider: 'soulx-singer', status: 'available',
			enabled: true, loaded: false, device: 'mps', sample_rate: 44100,
			recommended_for: ['voice_conversion'],
			capabilities: { tts: false, voice_clone_tts: false, voice_design: false, stt: false, voice_conversion: true, sound_effect_generation: false }
		}
	],
	model_preferences: { voxcpm: { id: 'voxcpm', enabled: true, order: 10 }, 'soulx-singer': { id: 'soulx-singer', enabled: true, order: 20 } },
	default_tts_model: 'voxcpm', default_vc_model: 'soulx-singer'
};

async function mockTranscriptionWorkflows(page: Page, provider: SttProvider) {
	const state = {
		transcripts: [] as TranscriptRequest[],
		mediaImports: [] as Array<{ url: string; isolate_voice: boolean }>,
		unexpected: [] as string[],
		pageErrors: [] as string[]
	};
	const wav = pcmFixture();
	const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS' };
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
		if (method === 'GET' && path === '/api/studio/preferences') return json(route, {
			preferences: { start_menu: 'home', source_language: 'ko', stt_provider: provider, show_auxiliary_tools: true },
			platform: { is_mac: true, apple_speech_supported: true, apple_speech_message: 'UI 설정 전달 테스트용 상태' },
			generation_concurrency: 1
		});
		if (method === 'GET' && path === '/api/models') return json(route, modelCatalog);
		if (method === 'GET' && path === '/api/health') return json(route, { ok: true, model: { engine: 'voxcpm', loaded: true, device: 'mps' } });
		if (method === 'GET' && ['/api/voices', '/api/contents', '/api/story-studio/projects', '/api/voice-conversion/jobs'].includes(path)) return json(route, []);
		if (method === 'GET' && path === '/api/generation-jobs') return json(route, { jobs: [], concurrency: 1 });
		if (method === 'GET' && path === '/api/ai/providers') return json(route, {
			selection: { provider_id: 'apple', model_id: 'system' },
			providers: [{ id: 'apple', label: 'Apple 내장', connection_type: 'local', available: true, authenticated: true,
				message: 'UI 테스트용 상태', models: [{ id: 'system', label: 'Apple 내장 모델' }] }],
			api_providers: [],
			translation: { mode: 'auto', effective_provider: 'apple', effective_model: 'system', message: 'UI 테스트용 상태', apple_available: true },
			connections: { local_only: true, translation_mode: 'auto',
				local: { base_url: '', model_id: '', has_api_key: false },
				nvidia: { base_url: '', model_id: '', has_api_key: false },
				compatible: { base_url: '', model_id: '', has_api_key: false } }
		});
		if (method === 'POST' && path === '/api/audio/media-import') {
			state.mediaImports.push(request.postDataJSON());
			return json(route, { platform: 'youtube', title: '전사 설정 확인용 원곡', webpage_url: mediaUrl,
				duration_seconds: 2, audio_url: audioPath, filename, voice_isolated: false });
		}
		if (method === 'GET' && path === audioPath) {
			return route.fulfill({ status: 200, headers: { ...cors, 'Content-Type': 'audio/wav', 'Content-Length': String(wav.length) }, body: wav });
		}
		if (method === 'POST' && ['/api/stt', '/api/audio/transcript-segments'].includes(path)) {
			// Inspect the real browser FormData fields, without invoking either STT engine.
			const body = request.postDataBuffer()?.toString('utf8') ?? '';
			state.transcripts.push({
				path,
				provider: body.match(/name="provider"\r?\n\r?\n([^\r\n]+)/)?.[1] ?? '',
				language: body.match(/name="language"\r?\n\r?\n([^\r\n]+)/)?.[1] ?? ''
			});
			return json(route, { text: path === '/api/stt' ? storyTranscript : coverTranscript, language: 'ko', segments: [] });
		}
		state.unexpected.push(`${method} ${path}`);
		return json(route, { detail: `Unexpected request in STT preference test: ${method} ${path}` }, 501);
	});
	return state;
}

for (const provider of ['apple-speech', 'whisper'] as const) {
	test(`${provider}: saved STT preference reaches story media and cover lyrics`, async ({ page }) => {
		const state = await mockTranscriptionWorkflows(page, provider);
		await page.goto(appUrl);
		await page.getByRole('button', { name: '대화 오디오', exact: true }).first().click();
		await page.getByRole('button', { name: 'AI 대화 만들기', exact: true }).click();
		const dialog = page.getByRole('dialog', { name: 'AI 대화 만들기', exact: true });
		await dialog.getByRole('radio', { name: '자료로 만들기', exact: true }).click();
		await expect(dialog.getByLabel('자료 원문', { exact: true })).toBeVisible();
		await dialog.getByLabel('자료 미디어 주소', { exact: true }).fill(mediaUrl);
		await dialog.getByRole('button', { name: '영상에서 원문 가져오기', exact: true }).click();
		await expect(dialog.getByLabel('자료 원문', { exact: true })).toHaveValue(storyTranscript);
		expect(state.transcripts).toEqual([{ path: '/api/stt', provider, language: 'ko' }]);
		await dialog.getByRole('button', { name: '취소', exact: true }).click();

		await page.getByRole('button', { name: '노래 커버', exact: true }).first().click();
		await page.getByRole('button', { name: /새 노래 커버/ }).first().click();
		await page.locator('summary').filter({ hasText: /^가사 인식$/ }).click();
		// The wrapping label also contains the option text, so match its visible prefix.
		const lyricEngine = page.getByRole('combobox', { name: /^인식 방식/ });
		await expect(lyricEngine).toHaveValue(provider);
		await page.getByLabel('원곡 미디어 주소', { exact: true }).fill(mediaUrl);
		await page.getByRole('button', { name: '주소에서 가져오기', exact: true }).click();
		await expect(page.getByLabel('파형 시간 눈금', { exact: true })).toBeVisible();
		await page.getByRole('button', { name: '가사 인식', exact: true }).click();
		const lyricPreview = page.locator('.result-preview').filter({ has: page.getByRole('heading', { name: '가사 텍스트', exact: true }) });
		await expect(lyricPreview.getByRole('textbox')).toHaveValue(coverTranscript);
		expect(state.transcripts[1]).toEqual({ path: '/api/audio/transcript-segments', provider, language: 'ko' });

		// A user's in-screen choice still overrides the saved default for this cover.
		const override = provider === 'apple-speech' ? 'whisper' : 'apple-speech';
		await lyricEngine.selectOption(override);
		await page.getByLabel('노래 커버 제목', { exact: true }).fill('가사 전사 방식 선택 확인');
		await expect(lyricEngine).toHaveValue(override);
		const transcriptRequest = page.waitForResponse((response) => response.request().method() === 'POST'
			&& new URL(response.url()).pathname === '/api/audio/transcript-segments');
		await page.getByRole('button', { name: '가사 인식', exact: true }).click();
		expect((await transcriptRequest).status()).toBe(200);
		await expect(page.getByRole('button', { name: '가사 인식', exact: true })).toBeEnabled();
		expect(state.transcripts).toHaveLength(3);
		expect(state.transcripts[2]).toEqual({ path: '/api/audio/transcript-segments', provider: override, language: 'ko' });
		expect(state.mediaImports).toEqual([{ url: mediaUrl, isolate_voice: true }, { url: mediaUrl, isolate_voice: false }]);
		expect(state.unexpected).toEqual([]);
		expect(state.pageErrors).toEqual([]);
	});
}
