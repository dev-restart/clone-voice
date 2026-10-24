import type { StorybookConfig } from '@storybook/sveltekit';
import { fileURLToPath } from 'node:url';

const envStub = fileURLToPath(new URL('./env-stub.ts', import.meta.url));

// Stories live under src/stories (design system docs) or next to a component.
const config: StorybookConfig = {
	stories: ['../src/**/*.mdx', '../src/**/*.stories.@(js|ts|svelte)'],
	addons: ['@storybook/addon-svelte-csf', '@storybook/addon-docs'],
	framework: '@storybook/sveltekit',
	viteFinal: async (viteConfig) => {
		viteConfig.resolve = viteConfig.resolve ?? {};
		const alias = viteConfig.resolve.alias;
		viteConfig.resolve.alias = [
			{ find: '$env/dynamic/public', replacement: envStub },
			...(Array.isArray(alias) ? alias : Object.entries(alias ?? {}).map(([find, replacement]) => ({ find, replacement })))
		];
		return viteConfig;
	}
};
export default config;
