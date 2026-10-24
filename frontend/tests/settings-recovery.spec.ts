import { expect, test } from '@playwright/test';
import { readFile, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

test.beforeEach(async ({ page }) => {
	await page.route('**/api/studio/preferences', async (route) => {
		if (route.request().method() !== 'GET') return route.fallback();
		await route.fulfill({ status: 200, contentType: 'application/json', json: {
			preferences: { start_menu: 'home', source_language: 'ko', stt_provider: 'apple-speech', show_auxiliary_tools: true },
			platform: { is_mac: true, apple_speech_supported: true, apple_speech_message: 'UI 회귀 테스트용 상태' },
			generation_concurrency: 1
		} });
	});
});

test('damaged local AI settings remain editable without revealing embedded credentials', async ({ page }) => {
	expect(['http://127.0.0.1:8011', 'http://127.0.0.1:8013']).toContain(process.env.E2E_API_URL);
	const storage = process.env.E2E_STORAGE_DIR;
	expect(storage).toBeTruthy();
	const paths = ['ai_text_settings.json', 'ai_text_connections.json', 'ai_api_profiles.json'].map((name) => join(storage!, name));
	const original = await Promise.all(paths.map((path) => readFile(path).catch((error: NodeJS.ErrnoException) => {
		if (error.code === 'ENOENT') return null;
		throw error;
	})));
	try {
		await writeFile(paths[0], '[]', { mode: 0o600 });
		await writeFile(paths[1], JSON.stringify({ local: { base_url: 'https://fixture:private@localhost/v1' } }), { mode: 0o600 });
		await page.goto(process.env.APP_URL!);
		await page.getByRole('button', { name: '설정', exact: true }).first().click();
		await page.getByRole('tab', { name: 'AI 연결', exact: true }).click();
		const panel = page.locator('.ai-connections');
		await expect(panel.getByLabel('로컬 전용', { exact: true })).toBeChecked();
		await expect(panel).not.toContainText('fixture:private');
		await panel.getByRole('button', { name: '연결 추가', exact: true }).click();
		await panel.getByLabel('빠른 설정', { exact: true }).selectOption('ollama');
		await panel.getByLabel('연결 이름', { exact: true }).fill('잘못된 이전 주소의 대체 연결');
		const responsePromise = page.waitForResponse(r => r.url().endsWith('/api/ai/connections') && r.request().method() === 'POST');
		await panel.getByRole('button', { name: '연결 저장', exact: true }).click();
		expect((await responsePromise).status()).toBe(201);
		await expect(panel.getByLabel('기본 API 주소', { exact: true })).toHaveValue('http://127.0.0.1:11434/v1');
		await expect(panel.getByRole('button', { name: '잘못된 이전 주소의 대체 연결 편집', exact: true })).toBeVisible();
		await expect(panel).not.toContainText('fixture:private');
	} finally {
		for (let index = 0; index < paths.length; index++) {
			if (original[index] === null) await unlink(paths[index]).catch((error: NodeJS.ErrnoException) => {
				if (error.code !== 'ENOENT') throw error;
			});
			else await writeFile(paths[index], original[index]!, { mode: 0o600 });
		}
	}
});
