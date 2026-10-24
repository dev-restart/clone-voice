import { defineConfig } from '@playwright/test';
import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

// Reuse the project browser cache when an isolated runtime has no user cache.
// Explicit browser configuration and standard installations keep their precedence.
const projectBrowserCache = resolve('node_modules/.cache/ms-playwright');
if (!process.env.PLAYWRIGHT_BROWSERS_PATH && !process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH && existsSync(projectBrowserCache)) {
	process.env.PLAYWRIGHT_BROWSERS_PATH = projectBrowserCache;
}

const backendUrl = 'http://127.0.0.1:8011';
const frontendUrl = 'http://127.0.0.1:5186';
const storageDir = process.env.E2E_STORAGE_DIR ?? mkdtempSync(join(tmpdir(), 'clone-voice-e2e-'));
process.env.E2E_STORAGE_DIR = storageDir;
process.env.APP_URL ??= frontendUrl;
process.env.E2E_API_URL ??= backendUrl;

export default defineConfig({
	testDir: './tests',
	testMatch: '**/*.spec.ts',
	workers: 1,
	timeout: 60_000,
	use: { locale: 'ko-KR', viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure', launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH, downloadsPath: resolve('test-results/downloads') } },
	webServer: process.env.APP_URL === frontendUrl ? [
		{
			// The disposable server must not load developer API keys from a dotenv file.
			command: `.venv/bin/python -c "from app.config import Settings; Settings.model_config['env_file'] = None; import uvicorn; uvicorn.run('main:app', host='127.0.0.1', port=8011)"`,
			cwd: resolve('../backend'), url: `${backendUrl}/api/health`, reuseExistingServer: false,
			env: { CLONE_VOICE_STORAGE_DIR: storageDir, CLONE_VOICE_DATABASE_URL: `sqlite:///${join(storageDir, 'clone_voice.db')}`, CLONE_VOICE_VOXCPM_ENABLED: 'false', CLONE_VOICE_SOULX_SINGER_ENABLED: 'false', CLONE_VOICE_STABLE_AUDIO_SFX_ENABLED: 'false', CLONE_VOICE_VOICE_DIR: '', CLONE_VOICE_UPLOAD_DIR: '', CLONE_VOICE_OUTPUT_DIR: '', CLONE_VOICE_CONTENT_DIR: '', CLONE_VOICE_AI_TEXT_SETTINGS_PATH: join(storageDir, 'ai_text_settings.json') }
		},
		{
			command: 'pnpm run dev --host 127.0.0.1 --port 5186', url: frontendUrl, reuseExistingServer: false,
			env: { PUBLIC_API_BASE: backendUrl, CLONE_VOICE_ENV_DIR: storageDir }
		}
	] : undefined
});
