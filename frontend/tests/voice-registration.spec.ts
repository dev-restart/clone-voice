import { expect, test } from '@playwright/test';
import { randomUUID } from 'node:crypto';

test('local sample registration retains the entire original and trims only the reference without a CDN', async ({ page, request }) => {
	const backendUrl = process.env.E2E_API_URL;
	expect(['http://127.0.0.1:8011', 'http://127.0.0.1:8013']).toContain(backendUrl);
	const rate = 24000;
	const wav = Buffer.alloc(44 + rate * 12 * 2);
	wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
	wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
	wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34);
	wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40);
	for (let index = 0; index < rate * 12; index++) wav.writeInt16LE(Math.round(Math.sin(2 * Math.PI * 220 * index / rate) * 3000), 44 + index * 2);
	const externalRequests: string[] = [];
	page.on('request', (event) => {
		const url = new URL(event.url());
		if ((url.protocol === 'https:' || url.protocol === 'http:') && !['127.0.0.1', 'localhost'].includes(url.hostname)) externalRequests.push(url.hostname);
	});
	const name = `로컬 원본 보존 ${randomUUID().slice(0, 8)}`;
	let voiceId: string | undefined;
	try {
		await page.goto(process.env.APP_URL!);
		await page.getByRole('button', { name: '목소리 등록', exact: true }).click();
		await page.getByLabel('파일 선택', { exact: true }).setInputFiles({ name: 'full-original.wav', mimeType: 'audio/wav', buffer: wav });
		await expect(page.getByLabel('파형 시간 눈금').getByText('0:12', { exact: true })).toBeVisible();
		await page.getByLabel('목소리 이름', { exact: true }).fill(name);
		await page.getByLabel('샘플 발화 대본', { exact: true }).fill('음질 평가가 아닌 등록 경로 검사입니다.');
		const savedResponse = page.waitForResponse((response) => response.url() === `${backendUrl}/api/voices` && response.request().method() === 'POST');
		await page.getByRole('button', { name: '목소리 저장', exact: true }).click();
		const response = await savedResponse;
		expect(response.status()).toBe(201);
		const voice = await response.json();
		voiceId = voice.id;
		await expect(page.getByRole('button', { name: `${name} 목소리 선택`, exact: true })).toBeVisible();
		const original = await (await request.get(`${backendUrl}${voice.source_audio_url}`)).body();
		const reference = await (await request.get(`${backendUrl}${voice.audio_url}`)).body();
		expect(original.equals(wav)).toBe(true);
		expect(voice.trim_start).toBe(0);
		expect(voice.trim_end).toBe(10);
		const dataChunk = reference.indexOf(Buffer.from('data'));
		expect(dataChunk).toBeGreaterThan(0);
		expect(reference.readUInt32LE(dataChunk + 4)).toBe(rate * 10 * 2);
		expect(externalRequests).toEqual([]);
	} finally {
		if (voiceId) await request.delete(`${backendUrl}/api/voices/${voiceId}`);
	}
});
