import { t } from '../i18n/core.ts';
import type { VoiceProfile } from './types';

// Same placeholder sentences as DEFAULT_REFERENCE_PROMPTS in backend/app/services/generation_helpers.py.
// If one of them is left as a sample script it is not real speech, so it is not used for precise cloning.
const defaultReferencePrompts = new Set([
	'안녕하세요. 이 목소리는 음성 합성을 위한 샘플입니다. 또렷하고 자연스럽게 말하며 억양과 발음이 잘 드러나도록 녹음합니다.',
	'안녕하세요. 이 목소리는 로컬 음성 합성을 위한 샘플입니다. 또렷하고 자연스럽게 말하며 억양과 발음이 잘 드러나도록 녹음합니다.',
	'안녕하세요. 이 목소리는 음성 콘텐츠 제작을 위한 샘플입니다. 또렷하고 자연스럽게 말하며, 발음과 억양이 잘 드러나도록 녹음하고 있습니다.'
]);

export type CloneReadiness = {
	precise: boolean;
	label: string;
	hint: string;
	seconds: number | null;
	warning: string;
};

export function cloneReadiness(voice: VoiceProfile): CloneReadiness {
	const transcript = (voice.transcript ?? '').replace(/\s+/g, ' ').trim();
	const precise = transcript.length > 0 && transcript.length <= 500 && !defaultReferencePrompts.has(transcript);
	const seconds = voice.trim_end != null ? Math.max(0, voice.trim_end - (voice.trim_start ?? 0)) : null;
	let warning = '';
	if (seconds !== null && seconds < 3) warning = t('voicelib.warn.short');
	else if (seconds !== null && seconds > 30) warning = t('voicelib.warn.long');
	return precise
		? { precise, label: t('voicelib.precise'), hint: t('voicelib.preciseHint'), seconds, warning }
		: { precise, label: t('voicelib.noScript'), hint: t('voicelib.noScriptHint'), seconds, warning };
}
