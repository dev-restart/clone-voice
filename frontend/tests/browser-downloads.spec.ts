import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('the browser can finish saving a local download', async ({ page }) => {
	await page.goto(process.env.APP_URL ?? 'http://localhost:5186');
	const pending = page.waitForEvent('download');
	await page.evaluate(() => {
		const anchor = document.createElement('a');
		anchor.href = URL.createObjectURL(new Blob(['Clone Voice download capability check'], { type: 'text/plain' }));
		anchor.download = 'clone-voice-download-check.txt';
		document.body.append(anchor);
		anchor.click();
	});
	const download = await pending;
	const failure = await download.failure();
	// The managed Mac browser also cancels this app-independent text download.
	// Report that limitation explicitly; never treat it as proof that a file saved.
	test.skip(failure === 'canceled', 'Managed browser cancels even an app-independent text download; OS file-save completion could not be verified.');
	expect(failure).toBeNull();
	const path = await download.path();
	expect(path).toBeTruthy();
	expect(await readFile(path!, 'utf8')).toBe('Clone Voice download capability check');
});
