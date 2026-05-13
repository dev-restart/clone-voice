<script lang="ts">
	import { AlertCircle, ArrowDown, ArrowUp, CheckCircle2, Loader2, RefreshCw, Star, ToggleLeft, ToggleRight } from 'lucide-svelte';
	import { apiFetch } from '$lib/studio/api';
	import type { ModelPreference, RuntimeModelStatus } from '$lib/studio/types';

	let {
		models,
		modelPreferences = {},
		defaultTtsModelId = 'omnivoice',
		onReload,
		onNotice,
		onToggleModel,
		onMakeDefaultTts,
		onMoveModel
	}: {
		models: RuntimeModelStatus[];
		modelPreferences?: Record<string, ModelPreference>;
		defaultTtsModelId?: string;
		onReload: () => Promise<void>;
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
		onToggleModel: (modelId: string, enabled: boolean) => void | Promise<void>;
		onMakeDefaultTts: (modelId: string) => void | Promise<void>;
		onMoveModel: (modelId: string, direction: 'up' | 'down') => void | Promise<void>;
	} = $props();

	let loadingModel = $state('');
	let availableCount = $derived(models.filter((model) => model.status === 'available').length);
	let enabledCount = $derived(models.filter((model) => isModelEnabled(model)).length);
	let ttsCount = $derived(models.filter((model) => model.capabilities.tts).length);

	function statusLabel(model: RuntimeModelStatus) {
		if (model.status === 'available') return '사용 가능';
		return '설정 필요';
	}

	function isModelEnabled(model: RuntimeModelStatus) {
		return modelPreferences[model.id]?.enabled ?? true;
	}

	function isDefaultTtsModel(model: RuntimeModelStatus) {
		return model.capabilities.tts && defaultTtsModelId === model.id;
	}

	async function preload(model: RuntimeModelStatus) {
		loadingModel = model.id;
		try {
			await apiFetch(`/api/models/${model.id}/preload`, { method: 'POST' });
			onNotice('success', `${model.label} 로딩 상태를 확인했습니다.`);
			await onReload();
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			loadingModel = '';
		}
	}
</script>

<section class="surface settings-surface">
	<div class="settings-hero">
		<div>
			<h2>모델 상태</h2>
			<p>사용 중인 모델만 생성 화면에 표시하고, TTS 대표 모델과 노출 순서를 정합니다.</p>
		</div>
		<button class="icon-button" onclick={onReload} aria-label="모델 새로고침"><RefreshCw size={18} /></button>
	</div>
	<div class="settings-kpi-row" aria-label="모델 설정 요약">
		<div>
			<span>사용 가능</span>
			<strong>{availableCount}</strong>
		</div>
		<div>
			<span>생성 노출</span>
			<strong>{enabledCount}</strong>
		</div>
		<div>
			<span>TTS 후보</span>
			<strong>{ttsCount}</strong>
		</div>
	</div>
	<div class="model-routing-note">
		<strong>모델 준비와 표시 기준</strong>
		<p>루트에서 <code>./download-models.sh --all</code>을 실행하면 지원 모델을 한 번에 준비할 수 있습니다. 생성 화면에는 실제로 사용할 모델만 켜두고, 대표 TTS 모델을 기본 선택값으로 지정하세요.</p>
	</div>
	<div class="model-grid">
		{#each models as model, index (model.id)}
			<article class="model-card" class:available={model.status === 'available'} class:disabled-by-user={!isModelEnabled(model)}>
				<div class="model-card-head">
					<div>
						<h3>{model.label}</h3>
						<p>{model.provider}</p>
					</div>
					<div class="model-status-stack">
						{#if isDefaultTtsModel(model)}
							<span class="model-status default"><Star size={15} />대표 TTS</span>
						{/if}
						<span class="model-status">
							{#if model.status === 'unavailable'}<AlertCircle size={16} />{:else}<CheckCircle2 size={16} />{/if}
							{statusLabel(model)}
						</span>
					</div>
				</div>
				<div class="capability-row">
					<span class:enabled={model.capabilities.tts}>TTS</span>
					<span class:enabled={model.capabilities.voice_clone_tts}>Voice Clone</span>
					<span class:enabled={model.capabilities.stt}>STT</span>
					<span class:enabled={model.capabilities.voice_conversion}>VC</span>
				</div>
				<div class="model-card-body">
					<div class="meta-list">
						<p>샘플레이트 <b>{model.sample_rate / 1000}kHz</b></p>
						<p>장치 <b>{model.device ?? '-'}</b></p>
						<p>로드 <b>{model.loaded ? '완료' : '대기'}</b></p>
					</div>
					{#if model.recommended_for.length}
						<div class="tag-row">{#each model.recommended_for as item (item)}<span>{item}</span>{/each}</div>
					{/if}
					{#if model.message}<p class="model-message">{model.message}</p>{/if}
				</div>
				<div class="model-preference-panel">
					<div>
						<strong>생성 화면 노출</strong>
						<p>{isModelEnabled(model) ? 'TTS, 스토리, 변환 화면의 모델 선택 목록에 표시됩니다.' : '설정 화면에만 남기고 생성 선택 목록에서는 숨깁니다.'}</p>
					</div>
					<div class="model-preference-controls">
						<button class="secondary-action mini" class:active={isModelEnabled(model)} aria-pressed={isModelEnabled(model)} onclick={() => onToggleModel(model.id, !isModelEnabled(model))}>
							{#if isModelEnabled(model)}<ToggleRight size={16} />사용 중{:else}<ToggleLeft size={16} />미사용{/if}
						</button>
						{#if model.capabilities.tts}
							<button class="secondary-action mini" class:active={isDefaultTtsModel(model)} disabled={!isModelEnabled(model) || model.status === 'unavailable' || isDefaultTtsModel(model)} onclick={() => onMakeDefaultTts(model.id)}>
								<Star size={15} />
								{isDefaultTtsModel(model) ? '대표 모델' : '대표로 사용'}
							</button>
						{/if}
						<div class="model-order-actions" aria-label={`${model.label} 표시 순서`}>
							<button class="icon-button mini" disabled={index === 0} onclick={() => onMoveModel(model.id, 'up')} aria-label={`${model.label} 위로 이동`}><ArrowUp size={15} /></button>
							<button class="icon-button mini" disabled={index === models.length - 1} onclick={() => onMoveModel(model.id, 'down')} aria-label={`${model.label} 아래로 이동`}><ArrowDown size={15} /></button>
						</div>
					</div>
				</div>
				<div class="model-card-actions">
					<button class="primary-action" disabled={loadingModel === model.id || model.status === 'unavailable'} onclick={() => preload(model)}>
						{#if loadingModel === model.id}<Loader2 size={16} class="spin" />{:else}<CheckCircle2 size={16} />{/if}
						모델 로딩 확인
					</button>
				</div>
			</article>
		{/each}
	</div>
</section>
