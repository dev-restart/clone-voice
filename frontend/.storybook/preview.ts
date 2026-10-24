import type { Preview } from '@storybook/sveltekit';
import '../src/routes/layout.css';
import { i18n, type Locale } from '../src/lib/i18n/index.svelte';

const preview: Preview = {
	globalTypes: {
		locale: {
			description: 'Display language',
			toolbar: {
				title: 'Language',
				icon: 'globe',
				items: [
					{ value: 'ko', title: '한국어' },
					{ value: 'en', title: 'English' }
				],
				dynamicTitle: true
			}
		}
	},
	initialGlobals: { locale: 'ko' },
	// Components read the display language from the shared i18n store, so switching the toolbar re-renders them.
	beforeEach: ({ globals }) => {
		i18n.set(globals.locale as Locale);
	},
	parameters: {
		layout: 'centered',
		controls: { matchers: { color: /(background|color)$/i, date: /Date$/i } },
		backgrounds: { disable: true }
	},
	tags: ['autodocs']
};

export default preview;
