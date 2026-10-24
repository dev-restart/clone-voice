import { expect, test, type Page, type Route, type Request } from '@playwright/test';

function wav(seconds = 90, frequency = 220) {
	const rate = 16_000;
	const data = Buffer.alloc(44 + rate * seconds * 2);
	data.write('RIFF'); data.writeUInt32LE(data.length - 8, 4); data.write('WAVEfmt ', 8);
	data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22);
	data.writeUInt32LE(rate, 24); data.writeUInt32LE(rate * 2, 28);
	data.writeUInt16LE(2, 32); data.writeUInt16LE(16, 34);
	data.write('data', 36); data.writeUInt32LE(data.length - 44, 40);
	for (let i = 0; i < rate * seconds; i++) data.writeInt16LE(Math.round(Math.sin(2 * Math.PI * frequency * i / rate) * 3500), 44 + i * 2);
	return data;
}

function fixture(start = 20, end = 28) {
	return {
		duration_seconds: 90, engine: 'apple-sound-analysis',
		message: 'Apple 소리 분석으로 말소리·음악·노래 위치를 찾았습니다.', warnings: [],
		regions: [{ start: 0, end: 20, kind: 'silence' }, { start: 20, end: 90, kind: 'speech' }],
		candidates: [{ id: 'sample-1', start, end, label: '말소리 후보 1',
			reasons: ['말소리 분류가 이어짐', '강한 음악·노래 분류가 적음'], speech_fraction: .95 }]
	};
}

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((done) => (resolve = done));
	return { resolve, promise };
}

const startInput = (page: Page) => page.getByRole('spinbutton', { name: '선택 시작 초', exact: true });
const endInput = (page: Page) => page.getByRole('spinbutton', { name: '선택 끝 초', exact: true });
const transcript = (page: Page) => page.getByLabel('샘플 발화 대본', { exact: true });

async function upload(page: Page, name = 'source-a.wav', seconds = 90) {
	await page.getByLabel('파일 선택', { exact: true }).setInputFiles({ name, mimeType: 'audio/wav', buffer: wav(seconds) });
	await expect(page.getByRole('button', { name: '말소리 구간 찾기', exact: true })).toBeEnabled();
}

async function expectRange(page: Page, start: number, end: number) {
	await expect.poll(async () => Number(await startInput(page).inputValue())).toBeCloseTo(start, 2);
	await expect.poll(async () => Number(await endInput(page).inputValue())).toBeCloseTo(end, 2);
}

async function setRange(page: Page, start: number, end: number) {
	await startInput(page).fill(String(start));
	await startInput(page).blur();
	await endInput(page).fill(String(end));
	await endInput(page).blur();
	await expectRange(page, start, end);
}

async function deliver(page: Page, route: Route, json: unknown) {
	const request = route.request();
	const completed = request.failure() ? Promise.resolve() : new Promise<void>((resolve) => {
		const finish = (finished: Request) => {
			if (finished !== request) return;
			page.off('requestfinished', finish); page.off('requestfailed', finish);
			resolve();
		};
		page.on('requestfinished', finish); page.on('requestfailed', finish);
	});
	try { await route.fulfill({ json }); } catch (error) { if (!request.failure()) throw error; }
	await completed;
	await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

test.beforeEach(async ({ page }) => {
	await page.route('**/api/audio/uploads', (route) => route.fulfill({ json: { audio_url: '/api/files/uploads/ui-sample.wav', filename: 'ui-sample.wav' } }));
	await page.goto(process.env.APP_URL!);
	await page.getByRole('button', { name: '목소리 등록', exact: true }).click();
});

test('long waveform, preview, candidate selection and timestamped text stay synchronized', async ({ page }, testInfo) => {
	const errors: string[] = [];
	page.on('pageerror', error => errors.push(error.message));
	await page.route('**/api/audio/sample-analysis', route => route.fulfill({ json: fixture() }));
	await page.route('**/api/audio/sample-transcript', route => {
		const body = route.request().postDataJSON();
		expect(body.start).toBe(9); expect(body.end).toBe(39);
		return route.fulfill({ json: { text: '확인용 문장입니다.', segments: [
			{ start: 20, end: 24, text: '확인용' }, { start: 24.1, end: 29, text: '문장입니다.' }
		] } });
	});
	await upload(page);
	await expectRange(page, 0, 10);
	await expect(page.getByText('보는 구간 0:00.0–0:30.0', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: '말소리 구간 찾기', exact: true }).click();
	await page.getByRole('button', { name: '말소리 후보 1 미리듣기', exact: true }).click();
	await expectRange(page, 0, 10);
	await expect.poll(() => page.locator('audio').evaluate((node: HTMLAudioElement) => node.currentTime)).toBeGreaterThanOrEqual(20);
	await page.getByRole('button', { name: '일시 정지', exact: true }).click();
	await page.getByRole('button', { name: '말소리 후보 1 구간 선택', exact: true }).click();
	await expectRange(page, 20, 28);
	await page.getByRole('button', { name: '주변 30초 받아쓰기', exact: true }).click();
	await page.getByRole('button', { name: '0:20.0 문장 구간 선택', exact: true }).click();
	await expectRange(page, 20, 29);
	await expect(transcript(page)).toHaveValue('확인용 문장입니다.');
	await expect(page.getByRole('button', { name: '목소리 저장', exact: true })).toBeEnabled();
	await setRange(page, 21, 29);
	await expect(page.getByText('선택 구간이 바뀌었습니다.', { exact: false })).toBeVisible();
	await expect(page.getByRole('button', { name: '목소리 저장', exact: true })).toBeDisabled();
	await page.getByRole('button', { name: '현재 구간 대본으로 확인', exact: true }).click();
	await expect(page.getByRole('button', { name: '목소리 저장', exact: true })).toBeEnabled();
	await setRange(page, 20, 20.4);
	await page.getByRole('button', { name: '선택 구간 재생', exact: true }).click();
	await expect.poll(() => page.locator('audio').evaluate((node: HTMLAudioElement) => node.paused)).toBe(true);
	const played = await page.locator('audio').evaluate((node: HTMLAudioElement) => node.currentTime);
	expect(played).toBeGreaterThanOrEqual(20.35); expect(played).toBeLessThan(20.65);
	await page.screenshot({ path: testInfo.outputPath('voice-selection-desktop.png'), fullPage: true });
	expect(errors).toEqual([]);
});

for (const change of ['text', 'range'] as const) {
	test('late selected transcription preserves changed ' + change, async ({ page }) => {
		const pending = deferred<Route>();
		await page.route('**/api/stt', route => { pending.resolve(route); });
		await upload(page);
		await setRange(page, 20, 28);
		await transcript(page).fill('현재 구간의 기존 대본입니다.');
		await page.getByRole('button', { name: '선택 구간 받아쓰기', exact: true }).click();
		const held = await pending.promise;
		if (change === 'text') await transcript(page).fill('사용자가 직접 수정했습니다.');
		else await setRange(page, 40, 48);
		await deliver(page, held, { text: '이전 응답이 덮어쓰면 안 됩니다.' });
		await expect(transcript(page)).toHaveValue(change === 'text' ? '사용자가 직접 수정했습니다.' : '현재 구간의 기존 대본입니다.');
		if (change === 'range') {
			await expectRange(page, 40, 48);
			await expect(page.getByRole('button', { name: '목소리 저장', exact: true })).toBeDisabled();
		}
	});
}

test('a late source A analysis cannot replace source B candidates', async ({ page }) => {
	const pending = deferred<Route>();
	let count = 0;
	await page.route('**/api/audio/sample-analysis', route => {
		if (++count === 1) { pending.resolve(route); return; }
		return route.fulfill({ json: fixture(40, 48) });
	});
	await upload(page);
	await page.getByRole('button', { name: '말소리 구간 찾기', exact: true }).click();
	const heldA = await pending.promise;
	await upload(page, 'source-b.wav');
	await page.getByRole('button', { name: '말소리 구간 찾기', exact: true }).click();
	await expect(page.getByRole('button', { name: '말소리 후보 1 구간 선택', exact: true })).toBeVisible();
	await deliver(page, heldA, fixture());
	await page.getByRole('button', { name: '말소리 후보 1 구간 선택', exact: true }).click();
	await expectRange(page, 40, 48);
});

test('empty recommendations and transcription errors leave manual selection usable', async ({ page }) => {
	await page.route('**/api/audio/sample-analysis', route => route.fulfill({ json: { ...fixture(), candidates: [] } }));
	await page.route('**/api/audio/sample-transcript', route => route.fulfill({ status: 503, json: { detail: '이 Mac에서 받아쓰기를 준비하지 못했습니다.' } }));
	await upload(page);
	await page.getByRole('button', { name: '말소리 구간 찾기', exact: true }).click();
	await expect(page.getByText('추천할 만한 5초 이상의 구간을 찾지 못했습니다.', { exact: false })).toBeVisible();
	await page.getByRole('button', { name: '주변 30초 받아쓰기', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('받아쓰기를 준비하지 못했습니다.');
	await setRange(page, 20, 28);
	await transcript(page).fill('직접 입력한 대본입니다.');
	await expect(page.getByRole('button', { name: '목소리 저장', exact: true })).toBeEnabled();
});

test('link import reuses its server audio and the editor fits a narrow viewport', async ({ page }, testInfo) => {
	let uploadCalls = 0;
	let source = '';
	await page.route('**/api/audio/uploads', route => { uploadCalls++; return route.abort(); });
	await page.route('**/api/audio/media-import', route => {
		expect(route.request().postDataJSON().url).toBe('https://www.youtube.com/watch?v=SAzUYWru-w0');
		return route.fulfill({ json: { platform: 'youtube', title: '화면 검사용 오디오', audio_url: '/api/files/uploads/imported.wav', filename: 'imported.wav', voice_isolated: false } });
	});
	await page.route('**/api/files/uploads/imported.wav', route => route.fulfill({ contentType: 'audio/wav', body: wav(805) }));
	await page.route('**/api/audio/sample-analysis', route => {
		source = route.request().postDataJSON().audio_url;
		return route.fulfill({ json: { ...fixture(120, 128), duration_seconds: 805 } });
	});
	await page.getByRole('tab', { name: 'YouTube·Instagram', exact: true }).click();
	await page.getByLabel('미디어 주소', { exact: true }).fill('https://www.youtube.com/watch?v=SAzUYWru-w0');
	await page.getByRole('button', { name: '주소에서 가져오기', exact: true }).click();
	await expect(page.getByText('전체 13:25', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: '말소리 구간 찾기', exact: true }).click();
	await page.getByRole('button', { name: '말소리 후보 1 구간 선택', exact: true }).click();
	await expectRange(page, 120, 128);
	expect(source).toBe('/api/files/uploads/imported.wav'); expect(uploadCalls).toBe(0);
	await page.setViewportSize({ width: 390, height: 844 });
	await page.getByRole('button', { name: '선택 구간 확대', exact: true }).click();
	await expectRange(page, 120, 128);
	const sizes = await page.evaluate(() => ({ full: document.documentElement.scrollWidth, view: window.innerWidth,
		overflow: [...document.querySelectorAll('body *')].filter((node) => node.getBoundingClientRect().right > innerWidth + 1 && node.getBoundingClientRect().width > 0).slice(0, 20).map((node) => ({ tag: node.tagName, class: node.className, width: node.getBoundingClientRect().width, right: node.getBoundingClientRect().right })) }));
	await page.screenshot({ path: testInfo.outputPath('voice-selection-mobile.png'), fullPage: true });
	expect(sizes.full, JSON.stringify(sizes.overflow)).toBeLessThanOrEqual(sizes.view + 1);
});

test.describe('direct microphone recording', () => {
	test('short recording stays within the file and releasing the editor stops the microphone', async ({ page }) => {
		await page.evaluate(() => {
			// Exercise the real browser MediaRecorder with a synthesized stream;
			// this never opens the user's physical microphone.
			(window as any).__sampleStreams = [];
			(window as any).__sampleAudioContexts = [];
			navigator.mediaDevices.getUserMedia = async () => {
				const context = new AudioContext();
				const oscillator = context.createOscillator();
				const destination = context.createMediaStreamDestination();
				oscillator.connect(destination);
				oscillator.start();
				await context.resume();
				(window as any).__sampleAudioContexts.push(context);
				(window as any).__sampleStreams.push(destination.stream);
				return destination.stream;
			};
		});
		await page.getByRole('tab', { name: '녹음', exact: true }).click();
		await page.getByRole('button', { name: '녹음', exact: true }).click();
		await expect(page.getByText('녹음 중 0:01', { exact: true })).toBeVisible();
		await page.getByRole('button', { name: '녹음 종료', exact: true }).click();
		await expect(page.getByRole('button', { name: '말소리 구간 찾기', exact: true })).toBeEnabled();
		const end = Number(await endInput(page).inputValue());
		expect(end).toBeGreaterThan(.5); expect(end).toBeLessThan(4);
		expect(Number(await startInput(page).inputValue())).toBe(0);
		await expect.poll(() => page.evaluate(() => (window as any).__sampleStreams.every((stream: MediaStream) => stream.getTracks().every(track => track.readyState === 'ended')))).toBe(true);
		await page.getByRole('button', { name: '녹음', exact: true }).click();
		await expect(page.getByRole('button', { name: '녹음 종료', exact: true })).toBeVisible();
		await page.getByRole('button', { name: '목록', exact: true }).click();
		await expect.poll(() => page.evaluate(() => (window as any).__sampleStreams.every((stream: MediaStream) => stream.getTracks().every(track => track.readyState === 'ended')))).toBe(true);
		await page.evaluate(() => Promise.all((window as any).__sampleAudioContexts.map((context: AudioContext) => context.close())));
	});
});
