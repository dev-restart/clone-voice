<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { Languages, Loader2, SlidersHorizontal, Volume2 } from '@lucide/svelte';
	import { accents, languages } from '$lib/studio/api';
	import type { RuntimeModelStatus, StorySegment, StorySpeakerProfile, VoiceProfile } from '$lib/studio/types';
	import HelpPopover from '$lib/components/HelpPopover.svelte';

	let {
		selectedSegment,
		selectedIndex = 0,
		totalSegments = 0,
		voices,
		ttsModels,
		defaultTtsModelId = 'voxcpm',
		translatingSegmentId,
		speakerProfiles,
		batchSelectionCount = 0,
		onUpdateSegment,
		onTranslateSegment,
		onInsertTag,
		onApplyCurrentToSelected,
		onAssignVoiceToSpeaker,
		onAssignToneToSpeaker
	}: {
		selectedSegment?: StorySegment;
		selectedIndex?: number;
		totalSegments?: number;
		voices: VoiceProfile[];
		ttsModels: RuntimeModelStatus[];
		defaultTtsModelId?: string;
		translatingSegmentId: string;
		speakerProfiles: StorySpeakerProfile[];
		batchSelectionCount?: number;
		onUpdateSegment: (id: string, patch: Partial<StorySegment>) => void;
		onTranslateSegment: (id: string) => void;
		onInsertTag: (tag: string) => void;
		onApplyCurrentToSelected: () => void;
		onAssignVoiceToSpeaker: (speakerName: string, voiceId: string) => void;
		onAssignToneToSpeaker: (speakerName: string, tonePrompt: string) => void;
	} = $props();
	const toneSuggestions = $derived([
		t('story.tone.calm'), t('story.tone.bright'), t('story.tone.exciting'), t('story.tone.tense'),
		t('story.tone.serious'), t('story.tone.soft'), t('story.tone.whisper'), t('story.tone.surprised')
	]);

	let selectedModel = $derived(ttsModels.find((model) => model.id === (selectedSegment?.model_id ?? defaultTtsModelId)));
	let selectedVoice = $derived(voices.find((voice) => voice.id === selectedSegment?.voice_id));
	let selectedLanguage = $derived(languages.find((item) => item.code === selectedSegment?.language));
	let canTranslate = $derived(Boolean(selectedSegment && selectedSegment.segment_type !== 'sfx' && selectedSegment.language !== 'ko' && selectedSegment.text.trim()));
	let voxcpmSelected = $derived(selectedModel?.id === 'voxcpm');
</script>

<aside class="story-inspector surface">
	<div class="inspector-heading compact-inspector-heading">
		<div>
			<h2>{selectedSegment?.segment_type === 'sfx' ? t('story.insp.sfx') : t('story.insp.line')}</h2>
			<span>{selectedIndex + 1} / {totalSegments}</span>
		</div>
		{#if selectedSegment?.segment_type === 'sfx'}<Volume2 size={20} />{:else}<SlidersHorizontal size={20} />{/if}
	</div>

	{#if speakerProfiles.length}
		<section class="story-speaker-manager" aria-labelledby="story-speaker-manager-title">
			<div class="story-speaker-manager-heading">
				<div>
					<div class="help-heading"><h3 id="story-speaker-manager-title">{t('story.insp.speakers')}</h3><HelpPopover label={t('story.insp.speakers')} text={t('story.insp.speakersHelp')} /></div>
				</div>
				<span>{t('story.insp.speakerCount', { count: speakerProfiles.length })}</span>
			</div>
			<div class="story-speaker-manager-list">
				{#each speakerProfiles as profile (profile.name)}
					<div class="story-speaker-manager-row">
						<div class="story-speaker-name">
							<strong>{profile.name}</strong>
							<span>{t('story.insp.lines', { count: profile.segment_count })}</span>
						</div>
						<label>
							<span>{t('tts.set.voice')}</span>
							<select
								class="studio-input"
								value={profile.voice_id}
								onchange={(event) => onAssignVoiceToSpeaker(profile.name, event.currentTarget.value)}
								aria-label={t('story.insp.allVoice', { name: profile.name })}
							>
								<option value="">{profile.has_mixed_voices ? t('story.insp.mixedVoices') : t('ttsws.defaultVoice')}</option>
								{#each voices as voice (voice.id)}<option value={voice.id}>{voice.name}</option>{/each}
							</select>
						</label>
						<label>
							<span>{t('story.insp.tone')}</span>
							<input
								class="studio-input"
								list="story-inspector-tone-options"
								value={profile.tone_prompt}
								onchange={(event) => onAssignToneToSpeaker(profile.name, event.currentTarget.value)}
								placeholder={profile.has_mixed_tones ? t('story.insp.mixedTones') : t('story.insp.tonePlaceholder')}
								aria-label={t('story.insp.allTone', { name: profile.name })}
							/>
						</label>
					</div>
				{/each}
			</div>
		</section>
	{/if}

	<datalist id="story-inspector-tone-options">
		{#each toneSuggestions as tone (tone)}<option value={tone}></option>{/each}
	</datalist>

	{#if selectedSegment}
		{#if batchSelectionCount > 0}
			<div class="story-batch-panel compact-batch-panel">
				<strong>{t('story.insp.selected', { count: batchSelectionCount })}</strong>
				<button class="secondary-action full" onclick={onApplyCurrentToSelected}>{t('story.insp.applyCurrent')}</button>
			</div>
		{/if}

		{#if selectedSegment.segment_type === 'sfx'}
			<label>
				{t('story.insp.sfxLength')}
				<div class="range-value-row"><input type="range" min="0.5" max="15" step="0.5" value={selectedSegment.sfx_duration_seconds ?? 3} oninput={(event) => onUpdateSegment(selectedSegment.id, { sfx_duration_seconds: Number(event.currentTarget.value) })} /><b>{t('story.insp.seconds', { value: (selectedSegment.sfx_duration_seconds ?? 3).toFixed(1) })}</b></div>
			</label>
		{:else}
			<label>
				{t('story.speaker')}
				<input class="studio-input" value={selectedSegment.speaker_name ?? ''} oninput={(event) => onUpdateSegment(selectedSegment.id, { speaker_name: event.currentTarget.value })} placeholder={t('story.insp.speakerName')} />
			</label>
			<label>
				{t('tts.set.voice')}
				<select class="studio-input" value={selectedSegment.voice_id ?? ''} onchange={(event) => onUpdateSegment(selectedSegment.id, { voice_id: event.currentTarget.value })}>
					<option value="">{t('ttsws.defaultVoice')}</option>
					{#each voices as voice (voice.id)}<option value={voice.id}>{voice.name}</option>{/each}
				</select>
			</label>
			<div class="story-selection-line">
				<span>{selectedVoice?.name ?? t('ttsws.defaultVoice')}</span>
				<span>{selectedLanguage?.label ?? selectedSegment.language}</span>
				<span class:available={selectedModel?.status === 'available'}>{selectedModel?.status === 'available' ? t('story.insp.ready') : t('story.insp.check')}</span>
			</div>
			<div class="story-setting-field">
				<div class="help-heading"><label for="story-segment-tone">{t('story.insp.lineTone')}</label><HelpPopover label={t('story.insp.lineTone')} text={t('story.insp.lineToneHelp')} /></div>
				<input
					id="story-segment-tone"
					class="studio-input"
					list="story-inspector-tone-options"
					value={selectedSegment.tone_prompt ?? ''}
					oninput={(event) => onUpdateSegment(selectedSegment.id, { tone_prompt: event.currentTarget.value })}
					placeholder={t('story.tone.calm')}
				/>
			</div>

			<details class="story-advanced-settings">
				<summary><SlidersHorizontal size={16} />{t('story.insp.direction')}</summary>
				<div class="story-advanced-fields">
					<label>
						{t('tts.set.engine')}
						<select class="studio-input" value={selectedSegment.model_id ?? defaultTtsModelId} onchange={(event) => onUpdateSegment(selectedSegment.id, { model_id: event.currentTarget.value })}>
							{#each ttsModels as model (model.id)}<option value={model.id} disabled={model.status === 'unavailable'}>{model.label}</option>{/each}
						</select>
					</label>
					<label>
						{t('language.label')}
						<select class="studio-input" value={selectedSegment.language} onchange={(event) => onUpdateSegment(selectedSegment.id, { language: event.currentTarget.value, translated_text: null })}>
							{#each languages as item (item.code)}<option value={item.code}>{item.label}</option>{/each}
						</select>
					</label>
					{#if selectedSegment.language !== 'ko'}
						<button class="secondary-action full" disabled={!canTranslate || translatingSegmentId === selectedSegment.id} onclick={() => onTranslateSegment(selectedSegment.id)}>
							{#if translatingSegmentId === selectedSegment.id}<Loader2 class="spin" size={17} />{t('tts.translate.busy')}{:else}<Languages size={17} />{t('story.insp.translate')}{/if}
						</button>
					{/if}
					<label>
						{t('story.insp.accent')}
						<select class="studio-input" value={selectedSegment.accent ?? ''} onchange={(event) => onUpdateSegment(selectedSegment.id, { accent: event.currentTarget.value })}>
							{#each accents as accent (accent.value)}<option value={accent.value}>{accent.label}</option>{/each}
						</select>
					</label>
					{#if !voxcpmSelected}
						<div class="inline-toolbar story-tag-toolbar">
							<button onclick={() => onInsertTag('(break)')}>{t('story.insp.tagBreak')}</button>
							<button onclick={() => onInsertTag('(breath)')}>{t('story.insp.tagBreath')}</button>
							<button onclick={() => onInsertTag('[laughter]')}>{t('story.insp.tagLaugh')}</button>
							<button onclick={() => onInsertTag('[sigh]')}>{t('story.insp.tagSigh')}</button>
						</div>
					{/if}
					<label class="range-field">
						<span>{t('tts.speed')} <b>{selectedSegment.speed.toFixed(2)}x</b></span>
						<input type="range" min="0.5" max="2" step="0.05" value={selectedSegment.speed} oninput={(event) => onUpdateSegment(selectedSegment.id, { speed: Number(event.currentTarget.value) })} />
					</label>
				</div>
			</details>
		{/if}

		<label class="range-field inspector-pause">
			<span>{t('story.insp.pauseAfter')} <b>{selectedSegment.pause_after_ms}ms</b></span>
			<input type="range" min="0" max="3000" step="50" value={selectedSegment.pause_after_ms} oninput={(event) => onUpdateSegment(selectedSegment.id, { pause_after_ms: Number(event.currentTarget.value) })} />
		</label>
	{/if}
</aside>

<style>
	.help-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
	.help-heading h3, .help-heading label { margin: 0; }
	.story-setting-field { display: grid; gap: 7px; }
</style>
