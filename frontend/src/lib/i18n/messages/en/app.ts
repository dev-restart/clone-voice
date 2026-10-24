import type { app } from '../ko/app.ts';

export const app_en: Record<keyof typeof app, string> = {
	'app.voiceDeleted': 'Voice deleted.',
	'app.voiceNotSaved': 'The voice was selected but could not be remembered in this browser.',
	'app.reloadFail': 'Saved, but reloading the list failed. Refresh to see it. {error}'
};
