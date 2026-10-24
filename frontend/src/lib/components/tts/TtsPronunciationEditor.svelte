<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { BookOpenText, Plus, Trash2 } from '@lucide/svelte';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import { languages } from '$lib/studio/api';
	import { applyPronunciations } from '$lib/studio/production';
	import type { PronunciationRule } from '$lib/studio/types';
	let { rules, text, language, error, onChange }: {
		rules: PronunciationRule[]; text: string; language: string; error: string;
		onChange: (rules: PronunciationRule[]) => void;
	} = $props();
	let spokenText = $derived(error ? text : applyPronunciations(text, rules, language));
	function update(index: number, patch: Partial<PronunciationRule>) {
		onChange(rules.map((rule, position) => position === index ? { ...rule, ...patch } : rule));
	}
</script>

<details class="pronunciation-editor" open={rules.length > 0}>
	<summary><BookOpenText size={18} /><strong>{t('tts.pron.title')}</strong><HelpPopover label={t('tts.pron.title')} text={t('tts.pron.help')} /><span>{rules.length ? t('home.count', { count: rules.length }) : t('tts.pron.hint')}</span></summary>
	<div class="pronunciation-body">
		{#each rules as rule, index}
			<div class="pronunciation-row">
				<label>{t('tts.pron.word')}<input class="studio-input" aria-label={t('tts.pron.wordLabel', { n: index + 1 })} value={rule.source} maxlength="100" placeholder={t('tts.pron.wordPlaceholder')} oninput={(event) => update(index, { source: event.currentTarget.value })} /></label>
				<label>{t('tts.pron.reading')}<input class="studio-input" aria-label={t('tts.pron.readingLabel', { n: index + 1 })} value={rule.replacement} maxlength="200" placeholder={t('tts.pron.readingPlaceholder')} oninput={(event) => update(index, { replacement: event.currentTarget.value })} /></label>
				<label>{t('tts.pron.scope')}<select class="studio-input" aria-label={t('tts.pron.scopeLabel', { n: index + 1 })} value={rule.language} onchange={(event) => update(index, { language: event.currentTarget.value as PronunciationRule['language'] })}>
					<option value="all">{t('tts.pron.allLanguages')}</option>
					{#each languages as item}<option value={item.code}>{item.label}</option>{/each}
				</select></label>
				<button class="icon-button" aria-label={t('tts.pron.removeLabel', { n: index + 1 })} onclick={() => onChange(rules.filter((_, position) => position !== index))}><Trash2 size={16} /></button>
			</div>
		{/each}
		<button class="secondary-action" disabled={rules.length >= 100} onclick={() => onChange([...rules, { source: '', replacement: '', language: language as PronunciationRule['language'] }])}><Plus size={16} />{t('tts.pron.add')}</button>
		{#if error}<p class="pronunciation-error" role="status">{error}</p>{/if}
		{#if rules.length && !error && text.trim()}
			<div class="spoken-script"><strong>{t('tts.pron.spoken')} {text.length > 400 ? t('tts.pron.beginning') : ''}</strong><p>{spokenText.slice(0, 400)}{spokenText.length > 400 ? '…' : ''}</p>{#if spokenText === text}<small>{t('tts.pron.noMatch')}</small>{/if}</div>
		{/if}
	</div>
</details>
