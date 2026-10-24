<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import { languages } from '$lib/studio/api';

	let {
		sttProvider,
		language,
		targets,
		busy,
		hasText,
		onSttProviderChange,
		onLanguageChange,
		onToggleTarget,
		onTranslate
	}: {
		sttProvider: 'whisper' | 'apple-speech';
		language: string;
		targets: string[];
		busy: boolean;
		hasText: boolean;
		onSttProviderChange: (value: 'whisper' | 'apple-speech') => void;
		onLanguageChange: (value: string) => void;
		onToggleTarget: (code: string) => void;
		onTranslate: () => void;
	} = $props();
</script>

<aside class="surface inspector stt-settings-card">
	<div class="inspector-heading">
		<div class="inline-flex items-center gap-1"><h2 class="inline-flex items-center gap-1">{t('stt.settings')}</h2><HelpPopover label={t('stt.settings')} text={t('stt.settingsHelp')} /></div>
	</div>
	<label>{t('stt.engine')}
		<select class="studio-input" value={sttProvider} onchange={(event) => onSttProviderChange(event.currentTarget.value as 'whisper' | 'apple-speech')}>
			<option value="whisper">Whisper</option>
			<option value="apple-speech">Apple Speech</option>
		</select>
	</label>
	<label>{t('tts.source.language')}
		<select class="studio-input" value={language} onchange={(event) => onLanguageChange(event.currentTarget.value)}>
			<option value="">{t('stt.auto')}</option>
			{#each languages as item}<option value={item.code}>{item.label}</option>{/each}
		</select>
	</label>
	<div class="translation-target-picker">
		<div>
			<strong class="inline-flex items-center gap-1">{t('stt.targets')}<HelpPopover label={t('stt.targets')} text={t('stt.targetsHelp')} /></strong>
		</div>
		<div class="button-row wrap stt-lang-row">
			{#each languages as item}<button class:selected={targets.includes(item.code)} onclick={() => onToggleTarget(item.code)}>{item.label}</button>{/each}
		</div>
	</div>
	<button class="primary-action full" disabled={busy || !hasText} onclick={onTranslate}>{hasText ? t('stt.translate') : t('stt.translateFirst')}</button>
</aside>
