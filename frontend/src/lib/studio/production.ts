import { getLocale, t, type MessageKey } from '../i18n/core.ts';
import type { ContentProductionSettings, PronunciationRule } from './types.ts';

export type ProductionTemplate = {
	id: string;
	title: string;
	description: string;
	use: string;
	text: string;
	speed: number;
	language: 'ko' | 'en';
};

const TEMPLATES = [
	{ id: 'short-video', speed: 1.1 },
	{ id: 'course', speed: 0.9 },
	{ id: 'product', speed: 1 },
	{ id: 'announcement', speed: 0.9 },
] as const;

/** Localized starter scripts. The script is written in the UI language, so its source language follows it. */
export function getProductionTemplates(): ProductionTemplate[] {
	const language = getLocale();
	return TEMPLATES.map(({ id, speed }) => ({
		id,
		speed,
		language,
		title: t(`tpl.${id}.title` as MessageKey),
		description: t(`tpl.${id}.desc` as MessageKey),
		use: t(`tpl.${id}.use` as MessageKey),
		text: t(`tpl.${id}.text` as MessageKey)
	}));
}

export function defaultProductionSettings(modelId: string): ContentProductionSettings {
	return { model_id: modelId, voice_id: null, language: 'ko', accent: '', tone_prompt: '', style_prompt: '', speed: 1, normalize_output: true, quality: 'balanced', pronunciation_rules: [] };
}

export function pronunciationError(rules: PronunciationRule[]): string {
	if (rules.length > 100) return t('prod.error.tooMany');
	const keys = new Set<string>();
	for (const rule of rules) {
		const source = rule.source.trim().normalize('NFC');
		const replacement = rule.replacement.trim().normalize('NFC');
		if (!source || !replacement) return t('prod.error.incomplete');
		if (source.length > 100 || replacement.length > 200 || /[\n\r\t\[\]]/.test(source + replacement)) return t('prod.error.length');
		const key = JSON.stringify([source, rule.language]);
		if (keys.has(key)) return t('prod.error.duplicate');
		keys.add(key);
	}
	return '';
}

export function applyPronunciations(text: string, rules: PronunciationRule[], language: string): string {
	const entries = new Map<string, string>();
	for (const scope of ['all', language]) {
		for (const rule of rules) {
			if (rule.language === scope && rule.source.trim() && rule.replacement.trim()) entries.set(rule.source.trim().normalize('NFC'), rule.replacement.trim().normalize('NFC'));
		}
	}
	if (!entries.size) return text;
	const alternatives = [...entries.keys()].sort((a, b) => b.length - a.length).map((source) => {
		const start = /^[A-Za-z0-9_]/.test(source) ? '(?<![A-Za-z0-9_])' : '';
		const end = /[A-Za-z0-9_]$/.test(source) ? '(?![A-Za-z0-9_])' : '';
		return start + source.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + end;
	});
	const pattern = new RegExp(alternatives.join('|'), 'g');
	return text.normalize('NFC').split(/(\[[^\]\n]*\])/).map((part, index) => index % 2 ? part : part.replace(pattern, (match) => entries.get(match) ?? match)).join('');
}

export type TtsEntry = { contentId?: string; templateId?: string; newDraft?: boolean };
export type TtsRecoveryDraft = {
	version: 1;
	contentId: string;
	title: string;
	source_text: string;
	translations: Record<string, string>;
	production_settings: ContentProductionSettings;
	updatedAt: string;
};

export const ttsRecoveryKey = 'clone-voice-tts-draft-v1';

export function readRecoveryDraft(raw: string | null): TtsRecoveryDraft | null {
	if (!raw) return null;
	try {
		const value = JSON.parse(raw);
		const settings = value.production_settings;
		if (value.version !== 1 || typeof value.contentId !== 'string' || typeof value.title !== 'string' || typeof value.source_text !== 'string' || !value.source_text.trim()) return null;
		if (!settings || !Array.isArray(settings.pronunciation_rules) || typeof settings.speed !== 'number' || settings.speed < 0.5 || settings.speed > 2) return null;
		if (typeof settings.normalize_output !== 'boolean' || [settings.accent, settings.tone_prompt, settings.style_prompt].some((text) => typeof text !== 'string')) return null;
		if ([settings.model_id, settings.voice_id].some((value) => value !== null && typeof value !== 'string')) return null;
		if (!['ko', 'en', 'ja', 'zh', 'es', 'fr', 'de'].includes(settings.language) || !['fast', 'balanced', 'high'].includes(settings.quality)) return null;
		if (settings.pronunciation_rules.some((rule: PronunciationRule) => !rule || typeof rule.source !== 'string' || typeof rule.replacement !== 'string' || !['all', 'ko', 'en', 'ja', 'zh', 'es', 'fr', 'de'].includes(rule.language))) return null;
		if (!value.translations || typeof value.translations !== 'object' || Array.isArray(value.translations) || Object.values(value.translations).some((text) => typeof text !== 'string')) return null;
		if (typeof value.updatedAt !== 'string' || !Number.isFinite(Date.parse(value.updatedAt))) return null;
		return value;
	} catch {
		return null;
	}
}
