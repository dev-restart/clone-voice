import { expect, test } from '@playwright/test';

const appUrl = process.env.APP_URL ?? 'http://127.0.0.1:18185/';

const catalog = {
	registered_voices: [
		{
			id: 'voice-test',
			kind: 'registered-voice',
			title: '테스트 목소리',
			filename: 'voice-test.wav',
			audio_url: '/api/files/voices/voice-test.wav',
			source_audio_url: '/api/files/uploads/voice-source.wav',
			available: true,
			size_bytes: 24000,
			duration_seconds: 8.4,
			voice_id: 'voice-test',
			voice_name: '테스트 목소리',
			transcript: '기준 음성 대본입니다.',
			trim_start: 1,
			trim_end: 9.4,
			created_at: '2026-08-12T03:00:00Z'
		}
	],
	generated_files: [
		{
			id: 'cover-test',
			kind: 'ai-cover',
			title: '여름 노래 AI 커버',
			filename: 'cover-test.wav',
			audio_url: '/api/files/outputs/cover-test.wav',
			source_audio_url: '/api/files/uploads/source-test.wav',
			available: true,
			size_bytes: 48000,
			duration_seconds: 42,
			voice_id: 'voice-test',
			voice_name: '테스트 목소리',
			model_id: 'soulx-singer',
			source_title: '권리 확인된 원곡',
			created_at: '2026-08-12T04:00:00Z'
		},
		{
			id: 'unknown-test',
			kind: 'other',
			title: '기존 생성 파일',
			filename: 'unknown.wav',
			audio_url: '/api/files/outputs/unknown.wav',
			available: true,
			size_bytes: 12000,
			duration_seconds: 3,
			created_at: '2026-08-11T04:00:00Z'
		}
	]
};

test.beforeEach(async ({ page }) => {
	await page.route('**/api/studio/preferences', async (route) => {
		if (route.request().method() !== 'GET') return route.fallback();
		await route.fulfill({ status: 200, contentType: 'application/json', json: {
			preferences: { start_menu: 'home', source_language: 'ko', stt_provider: 'apple-speech', show_auxiliary_tools: true },
			platform: { is_mac: true, apple_speech_supported: true, apple_speech_message: 'UI 회귀 테스트용 상태' },
			generation_concurrency: 1
		} });
	});
	await page.route('**/api/assets', async (route) => {
		await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(catalog) });
	});
});

test('파일 보관함에서 등록 목소리와 생성 결과를 식별하고 다운로드할 수 있다', async ({ page }, testInfo) => {
	await page.goto(appUrl);
	await page.waitForLoadState('networkidle');
	await expect(page.getByRole('heading', { name: '작업실 홈', exact: true })).toBeVisible();
	await page.getByRole('button', { name: '파일 보관함', exact: true }).first().click();

	await expect(page.getByRole('heading', { name: '파일 보관함', exact: true }).first()).toBeVisible();
	await expect(page.getByRole('heading', { name: '보관된 파일', exact: true })).toBeVisible();
	await expect(page.getByText('테스트 목소리', { exact: true }).first()).toBeVisible();
	await expect(page.getByRole('link', { name: '테스트 목소리 기준 음성 다운로드' })).toHaveAttribute('href', /download=true/);
	await expect(page.getByRole('link', { name: '테스트 목소리 등록 원본 다운로드' })).toHaveAttribute('href', /download=true/);

	const filters = page.getByLabel('파일 종류 필터');
	await filters.getByRole('button', { name: '노래 커버', exact: true }).click();
	await expect(page.getByText('여름 노래 AI 커버', { exact: true })).toBeVisible();
	await expect(page.getByText(/원곡 · 권리 확인된 원곡/)).toBeVisible();
	await expect(page.getByText('테스트 목소리', { exact: true }).first()).toBeVisible();
	await expect(page.getByText('테스트 목소리 기준 음성과 비교', { exact: true })).toBeVisible();
	const format = page.getByRole('combobox', { name: '여름 노래 AI 커버 생성 결과 다운로드 형식', exact: true });
	await expect(format).toHaveValue('mp3');
	await expect(page.getByRole('button', { name: '여름 노래 AI 커버 생성 결과 MP3 다운로드', exact: true })).toBeEnabled();
	await format.selectOption('wav');
	await expect(page.getByRole('button', { name: '여름 노래 AI 커버 생성 결과 WAV 다운로드', exact: true })).toBeEnabled();
	await expect(page.getByRole('link', { name: '여름 노래 AI 커버 원본 오디오 다운로드' })).toHaveAttribute('href', /download=true/);
	await page.screenshot({ path: testInfo.outputPath('clone-voice-files.png'), fullPage: true });

	await filters.getByRole('button', { name: '기타 파일', exact: true }).click();
	await expect(page.getByText('기존 생성 파일', { exact: true })).toBeVisible();
	await expect(page.getByText('여름 노래 AI 커버', { exact: true })).toHaveCount(0);

	await page.getByLabel('파일 보관함 검색').fill('찾을 수 없는 파일');
	await expect(page.getByText('표시할 파일이 없습니다.', { exact: true })).toBeVisible();
});

test('파일 보관함은 mobile에서 가로로 넘치지 않는다', async ({ page }, testInfo) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto(appUrl);
	await page.waitForLoadState('networkidle');
	await expect(page.getByRole('heading', { name: '작업실 홈', exact: true })).toBeVisible();
	await page.getByRole('button', { name: '파일 보관함', exact: true }).first().click();
	await page.getByLabel('파일 종류 필터').getByRole('button', { name: '노래 커버', exact: true }).click();
	await expect(page.getByText('여름 노래 AI 커버', { exact: true })).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
	await page.screenshot({ path: testInfo.outputPath('clone-voice-files-mobile.png') });
});
