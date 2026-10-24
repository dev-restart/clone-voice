import type { ttsws } from '../ko/ttsws.ts';

export const ttsws_en: Record<keyof typeof ttsws, string> = {
	'ttsws.retryQueued': 'Retrying with the script and settings from when it was queued.',
	'ttsws.newTitle': 'New speech {time}',
	'ttsws.templateTitle': '{title} script',
	'ttsws.copyTitle': '{title} (copy)',
	'ttsws.jobDone': 'Done.',
	'ttsws.progressReconnect': 'Working… checking the progress connection.',
	'ttsws.preparing': 'Getting ready…',
	'ttsws.needText': 'Enter some text to turn into speech.',
	'ttsws.saved': 'Saved.',
	'ttsws.previewReady': 'Preview ready. Press play below.',
	'ttsws.needTargets': 'Choose a language and enter a script first.',
	'ttsws.queued': 'Queued {count} language(s). They are generated one at a time.',
	'ttsws.needScriptTranslate': 'Enter a script to translate first.',
	'ttsws.needLangTranslate': 'Choose at least one language to translate into.',
	'ttsws.translating': 'Translating into the selected languages…',
	'ttsws.translated': 'Translations are ready.',
	'ttsws.translatedNotice': 'Translations created.',
	'ttsws.confirmDelete': 'Delete \'{title}\'?',
	'ttsws.deleted': 'Deleted.',
	'ttsws.defaultVoice': 'Default voice',
	'ttsws.confirmDeleteResult': 'Delete the result \'{label}\'?',
	'ttsws.resultDeleted': 'Result deleted.',
	'ttsws.draft.title': 'You have an unfinished script',
	'ttsws.draft.restore': 'Restore draft',
	'ttsws.queueError': 'Could not check the queue. {error}'
};
