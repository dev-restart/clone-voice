<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { FileAudio, Mic, TextCursorInput } from '@lucide/svelte';

	let {
		fileName,
		busy,
		recording,
		sttProvider,
		text,
		onFileChange,
		onToggleRecord,
		onTranscribe,
		onTextChange
	}: {
		fileName?: string;
		busy: boolean;
		recording: boolean;
		sttProvider: 'whisper' | 'apple-speech';
		text: string;
		onFileChange: (event: Event) => void;
		onToggleRecord: () => void;
		onTranscribe: () => void;
		onTextChange: (value: string) => void;
	} = $props();
</script>

<section class="surface workspace-main stt-input-card">
	<div class="section-heading">
		<div>
			<h2>{t('stt.title')}</h2>
		</div>
		<button class="primary-action" disabled={busy || !fileName} onclick={onTranscribe}><TextCursorInput size={18} />{t('stt.start')}</button>
	</div>

	<div class="stt-flow-row" aria-label={t('stt.stepsLabel')}>
		<span class:active={Boolean(fileName)}>{t('stt.step1')}</span>
		<span class:active={Boolean(text.trim())}>{t('stt.step2')}</span>
		<span>{t('stt.step3')}</span>
	</div>

	<div class="upload-zone stt-dropzone">
		<div class="stt-file-icon"><FileAudio size={34} /></div>
		<div class="stt-dropcopy">
			<h3>{fileName ?? t('stt.pick')}</h3>
			{#if !fileName}<p>{t('stt.formats')}</p>{/if}
		</div>
		<div class="button-row stt-upload-actions">
			<label class="secondary-action">{t('voice.file.pick')}<input class="hidden" type="file" accept="audio/*" onchange={onFileChange} /></label>
			<button class="secondary-action" class:recording onclick={onToggleRecord}><Mic size={17} />{recording ? t('voice.record.stop') : t('voice.source.record')}</button>
		</div>
	</div>

	<div class="stt-result-panel">
		<div class="result-editor-head">
			<div>
			<h3>{t('stt.result')}</h3>
				{#if text.trim()}<p>{t('tts.chars', { count: text.length.toLocaleString() })}</p>{/if}
			</div>
			<span class="soft-badge">{text.trim() ? t('stt.hasResult') : t('stt.waiting')}</span>
		</div>
		<textarea class="script-editor short" value={text} oninput={(event) => onTextChange(event.currentTarget.value)} placeholder={t('stt.placeholder')}></textarea>
	</div>
</section>
