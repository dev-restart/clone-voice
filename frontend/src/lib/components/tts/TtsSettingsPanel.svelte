<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { RotateCcw } from '@lucide/svelte';
	import { accents, audioUrl, languages } from '$lib/studio/api';
	import type { RuntimeModelStatus, VoiceProfile } from '$lib/studio/types';
	import { cloneReadiness } from '$lib/studio/voices';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import ModelPicker from '$lib/components/model-picker/ModelPicker.svelte';

	let {
		busy = false,
		voices,
		ttsModels,
		selectedModel,
		canUseVoice,
		selectedVoiceId,
		modelId,
		language,
		accent,
		tonePrompt,
		stylePrompt,
		speed,
		normalizeOutput,
		quality,
		onCreateVoice,
		onSelectedVoiceChange,
		onModelChange,
		onLanguageChange,
		onAccentChange,
		onTonePromptChange,
		onStylePromptChange,
		onSpeedChange,
		onNormalizeOutputChange,
		onQualityChange
	}: {
		busy?: boolean;
		voices: VoiceProfile[];
		ttsModels: RuntimeModelStatus[];
		selectedModel?: RuntimeModelStatus;
		canUseVoice: boolean;
		selectedVoiceId: string;
		modelId: string;
		language: string;
		accent: string;
		tonePrompt: string;
		stylePrompt: string;
		speed: number;
		normalizeOutput: boolean;
		quality: 'fast' | 'balanced' | 'high';
		onCreateVoice?: () => void;
		onSelectedVoiceChange: (value: string) => void;
		onModelChange: (value: string) => void;
		onLanguageChange: (value: string) => void;
		onAccentChange: (value: string) => void;
		onTonePromptChange: (value: string) => void;
		onStylePromptChange: (value: string) => void;
		onSpeedChange: (value: number) => void;
		onNormalizeOutputChange: (value: boolean) => void;
		onQualityChange: (value: 'fast' | 'balanced' | 'high') => void;
	} = $props();

	const speedPresets = $derived([
		{ label: t('tts.set.slow'), value: 0.85 },
		{ label: t('tts.set.normal'), value: 1 },
		{ label: t('tts.set.fast'), value: 1.15 }
	]);
	const qualityOptions = $derived([
		{ value: 'fast', label: t('tts.set.quality.fast'), hint: t('tts.set.quality.fastHint') },
		{ value: 'balanced', label: t('tts.set.quality.balanced'), hint: t('tts.set.quality.balancedHint') },
		{ value: 'high', label: t('tts.set.quality.high'), hint: t('tts.set.quality.highHint') }
	] as const);

	let availableModels = $derived(ttsModels.filter((model) => model.status === 'available'));
	let isVoxcpm = $derived(selectedModel?.id === 'voxcpm');
	let referenceVoice = $derived(voices.find((voice) => voice.id === selectedVoiceId));
	let usesStyleInstruction = $derived(Boolean(tonePrompt.trim() || stylePrompt.trim() || accent.trim()));
	let qualityHint = $derived(qualityOptions.find((option) => option.value === quality)?.hint ?? '');
	let voiceHelper = $derived.by(() => {
		if (!selectedModel) return t('tts.set.noEngine');
		if (!canUseVoice) return t('tts.set.noClone');
		if (selectedVoiceId && !referenceVoice) return t('tts.set.voiceMissing');
		if (!voices.length) return t('tts.set.noVoices');
		if (!selectedVoiceId) return t('tts.set.defaultVoice');
		if (referenceVoice && isVoxcpm) {
			const readiness = cloneReadiness(referenceVoice);
			return readiness.precise ? t('tts.set.precise') : t('tts.set.basic');
		}
		return '';
	});
	let voiceNeedsAttention = $derived(!selectedModel || !canUseVoice || Boolean(selectedVoiceId && !referenceVoice) || !voices.length);
	let styleDisabled = $derived(!selectedModel);
</script>

<aside class="surface inspector tts-settings-card">
	<fieldset class="tts-edit-fields" disabled={busy}>
		<h2 class="panel-title">{t('tts.set.title')}</h2>

		<section class="setting-block">
			<div class="block-head">
				<label class="block-label" for="tts-voice">{t('tts.set.voice')}</label>
				{#if voiceHelper && !voiceNeedsAttention}<HelpPopover label={t('tts.set.voiceHelp')} text={voiceHelper} />{/if}
			</div>
			<select id="tts-voice" class="studio-input" aria-describedby={voiceNeedsAttention && voiceHelper ? 'tts-voice-helper' : undefined} value={selectedVoiceId} onchange={(event) => onSelectedVoiceChange(event.currentTarget.value)} disabled={!canUseVoice}>
				<option value="">{t('tts.set.defaultVoiceOption')}</option>
				{#if selectedVoiceId && !referenceVoice}<option value={selectedVoiceId} disabled>{t('tts.set.voiceUnavailable')}</option>{/if}
				{#each voices as voice (voice.id)}<option value={voice.id}>{voice.name}</option>{/each}
			</select>
			{#if voiceHelper && voiceNeedsAttention}<small id="tts-voice-helper" class="field-helper">{voiceHelper}</small>{/if}
			{#if onCreateVoice}<button type="button" class="secondary-action" onclick={onCreateVoice}>{t('tts.set.newVoice')}</button>{/if}
			{#if referenceVoice?.audio_url}
				<audio class="voice-sample" controls preload="none" aria-label={t('tts.set.sample')} src={audioUrl(referenceVoice.audio_url)}></audio>
			{/if}
		</section>

		<section class="setting-block">
			<div class="block-head">
				<label class="block-label" for="tts-speed">{t('tts.speed')}</label>
				<span class="value-chip">{speed.toFixed(2).replace(/0$/, '')}x</span>
			</div>
			<div class="chip-row" role="group" aria-label={t('tts.set.speedPresets')}>
				{#each speedPresets as preset (preset.value)}
					<button type="button" class:active={Math.abs(speed - preset.value) < 0.005} onclick={() => onSpeedChange(preset.value)}>{preset.label}</button>
				{/each}
				<button type="button" class="reset" aria-label={t('tts.set.speedReset')} disabled={Math.abs(speed - 1) < 0.005} onclick={() => onSpeedChange(1)}><RotateCcw size={13} /></button>
			</div>
			<input id="tts-speed" type="range" min="0.5" max="2" step="0.05" value={speed} oninput={(event) => onSpeedChange(Number(event.currentTarget.value))} />
			<div class="range-scale" aria-hidden="true"><span>0.5x</span><span>1x</span><span>2x</span></div>
		</section>

		{#if isVoxcpm}
			<section class="setting-block">
				<div class="block-head"><span class="block-label" id="tts-quality-label">{t('tts.set.quality')}</span><HelpPopover label={t('tts.set.quality')} text={qualityHint} /></div>
				<div class="segmented-control" role="radiogroup" aria-labelledby="tts-quality-label">
					{#each qualityOptions as option (option.value)}
						<button type="button" role="radio" aria-checked={quality === option.value} class:active={quality === option.value} onclick={() => onQualityChange(option.value)}>{option.label}</button>
					{/each}
				</div>
			</section>
		{/if}

		<details class="tts-advanced-settings">
			<summary>{t('tts.set.advanced')}</summary>
			<div class="tts-advanced-fields">
				{#if availableModels.length > 1 || selectedModel?.status !== 'available'}
					<div class="grid gap-1.5">
						<span class="block-label" id="tts-engine-label">{t('tts.set.engine')}</span>
						<ModelPicker models={ttsModels} value={modelId} domain="voice" onChange={onModelChange} />
					</div>
				{/if}
				<div class="block-head"><label class="check-row setting-check"><input type="checkbox" checked={normalizeOutput} onchange={(event) => onNormalizeOutputChange(event.currentTarget.checked)} />{t('tts.set.normalize')}</label><HelpPopover label={t('tts.set.normalize')} text={t('tts.set.normalizeHelp')} /></div>
				<label>{t('tts.set.tone')} <small>{t('common.optional')}</small>
					<input class="studio-input" value={tonePrompt} oninput={(event) => onTonePromptChange(event.currentTarget.value)} placeholder={t('tts.set.tonePlaceholder')} disabled={styleDisabled} />
				</label>
				<label>{t('tts.set.style')} <small>{t('common.optional')}</small>
					<input class="studio-input" value={stylePrompt} oninput={(event) => onStylePromptChange(event.currentTarget.value)} placeholder={t('tts.set.stylePlaceholder')} disabled={styleDisabled} />
				</label>
				<label>{t('tts.set.accent')} <small>{t('common.optional')}</small>
					<select class="studio-input" value={accent} onchange={(event) => onAccentChange(event.currentTarget.value)} disabled={styleDisabled}>
						{#each accents as item (item.value)}<option value={item.value}>{item.label}</option>{/each}
					</select>
				</label>
				{#if isVoxcpm && usesStyleInstruction}
					<p class="warning-note">{t('tts.set.styleWarning')}</p>
				{/if}
			</div>
		</details>

		{#if selectedModel?.status === 'unavailable'}<p class="warning-note">{t('tts.set.modelNotReady')}</p><details><summary>{t('tts.set.modelDetails')}</summary><p class="warning-note">{selectedModel.message || t('tts.set.modelCheck')}</p></details>{/if}
		{#if !selectedModel}<p class="warning-note">{t('tts.set.modelMissing')}</p>{/if}
	</fieldset>
</aside>

<style>
	.panel-title { margin: 0 0 4px; font-size: 18px; font-weight: 700; }
	.setting-block { display: grid; gap: 8px; padding: 14px 0; border-top: 1px solid var(--border-soft); }
	.setting-block:first-of-type { border-top: 0; padding-top: 6px; }
	.block-label { font-size: 13px; font-weight: 650; color: var(--foreground); }
	.block-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
	.value-chip { border-radius: 999px; background: var(--accent-soft); padding: 2px 10px; color: var(--accent-hover); font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; }
	.voice-sample { width: 100%; height: 38px; }
	.chip-row { display: flex; gap: 6px; }
	.chip-row button { flex: 1; min-height: 32px; border: 1px solid var(--border); border-radius: 8px; background: var(--card-elevated); color: var(--muted-foreground); font-size: 12.5px; cursor: pointer; }
	.chip-row button.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent-hover); font-weight: 650; }
	.chip-row button.reset { flex: 0 0 34px; display: inline-flex; align-items: center; justify-content: center; }
	.chip-row button:disabled { opacity: 0.45; cursor: default; }
	input[type='range'] { width: 100%; accent-color: var(--accent); }
	.range-scale { display: flex; justify-content: space-between; margin-top: -4px; color: var(--subtle-foreground); font-size: 11px; }
	.setting-check { display: grid; grid-template-columns: auto 1fr; column-gap: 8px; align-items: center; border-top: 0; padding-top: 0; }
	.tts-advanced-fields label small { color: var(--subtle-foreground); font-weight: 400; }
</style>
