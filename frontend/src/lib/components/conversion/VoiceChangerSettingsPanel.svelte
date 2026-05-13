<script lang="ts">
	import { languages } from '$lib/studio/api';
	import type { RuntimeModelStatus, VoiceProfile } from '$lib/studio/types';

	let {
		voices,
		vcModels,
		selectedModel,
		sttProvider,
		sttLanguage,
		modelId,
		voiceId,
		conversionMode,
		diffusionSteps,
		lengthAdjust,
		inferenceCfgRate,
		f0Condition,
		autoF0Adjust,
		semiToneShift,
		fp16,
		realtimeLaunching,
		realtimeStatus,
		onSttProviderChange,
		onSttLanguageChange,
		onModelChange,
		onVoiceChange,
		onConversionModeChange,
		onDiffusionStepsChange,
		onLengthAdjustChange,
		onInferenceCfgRateChange,
		onF0ConditionChange,
		onAutoF0AdjustChange,
		onSemiToneShiftChange,
		onFp16Change,
		onLaunchRealtime
	}: {
		voices: VoiceProfile[];
		vcModels: RuntimeModelStatus[];
		selectedModel?: RuntimeModelStatus;
		sttProvider: 'whisper' | 'apple-speech';
		sttLanguage: string;
		modelId: string;
		voiceId: string;
		conversionMode: 'voice' | 'singing' | 'v2';
		diffusionSteps: number;
		lengthAdjust: number;
		inferenceCfgRate: number;
		f0Condition: boolean;
		autoF0Adjust: boolean;
		semiToneShift: number;
		fp16: boolean;
		realtimeLaunching: boolean;
		realtimeStatus: { state: 'idle' | 'launching' | 'running' | 'error'; message: string; pid?: number | null };
		onSttProviderChange: (value: 'whisper' | 'apple-speech') => void;
		onSttLanguageChange: (value: string) => void;
		onModelChange: (value: string) => void;
		onVoiceChange: (value: string) => void;
		onConversionModeChange: (value: 'voice' | 'singing' | 'v2') => void;
		onDiffusionStepsChange: (value: number) => void;
		onLengthAdjustChange: (value: number) => void;
		onInferenceCfgRateChange: (value: number) => void;
		onF0ConditionChange: (value: boolean) => void;
		onAutoF0AdjustChange: (value: boolean) => void;
		onSemiToneShiftChange: (value: number) => void;
		onFp16Change: (value: boolean) => void;
		onLaunchRealtime: () => void;
	} = $props();
</script>

<aside class="surface inspector">
	<h2>변환 설정</h2>
	<label>변환 모드
		<select class="studio-input" value={conversionMode} onchange={(event) => onConversionModeChange(event.currentTarget.value as 'voice' | 'singing' | 'v2')}>
			<option value="voice">일반 음성 VC</option>
			<option value="singing">보컬/SVC 변환</option>
			<option value="v2">V2 스타일/익명화</option>
		</select>
	</label>
	{#if conversionMode === 'singing'}
		<p class="field-helper">보컬/SVC는 Seed-VC F0 조건 모델을 사용해 노래의 피치 흐름을 보존하면서 대상 목소리로 변환합니다.</p>
	{:else if conversionMode === 'v2'}
		<p class="warning-note">V2는 Seed-VC 실험 경로입니다. 체크포인트와 로컬 의존성이 맞지 않으면 서버가 명확한 오류를 반환합니다.</p>
	{/if}
	<label>대본 읽기 provider
		<select class="studio-input" value={sttProvider} onchange={(event) => onSttProviderChange(event.currentTarget.value as 'whisper' | 'apple-speech')}>
			<option value="whisper">Whisper</option>
			<option value="apple-speech">Apple Speech</option>
		</select>
	</label>
	<label>대본 언어
		<select class="studio-input" value={sttLanguage} onchange={(event) => onSttLanguageChange(event.currentTarget.value)}>
			{#each languages as item}<option value={item.code}>{item.label}</option>{/each}
		</select>
	</label>
	<label>모델
		<select class="studio-input" value={modelId} onchange={(event) => onModelChange(event.currentTarget.value)}>
			{#each vcModels as model}<option value={model.id} disabled={model.status === 'unavailable'}>{model.label} · {model.status}</option>{/each}
		</select>
	</label>
	<label>대상 목소리
		<select class="studio-input" value={voiceId} onchange={(event) => onVoiceChange(event.currentTarget.value)}>
			<option value="">목소리 선택</option>
			{#each voices as voice}<option value={voice.id}>{voice.name}</option>{/each}
		</select>
	</label>
	{#if selectedModel?.status === 'unavailable'}
		<p class="warning-note">{selectedModel.message}</p>
	{/if}
	<div class="settings-inline">
		<label>Diffusion steps
			<input class="studio-input" type="number" min="4" max="120" step="1" value={diffusionSteps} oninput={(event) => onDiffusionStepsChange(Number(event.currentTarget.value))} />
		</label>
		<label>Length adjust
			<input class="studio-input" type="number" min="0.5" max="2" step="0.05" value={lengthAdjust} oninput={(event) => onLengthAdjustChange(Number(event.currentTarget.value))} />
		</label>
	</div>
	<label>CFG rate
		<input class="studio-input" type="number" min="0" max="2" step="0.05" value={inferenceCfgRate} oninput={(event) => onInferenceCfgRateChange(Number(event.currentTarget.value))} />
	</label>
	<label>반음 이동
		<input class="studio-input" type="number" min="-24" max="24" step="1" value={semiToneShift} oninput={(event) => onSemiToneShiftChange(Number(event.currentTarget.value))} />
	</label>
	<label class="check-row">
		<input type="checkbox" checked={f0Condition || conversionMode === 'singing'} disabled={conversionMode === 'singing'} onchange={(event) => onF0ConditionChange(event.currentTarget.checked)} />
		F0 조건 사용
	</label>
	<label class="check-row">
		<input type="checkbox" checked={autoF0Adjust} onchange={(event) => onAutoF0AdjustChange(event.currentTarget.checked)} />
		자동 F0 보정
	</label>
	<label class="check-row">
		<input type="checkbox" checked={fp16} onchange={(event) => onFp16Change(event.currentTarget.checked)} />
		FP16 추론
	</label>
	<button class="secondary-action full" disabled={selectedModel?.status !== 'available' || realtimeLaunching} onclick={onLaunchRealtime}>
		{realtimeLaunching ? '실시간 GUI 실행 중...' : 'Seed-VC 실시간 GUI 실행'}
	</button>
	{#if realtimeStatus.state !== 'idle'}
		<div class={`realtime-status ${realtimeStatus.state}`} role={realtimeStatus.state === 'error' ? 'alert' : 'status'}>
			<strong>{realtimeStatus.state === 'launching' ? '실행 요청 중' : realtimeStatus.state === 'running' ? '실시간 GUI 실행됨' : '실행 실패'}</strong>
			<p>{realtimeStatus.message}</p>
			{#if realtimeStatus.pid}
				<small>PID {realtimeStatus.pid}</small>
			{/if}
		</div>
	{/if}
	<p class="field-helper">실시간 변환은 Seed-VC의 네이티브 GUI를 실행합니다. 실행된 창에서 입력/출력 장치와 reference audio를 선택하세요.</p>
</aside>
