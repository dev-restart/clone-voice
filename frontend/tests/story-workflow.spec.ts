import { expect, test } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const appUrl = process.env.APP_URL ?? 'http://127.0.0.1:18185/';
const backendUrl = process.env.E2E_API_URL ?? 'http://127.0.0.1:18109';
const storageKey = 'clonevoice.storyStudio.projects.v1';
const pendingKey = 'clonevoice.storyStudio.pending.v1';

test.beforeEach(async ({ page }) => {
	// These legacy story scenarios explicitly enable the optional conversation tool.
	await page.route('**/api/studio/preferences', async (route) => {
		if (route.request().method() !== 'GET') return route.fallback();
		await route.fulfill({ status: 200, contentType: 'application/json', json: {
			preferences: { start_menu: 'home', source_language: 'ko', stt_provider: 'apple-speech', show_auxiliary_tools: true },
			platform: { is_mac: true, apple_speech_supported: true, apple_speech_message: 'UI 회귀 테스트용 상태' },
			generation_concurrency: 1
		} });
	});
});

function draft(title = '저장 복구 확인') {
	const now = new Date().toISOString();
	return { id: randomUUID(), title, created_at: now, updated_at: now, revision: 0, result: null, segments: [
		{ id: randomUUID(), text: '자료에서 확인한 내용을 먼저 설명합니다.', language: 'ko', model_id: 'voxcpm', speed: 1, pause_after_ms: 450, speaker_name: '진행자' },
		{ id: randomUUID(), text: '아직 정해지지 않은 부분도 함께 짚겠습니다.', language: 'ko', model_id: 'voxcpm', speed: 1, pause_after_ms: 500, speaker_name: '게스트' }
	] };
}

async function openStory(page: import('@playwright/test').Page) {
	await page.goto(appUrl);
	await page.getByRole('button', { name: '대화 오디오', exact: true }).first().click();
	await expect(page.getByText('이 컴퓨터에 저장됨', { exact: true })).toBeVisible();
}

test('browser-only projects migrate and reopen after local storage is cleared', async ({ page, request }) => {
	const legacy = draft('브라우저에서 서버로 이관');
	await page.addInitScript(({ key, project }) => { window.localStorage.setItem(key, JSON.stringify([project])); }, { key: storageKey, project: legacy });
	await openStory(page);
	await expect.poll(async () => (await request.get(`${backendUrl}/api/story-studio/projects/${legacy.id}`)).status()).toBe(200);
	await page.getByRole('button', { name: `${legacy.title} 편집` }).click();
	await page.getByLabel('대사 1', { exact: true }).fill('서버에 저장한 새 대사입니다.');
	await expect(page.getByText('이 컴퓨터에 저장됨', { exact: true })).toBeVisible();
	const response = await request.get(`${backendUrl}/api/story-studio/projects/${legacy.id}`);
	expect((await response.json()).segments[0].text).toBe('서버에 저장한 새 대사입니다.');
	await page.evaluate(({ key, pending }) => { window.localStorage.removeItem(key); window.localStorage.removeItem(pending); }, { key: storageKey, pending: pendingKey });
	await page.reload();
	await page.getByRole('button', { name: '대화 오디오', exact: true }).first().click();
	await page.getByRole('button', { name: `${legacy.title} 편집` }).click();
	await expect(page.getByLabel('대사 1', { exact: true })).toHaveValue('서버에 저장한 새 대사입니다.');
});

test('four AI speakers carry casting into the editor and backup', async ({ page }, testInfo) => {
	await page.route('**/api/story-studio/dialogue-draft', async (route) => {
		const input = route.request().postDataJSON();
		expect(input.speaker_c_name).toBe('분석가');
		expect(input.speaker_d_name).toBe('해설자');
		await route.fulfill({ json: {
			title: '네 화자의 출시 점검', summary: '원문 범위의 대담', format: input.format, language: input.language,
			speech_turns: input.speech_turns, include_sfx_cues: false, provider: 'local', model: 'e2e-fixture',
			speakers: { speaker_a: input.speaker_a_name, speaker_b: input.speaker_b_name }, additional_speakers: { C: input.speaker_c_name, D: input.speaker_d_name },
			turns: Array.from({ length: input.speech_turns }, (_, index) => ({ index: index + 1, speaker: ['A', 'B', 'C', 'D'][index % 4], text: `자료에서 확인한 ${index + 1}번째 내용입니다.` }))
		} });
	});
	await openStory(page);
	await page.getByRole('button', { name: 'AI 대화 만들기', exact: true }).click();
	const dialog = page.getByRole('dialog', { name: 'AI 대화 만들기' });
	await expect(dialog.getByRole('radio', { name: '주제만 적기', exact: true })).toBeChecked();
	await expect(dialog.getByLabel('주제 또는 요청', { exact: true })).toBeFocused();
	await dialog.getByLabel('참여 인원').selectOption('4');
	await dialog.getByRole('radio', { name: '자료로 만들기', exact: true }).click();
	await expect(dialog.getByLabel('자료 원문', { exact: true })).toBeVisible();
	await dialog.getByLabel('자료 원문', { exact: true }).fill('출시 일정이 일주일 조정됐고 품질 확인 항목이 추가됐습니다. 담당자를 재배치하고 다음 주에 다시 점검합니다.');
	await expect(dialog.getByLabel('화자 4 목소리')).toBeVisible();
	await expect(dialog.getByRole('button', { name: '편집기로 가져오기' })).toBeInViewport();
	await page.screenshot({ path: testInfo.outputPath('clone-voice-four-speaker-draft.png'), fullPage: true });
	await dialog.getByRole('button', { name: '편집기로 가져오기' }).click();
	for (const name of ['진행자', '게스트', '분석가', '해설자']) await expect(page.getByLabel(`${name} 전체 목소리`, { exact: true })).toBeVisible();
	await expect(page.getByText('이 컴퓨터에 저장됨', { exact: true })).toBeVisible();
	await page.getByText('원문 전체 확인', { exact: true }).click();
	await expect(page.getByText(/담당자를 재배치하고 다음 주/).last()).toBeVisible();
	const downloadEvent = page.waitForEvent('download');
	await page.getByRole('button', { name: '프로젝트 백업', exact: true }).click();
	expect((await downloadEvent).suggestedFilename()).toBe('네 화자의 출시 점검.json');
	await page.screenshot({ path: testInfo.outputPath('clone-voice-dialogue-editor-desktop.png'), fullPage: true });
});

test('failed autosave keeps the draft and explicit retry persists it', async ({ page, request }) => {
	const project = draft('저장 실패 복구');
	await request.put(`${backendUrl}/api/story-studio/projects/${project.id}`, { data: project });
	await openStory(page);
	await page.getByRole('button', { name: `${project.title} 편집` }).click();
	await page.route('**/api/story-studio/projects/*', async (route) => {
		if (route.request().method() === 'PUT') await route.fulfill({ status: 503, json: { detail: 'test storage unavailable' } });
		else await route.continue();
	});
	await page.getByLabel('대사 1', { exact: true }).fill('저장 실패 뒤에도 남아야 하는 대본');
	await expect(page.getByText('서버 저장을 완료하지 못했습니다', { exact: true })).toBeVisible();
	await expect.poll(() => page.evaluate((key) => JSON.parse(window.localStorage.getItem(key) || '[]')[0]?.segments[0].text, pendingKey)).toBe('저장 실패 뒤에도 남아야 하는 대본');
	await page.unroute('**/api/story-studio/projects/*');
	await page.getByRole('button', { name: '저장 다시 시도' }).click();
	await expect(page.getByText('이 컴퓨터에 저장됨', { exact: true })).toBeVisible();
	expect((await (await request.get(`${backendUrl}/api/story-studio/projects/${project.id}`)).json()).segments[0].text).toBe('저장 실패 뒤에도 남아야 하는 대본');
});

test('conflicting edits survive reload as a separate recovered project', async ({ page, request }) => {
	const project = draft('동시 편집 보호');
	const saved = await (await request.put(`${backendUrl}/api/story-studio/projects/${project.id}`, { data: project })).json();
	await openStory(page);
	await page.getByRole('button', { name: `${project.title} 편집` }).click();
	await request.put(`${backendUrl}/api/story-studio/projects/${project.id}`, { data: { ...saved, title: '다른 화면에서 저장한 제목' } });
	await page.getByLabel('대사 1', { exact: true }).fill('충돌한 로컬 편집도 보존해야 합니다.');
	await expect(page.getByText('서버 저장을 완료하지 못했습니다', { exact: true })).toBeVisible();
	await page.reload();
	await page.getByRole('button', { name: '대화 오디오', exact: true }).first().click();
	await expect(page.getByText('이 컴퓨터에 저장됨', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: '동시 편집 보호 (복구본) 편집', exact: true }).click();
	await expect(page.getByLabel('대사 1', { exact: true })).toHaveValue('충돌한 로컬 편집도 보존해야 합니다.');
	const original = await (await request.get(`${backendUrl}/api/story-studio/projects/${project.id}`)).json();
	expect(original.title).toBe('다른 화면에서 저장한 제목');
});

test('four-speaker casting remains accessible on mobile without horizontal overflow', async ({ page }, testInfo) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await openStory(page);
	await page.getByRole('button', { name: 'AI 대화 만들기', exact: true }).click();
	const dialog = page.getByRole('dialog', { name: 'AI 대화 만들기' });
	await expect(dialog.getByRole('radio', { name: '주제만 적기', exact: true })).toBeChecked();
	await expect(dialog.getByLabel('주제 또는 요청', { exact: true })).toBeFocused();
	await dialog.getByLabel('참여 인원').selectOption('4');
	await expect(dialog.getByLabel('화자 4 이름')).toBeVisible();
	await expect(dialog.getByRole('button', { name: '편집기로 가져오기' })).toBeInViewport();
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
	await page.screenshot({ path: testInfo.outputPath('clone-voice-four-speaker-mobile.png'), fullPage: true });
	await page.keyboard.press('Escape');
	await expect(dialog).toBeHidden();
	await expect(page.getByRole('button', { name: 'AI 대화 만들기', exact: true })).toBeFocused();
});

test('an edited script marks the existing take and exports the generated text', async ({ page, request }, testInfo) => {
	const project = draft('생성본과 편집본 구분');
	const outputDir = join(process.env.E2E_STORAGE_DIR!, 'outputs');
	mkdirSync(outputDir, { recursive: true });
	const filename = `${randomUUID()}.wav`;
	const samples = 24000 * 2;
	const wav = Buffer.alloc(44 + samples * 2);
	wav.write('RIFF', 0); wav.writeUInt32LE(36 + samples * 2, 4); wav.write('WAVEfmt ', 8);
	wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
	wav.writeUInt32LE(24000, 24); wav.writeUInt32LE(48000, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34);
	wav.write('data', 36); wav.writeUInt32LE(samples * 2, 40);
	writeFileSync(join(outputDir, filename), wav);
	const result = { title: project.title, audio_url: `/api/files/outputs/${filename}`, duration_seconds: 2,
		created_at: new Date().toISOString(), source_segments: project.segments,
		segments: project.segments.map((segment, index) => ({ ...segment, index: index + 1, voice_name: segment.speaker_name, audio_url: `/api/files/outputs/${filename}`, duration_seconds: 0.5, segment_type: 'speech' })) };
	const saved = await request.put(`${backendUrl}/api/story-studio/projects/${project.id}`, { data: { ...project, result } });
	expect(saved.status()).toBe(200);
	await openStory(page);
	await page.getByRole('button', { name: `${project.title} 편집` }).click();
	await expect(page.getByLabel('대화 오디오 결과', { exact: true })).toBeVisible();
	await page.getByLabel('대사 1', { exact: true }).fill('생성 이후에 수정한 대사입니다.');
	await expect(page.getByText(/현재 재생·다운로드하는 오디오는 이전 생성본/)).toBeVisible();
	await expect(page.getByText('이 컴퓨터에 저장됨', { exact: true })).toBeVisible();
	// Verify the UI's export request and download handoff, then read the same URL with
	// the API client because this browser's CDP body/file reads fail. The GET only
	// exports the stored result; OS saving is checked in browser-downloads.spec.ts.
	const scriptResponseEvent = page.waitForResponse((response) => {
		const url = new URL(response.url());
		return response.request().method() === 'GET'
			&& url.pathname === `/api/story-studio/projects/${project.id}/export`
			&& url.searchParams.get('format') === 'txt';
	});
	const downloadEvent = page.waitForEvent('download');
	await page.getByRole('button', { name: '대본 TXT', exact: true }).click();
	const [scriptResponse, download] = await Promise.all([scriptResponseEvent, downloadEvent]);
	expect(scriptResponse.status()).toBe(200);
	expect(scriptResponse.headers()['content-type']).toMatch(/^text\/plain(?:;|$)/i);
	expect(download.suggestedFilename()).toBe(`${project.title}.txt`);
	const scriptExport = await request.get(scriptResponse.url());
	expect(scriptExport.status()).toBe(200);
	expect(scriptExport.headers()['content-type']).toMatch(/^text\/plain(?:;|$)/i);
	const script = (await scriptExport.body()).toString('utf8');
	for (const segment of project.segments) expect(script).toContain(segment.text);
	expect(script).not.toContain('생성 이후에 수정한 대사입니다.');

	const zipResponseEvent = page.waitForResponse((response) => {
		const url = new URL(response.url());
		return response.request().method() === 'GET'
			&& url.pathname === `/api/story-studio/projects/${project.id}/export`
			&& url.searchParams.get('format') === 'zip';
	});
	const zipEvent = page.waitForEvent('download');
	await page.getByRole('button', { name: '제작 패키지 ZIP', exact: true }).click();
	const [zipResponse, zip] = await Promise.all([zipResponseEvent, zipEvent]);
	expect(zipResponse.status()).toBe(200);
	expect(zip.suggestedFilename()).toBe(`${project.title}.zip`);
	const zipExport = await request.get(zipResponse.url());
	expect(zipExport.status()).toBe(200);
	expect((await zipExport.body()).subarray(0, 2).toString('ascii')).toBe('PK');
	await page.screenshot({ path: testInfo.outputPath('clone-voice-generated-take-editor.png'), fullPage: true });
});
