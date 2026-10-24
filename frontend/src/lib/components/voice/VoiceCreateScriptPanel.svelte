<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { Loader2, Mic } from '@lucide/svelte';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import { languages } from '$lib/studio/api';
	let {
		name, transcript, sampleText, sttProvider, sttLanguage, busy, hasFile, transcribing, transcriptStale,
		onNameChange, onTranscriptChange, onSttProviderChange, onSttLanguageChange,
		onTranscribeSelection, onConfirmTranscript
	}: {
		name: string; transcript: string; sampleText: string;
		sttProvider: 'whisper' | 'apple-speech'; sttLanguage: string;
		busy: boolean; hasFile: boolean; transcribing: boolean; transcriptStale: boolean;
		onNameChange: (value: string) => void; onTranscriptChange: (value: string) => void;
		onSttProviderChange: (value: 'whisper' | 'apple-speech') => void;
		onSttLanguageChange: (value: string) => void; onTranscribeSelection: () => void;
		onConfirmTranscript: () => void;
	} = $props();
</script>

<div class="voice-form-flow">
	<label>{t('voice.script.name')}<input class="studio-input" value={name} disabled={busy} oninput={(event) => onNameChange(event.currentTarget.value)} placeholder={t('voice.script.namePlaceholder')} /></label>
	<div class="voice-script-field">
		<span class="label-row">
			<span class="inline-flex items-center gap-1"><label for="voice-sample-transcript">{t('voice.script.title')}</label><HelpPopover label={t('voice.script.title')} text={t('voice.script.help')} /></span>
			<button class="secondary-action compact" disabled={busy || transcribing || !hasFile} onclick={onTranscribeSelection} type="button">
				{#if transcribing}<Loader2 class="spin" size={16} />{t('voice.script.busy')}{:else}<Mic size={16} />{t('voice.script.run')}{/if}
			</button>
		</span>
		<textarea id="voice-sample-transcript" class="studio-input transcript-box" value={transcript} disabled={busy}
			oninput={(event) => onTranscriptChange(event.currentTarget.value)} placeholder={sampleText}></textarea>
		{#if transcriptStale}
			<div class="transcript-stale" role="status">
				<p>{t('voice.script.stale')}</p>
				<button class="secondary-action compact" type="button" disabled={busy || transcribing} onclick={onConfirmTranscript}>{t('voice.script.confirm')}</button>
			</div>
		{/if}
	</div>
	<div class="settings-inline">
		<label>{t('voice.script.engine')}
			<select class="studio-input" value={sttProvider} disabled={busy} onchange={(event) => onSttProviderChange(event.currentTarget.value as 'whisper' | 'apple-speech')}>
				<option value="whisper">Whisper</option><option value="apple-speech">Apple Speech</option>
			</select>
		</label>
		<label>{t('voice.script.language')}
			<select class="studio-input" value={sttLanguage} disabled={busy} onchange={(event) => onSttLanguageChange(event.currentTarget.value)}>
				{#each languages as item}<option value={item.code}>{item.label}</option>{/each}
			</select>
		</label>
	</div>
</div>

<style>
	.voice-form-flow { min-width: 0; grid-template-columns: minmax(0, 1fr); }
	.label-row { flex-wrap: wrap; }
	.voice-script-field { min-width: 0; }
	.transcript-stale { display: grid; gap: 9px; padding: 12px; border: 1px solid #d6bb81; border-radius: 10px; background: #fff8e8; color: #725719; }
	.transcript-stale p { margin: 0; font-size: 12px; line-height: 1.6; }
	.transcript-stale button { justify-self: start; }
</style>
