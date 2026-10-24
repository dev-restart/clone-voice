<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { audioUrl, languages } from '$lib/studio/api';
	import type { RuntimeModelStatus, VoiceProfile } from '$lib/studio/types';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import ModelPicker from '$lib/components/model-picker/ModelPicker.svelte';

	type CoverQuality = 'fast' | 'balanced' | 'quality';

	let {
		voices,
		vcModels,
		selectedVoice,
		selectedModel,
		sttProvider,
		sttLanguage,
		voiceId,
		modelId,
		quality,
		cfgScale,
		autoShift,
		pitchShift,
		separateVocals,
		mixAccompaniment,
		seed,
		onSttProviderChange,
		onSttLanguageChange,
		onModelChange,
		onVoiceChange,
		onQualityChange,
		onCfgScaleChange,
		onAutoShiftChange,
		onPitchShiftChange,
		onSeparateVocalsChange,
		onMixAccompanimentChange,
		onSeedChange
	}: {
		voices: VoiceProfile[];
		vcModels: RuntimeModelStatus[];
		selectedVoice?: VoiceProfile;
		selectedModel?: RuntimeModelStatus;
		sttProvider: 'whisper' | 'apple-speech';
		sttLanguage: string;
		voiceId: string;
		modelId: string;
		quality: CoverQuality;
		cfgScale: number;
		autoShift: boolean;
		pitchShift: number;
		separateVocals: boolean;
		mixAccompaniment: boolean;
		seed: number;
		onSttProviderChange: (value: 'whisper' | 'apple-speech') => void;
		onSttLanguageChange: (value: string) => void;
		onModelChange: (value: string) => void;
		onVoiceChange: (value: string) => void;
		onQualityChange: (value: CoverQuality) => void;
		onCfgScaleChange: (value: number) => void;
		onAutoShiftChange: (value: boolean) => void;
		onPitchShiftChange: (value: number) => void;
		onSeparateVocalsChange: (value: boolean) => void;
		onMixAccompanimentChange: (value: boolean) => void;
		onSeedChange: (value: number) => void;
	} = $props();
</script>

<aside class="surface inspector">
	<h2>{t('cover.set.title')}</h2>
	{#if selectedModel?.status === 'unavailable'}
		<p class="warning-note">{selectedModel.message || t('cover.set.prepare')}</p>
	{:else if !selectedModel}
		<p class="warning-note">{t('cover.set.noModel')}</p>
	{/if}

	<div class="voice-setting">
		<div class="field-heading"><span class="field-label">{t('cover.set.model')}</span></div>
		<ModelPicker models={vcModels} value={modelId} domain="cover" onChange={onModelChange} />
	</div>

	<div class="voice-setting">
		<div class="field-heading"><label for="cover-target-voice">{t('cover.results.target')}</label><HelpPopover label={t('cover.results.target')} text={t('cover.set.voiceHelp')} /></div>
		<select id="cover-target-voice" class="studio-input" value={voiceId} onchange={(event) => onVoiceChange(event.currentTarget.value)}>
			<option value="">{t('home.voices.placeholder')}</option>
			{#each voices as voice (voice.id)}<option value={voice.id}>{voice.name}</option>{/each}
		</select>
	</div>
	{#if selectedVoice}
		<div class="selected-voice-preview">
			<div class="selected-voice-copy">
				<strong>{selectedVoice.name}</strong>
				<small>{selectedVoice.transcript || t('cover.set.voiceFallback')}</small>
			</div>
			<audio controls preload="metadata" src={audioUrl(selectedVoice.audio_url)}></audio>
		</div>
	{/if}

	<div>
		<span class="field-label">{t('tts.set.quality')}</span>
		<div class="segmented-control" aria-label={t('cover.set.qualityLabel')}>
			<button type="button" class:active={quality === 'fast'} onclick={() => onQualityChange('fast')}>{t('tts.set.quality.fast')}</button>
			<button type="button" class:active={quality === 'balanced'} onclick={() => onQualityChange('balanced')}>{t('tts.set.quality.balanced')}</button>
			<button type="button" class:active={quality === 'quality'} onclick={() => onQualityChange('quality')}>{t('tts.set.quality.high')}</button>
		</div>
	</div>

	<label class="check-row"><input type="checkbox" checked={separateVocals} onchange={(event) => onSeparateVocalsChange(event.currentTarget.checked)} />{t('cover.set.separate')}</label>
	<label class="check-row"><input type="checkbox" checked={mixAccompaniment} disabled={!separateVocals} onchange={(event) => onMixAccompanimentChange(event.currentTarget.checked)} />{t('cover.set.mix')}</label>
	<label class="check-row"><input type="checkbox" checked={autoShift} onchange={(event) => onAutoShiftChange(event.currentTarget.checked)} />{t('cover.set.autoShift')}</label>

	<details class="settings-disclosure">
		<summary>{t('cover.set.advanced')}</summary>
		<div class="settings-disclosure-body">
			<label>{t('cover.set.cfg')} <span class="range-value">{cfgScale.toFixed(1)}</span>
				<input type="range" min="0.5" max="4" step="0.1" value={cfgScale} oninput={(event) => onCfgScaleChange(Number(event.currentTarget.value))} />
			</label>
			<div class="voice-setting"><div class="field-heading"><label for="cover-pitch-shift">{t('assist.pitch')}</label><HelpPopover label={t('assist.pitch')} text={t('cover.set.pitchHelp')} /></div><input id="cover-pitch-shift" class="studio-input" type="number" min="-24" max="24" step="1" value={pitchShift} oninput={(event) => onPitchShiftChange(Number(event.currentTarget.value))} /></div>
			<div class="voice-setting"><div class="field-heading"><label for="cover-seed">{t('cover.set.seed')}</label><HelpPopover label={t('cover.set.seed')} text={t('cover.set.seedHelp')} /></div><input id="cover-seed" class="studio-input" type="number" min="0" max="100000" step="1" value={seed} oninput={(event) => onSeedChange(Number(event.currentTarget.value))} /></div>
		</div>
	</details>

	<details class="settings-disclosure">
		<summary>{t('cover.lyrics')}</summary>
		<div class="settings-disclosure-body">
			<label>{t('cover.set.sttMethod')}
				<select class="studio-input" value={sttProvider} onchange={(event) => onSttProviderChange(event.currentTarget.value as 'whisper' | 'apple-speech')}>
					<option value="whisper">Whisper</option>
					<option value="apple-speech">Apple Speech</option>
				</select>
			</label>
			<label>{t('cover.set.lyricsLanguage')}
				<select class="studio-input" value={sttLanguage} onchange={(event) => onSttLanguageChange(event.currentTarget.value)}>
					{#each languages as item (item.code)}<option value={item.code}>{item.label}</option>{/each}
				</select>
			</label>
		</div>
	</details>
</aside>

<style>
	.field-label {
		display: block;
		margin-bottom: 7px;
		color: var(--graphite);
		font-size: 13px;
		font-weight: 500;
	}

	.voice-setting { display: grid; gap: 7px; }
	.field-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
	.field-heading label { margin: 0; }

	.range-value {
		float: right;
		color: var(--muted-foreground);
		font-variant-numeric: tabular-nums;
	}

	input[type='range'] {
		width: 100%;
		accent-color: var(--accent);
	}

	.selected-voice-preview {
		display: grid;
		gap: 10px;
		margin-top: 10px;
		border: 1px solid var(--border-soft);
		border-radius: var(--radius-md);
		background: var(--card-elevated);
		padding: 12px;
	}

	.selected-voice-copy small {
		display: block;
		margin-top: 4px;
		color: var(--muted-foreground);
		font-size: 13px;
		line-height: 1.5;
	}
</style>
