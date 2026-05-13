<script lang="ts">
	import { Languages, Loader2 } from 'lucide-svelte';
	import { accents, languages } from '$lib/studio/api';
	import type { RuntimeModelStatus, StorySegment, VoiceProfile } from '$lib/studio/types';

	let {
		selectedSegment,
		selectedIndex = 0,
		totalSegments = 0,
		voices,
		ttsModels,
		defaultTtsModelId = 'omnivoice',
		translatingSegmentId,
		batchSelectionCount = 0,
		onUpdateSegment,
		onTranslateSegment,
		onInsertTag,
		onApplyToSelected,
		onApplyCurrentToSelected
	}: {
		selectedSegment?: StorySegment;
		selectedIndex?: number;
		totalSegments?: number;
		voices: VoiceProfile[];
		ttsModels: RuntimeModelStatus[];
		defaultTtsModelId?: string;
		translatingSegmentId: string;
		batchSelectionCount?: number;
		onUpdateSegment: (id: string, patch: Partial<StorySegment>) => void;
		onTranslateSegment: (id: string) => void;
		onInsertTag: (tag: string) => void;
		onApplyToSelected: (patch: Partial<StorySegment>, notice?: string) => void;
		onApplyCurrentToSelected: () => void;
	} = $props();

	let selectedModel = $derived(ttsModels.find((model) => model.id === (selectedSegment?.model_id ?? defaultTtsModelId)));
	let selectedVoice = $derived(voices.find((voice) => voice.id === selectedSegment?.voice_id));
	let selectedLanguage = $derived(languages.find((item) => item.code === selectedSegment?.language));
	let selectedWords = $derived(selectedSegment?.text.trim().split(/\s+/).filter(Boolean).length ?? 0);
	let canTranslate = $derived(Boolean(selectedSegment && selectedSegment.language !== 'ko' && selectedSegment.text.trim()));

	function statusLabel(model?: RuntimeModelStatus) {
		if (!model) return '모델 없음';
		return model.status === 'available' ? '사용 가능' : '설정 필요';
	}
</script>

<aside class="story-inspector surface">
	<div class="inspector-heading">
		<h2>단락 설정</h2>
		<p>선택한 단락의 모델, 목소리, 언어와 연출을 조정합니다.</p>
	</div>
	{#if selectedSegment}
		<div class="story-selection-summary">
			<div>
				<strong>단락 {selectedIndex + 1}/{totalSegments}</strong>
				<p>{selectedWords}단어 · {selectedLanguage?.label ?? selectedSegment.language} · {selectedVoice?.name ?? 'Auto Voice'}</p>
			</div>
			<span class:available={selectedModel?.status === 'available'}>{statusLabel(selectedModel)}</span>
		</div>
		{#if batchSelectionCount > 0}
			<div class="story-batch-panel">
				<div>
					<strong>선택 단락 {batchSelectionCount}개</strong>
					<p>현재 단락을 기준으로 여러 단락의 목소리와 연출을 맞춥니다.</p>
				</div>
				<button class="secondary-action full" onclick={onApplyCurrentToSelected}>현재 설정 전체 적용</button>
				<div class="story-batch-mini-actions">
					<button onclick={() => onApplyToSelected({ voice_id: selectedSegment.voice_id ?? '' }, '목소리를 적용했습니다.')}>목소리</button>
					<button
						onclick={() =>
							onApplyToSelected(
								{
									model_id: selectedSegment.model_id ?? defaultTtsModelId,
									language: selectedSegment.language,
									accent: selectedSegment.accent ?? ''
								},
								'모델과 언어를 적용했습니다.'
							)}
					>
						모델/언어
					</button>
					<button
						onclick={() =>
							onApplyToSelected(
								{
									tone_prompt: selectedSegment.tone_prompt ?? '',
									speed: selectedSegment.speed,
									pause_after_ms: selectedSegment.pause_after_ms
								},
								'연출과 쉼을 적용했습니다.'
							)}
					>
						연출/쉼
					</button>
				</div>
			</div>
		{/if}
		<label>
			생성 모델
			<select class="studio-input" value={selectedSegment.model_id ?? defaultTtsModelId} onchange={(event) => onUpdateSegment(selectedSegment.id, { model_id: event.currentTarget.value })}>
				{#each ttsModels as model}
					<option value={model.id} disabled={model.status === 'unavailable'}>{model.label}</option>
				{/each}
			</select>
		</label>
		<label>
			기준 목소리
			<select class="studio-input" value={selectedSegment.voice_id ?? ''} onchange={(event) => onUpdateSegment(selectedSegment.id, { voice_id: event.currentTarget.value })}>
				<option value="">Auto Voice</option>
				{#each voices as voice}
					<option value={voice.id}>{voice.name}</option>
				{/each}
			</select>
		</label>
		<label>
			생성 언어
			<select class="studio-input" value={selectedSegment.language} onchange={(event) => onUpdateSegment(selectedSegment.id, { language: event.currentTarget.value, translated_text: null })}>
				{#each languages as item}
					<option value={item.code}>{item.label}</option>
				{/each}
			</select>
		</label>
		<button class="secondary-action full" disabled={!canTranslate || translatingSegmentId === selectedSegment.id} onclick={() => onTranslateSegment(selectedSegment.id)}>
			{#if translatingSegmentId === selectedSegment.id}<Loader2 class="spin" size={17} />번역 중{:else}<Languages size={17} />이 단락 번역{/if}
		</button>
		<small class="field-helper">{selectedSegment.language === 'ko' ? '한국어 단락은 번역 없이 바로 생성합니다.' : '번역 후에는 번역문을 직접 수정할 수 있습니다.'}</small>
		<label>
			발음/억양
			<select class="studio-input" value={selectedSegment.accent ?? ''} onchange={(event) => onUpdateSegment(selectedSegment.id, { accent: event.currentTarget.value })}>
				{#each accents as accent}
					<option value={accent.value}>{accent.label}</option>
				{/each}
			</select>
		</label>
		<label>
			톤/연출 프롬프트
			<input class="studio-input" value={selectedSegment.tone_prompt ?? ''} oninput={(event) => onUpdateSegment(selectedSegment.id, { tone_prompt: event.currentTarget.value })} placeholder="예: calm, reflective 또는 차분하게" />
		</label>
		<div class="inline-toolbar story-tag-toolbar">
			<button onclick={() => onInsertTag('(break)')}>쉼</button>
			<button onclick={() => onInsertTag('(breath)')}>호흡</button>
			<button onclick={() => onInsertTag('[laughter]')}>웃음</button>
			<button onclick={() => onInsertTag('[sigh]')}>한숨</button>
		</div>
		<label class="range-field">
			<span>속도 <b>{selectedSegment.speed.toFixed(2)}x</b></span>
			<input type="range" min="0.5" max="2" step="0.05" value={selectedSegment.speed} oninput={(event) => onUpdateSegment(selectedSegment.id, { speed: Number(event.currentTarget.value) })} />
		</label>
		<label class="range-field">
			<span>다음 단락 전 쉼 <b>{selectedSegment.pause_after_ms}ms</b></span>
			<input type="range" min="0" max="3000" step="50" value={selectedSegment.pause_after_ms} oninput={(event) => onUpdateSegment(selectedSegment.id, { pause_after_ms: Number(event.currentTarget.value) })} />
		</label>
	{/if}
</aside>
