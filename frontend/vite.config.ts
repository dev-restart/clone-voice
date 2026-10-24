import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	const envDir = process.env.CLONE_VOICE_ENV_DIR || process.cwd();
	const env = loadEnv(mode, envDir, '');

	return {
		envDir,
		plugins: [tailwindcss(), sveltekit()],
		server: {
			proxy: {
				'/api': {
					target: env.PUBLIC_API_BASE || 'http://127.0.0.1:18109',
					changeOrigin: true,
					ws: true
				}
			}
		}
	};
});
