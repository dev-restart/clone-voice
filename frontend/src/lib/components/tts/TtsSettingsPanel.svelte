<script lang="ts">
	import { accents, languages } from '$lib/studio/api';
	import type { RuntimeModelStatus, VoiceProfile } from '$lib/studio/types';

	let {
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
		onSelectedVoiceChange,
		onModelChange,
		onLanguageChange,
		onAccentChange,
		onTonePromptChange,
		onStylePromptChange,
		onSpeedChange,
		onNormalizeOutputChange
	}: {
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
		onSelectedVoiceChange: (value: string) => void;
		onModelChange: (value: string) => void;
		onLanguageChange: (value: string) => void;
		onAccentChange: (value: string) => void;
		onTonePromptChange: (value: string) => void;
		onStylePromptChange: (value: string) => void;
		onSpeedChange: (value: number) => void;
		onNormalizeOutputChange: (value: boolean) => void;
	} = $props();

	function modelDisabled(model: RuntimeModelStatus) {
		return model.status === 'unavailable';
	}

	function statusLabel(model?: RuntimeModelStatus) {
		if (!model) return '모델 없음';
		return model.status === 'available' ? '사용 가능' : '설정 필요';
	}

	let voiceHelper = $derived.by(() => {
		if (!selectedModel) return '먼저 사용할 모델을 선택하세요.';
		if (!canUseVoice) return `${selectedModel.label}은 현재 목소리 복제를 사용하지 않습니다.`;
		if (!voices.length) return '등록된 목소리가 없습니다. 목소리 라이브러리에서 샘플을 먼저 추가하세요.';
		return '선택하지 않으면 기본 TTS 목소리로 생성합니다.';
	});
</script>

<aside class="surface inspector tts-settings-card">
	<div class="inspector-heading">
		<h2>생성 설정</h2>
		<p>모델, 기준 목소리, 언어와 스타일을 정한 뒤 음성을 생성합니다.</p>
	</div>

	<div class="settings-status-card">
		<div>
			<strong>{selectedModel?.label ?? '모델 선택 필요'}</strong>
			<p>{selectedModel ? `${selectedModel.provider} · ${(selectedModel.sample_rate / 1000).toFixed(0)}kHz` : '사용 가능한 TTS 모델을 확인하세요.'}</p>
		</div>
		{#if selectedModel?.status === 'unavailable'}
			<span>{statusLabel(selectedModel)}</span>
		{/if}
	</div>

	<label>생성 모델
		<select class="studio-input" value={modelId} onchange={(event) => onModelChange(event.currentTarget.value)}>
			{#each ttsModels as model (model.id)}
				<option value={model.id} disabled={modelDisabled(model)}>{model.label}</option>
			{/each}
		</select>
	</label>
	<label>기준 목소리
		<select class="studio-input" value={selectedVoiceId} onchange={(event) => onSelectedVoiceChange(event.currentTarget.value)} disabled={!canUseVoice}>
			<option value="">목소리 없이 생성</option>
			{#each voices as voice (voice.id)}<option value={voice.id}>{voice.name}</option>{/each}
		</select>
		<small class="field-helper">{voiceHelper}</small>
	</label>
	<label>생성 언어
		<select class="studio-input" value={language} onchange={(event) => onLanguageChange(event.currentTarget.value)}>
			{#each languages as item (item.code)}<option value={item.code}>{item.label}</option>{/each}
		</select>
	</label>
	<label>발음/억양
		<select class="studio-input" value={accent} onchange={(event) => onAccentChange(event.currentTarget.value)}>
			{#each accents as item (item.value)}<option value={item.value}>{item.label}</option>{/each}
		</select>
	</label>
	<label>톤 프롬프트<input class="studio-input" value={tonePrompt} oninput={(event) => onTonePromptChange(event.currentTarget.value)} placeholder="예: 차분하게, 밝게, 낮은 톤" /></label>
	<label>스타일 지시<input class="studio-input" value={stylePrompt} oninput={(event) => onStylePromptChange(event.currentTarget.value)} placeholder="모델에 추가로 전달할 스타일 지시" /></label>
	<label class="range-field">
		<span>속도 <b>{speed}x</b></span>
		<input type="range" min="0.5" max="2" step="0.1" value={speed} oninput={(event) => onSpeedChange(Number(event.currentTarget.value))} />
	</label>
	<label class="check-row setting-check"><input type="checkbox" checked={normalizeOutput} onchange={(event) => onNormalizeOutputChange(event.currentTarget.checked)} />생성 후 음량 정규화</label>
	{#if selectedModel?.status === 'unavailable'}<p class="warning-note">{selectedModel.message}</p>{/if}
</aside>
