<script lang="ts">
	import { onMount } from 'svelte';
	import AppShell from '$lib/components/AppShell.svelte';
	import ApiLogPanel from '$lib/components/app/ApiLogPanel.svelte';
	import HomeDashboard from '$lib/components/app/HomeDashboard.svelte';
	import NoticePanel from '$lib/components/app/NoticePanel.svelte';
	import ModelSettingsPanel from '$lib/components/ModelSettingsPanel.svelte';
	import SpeechToTextWorkspace from '$lib/components/SpeechToTextWorkspace.svelte';
	import StoryStudioWorkspace from '$lib/components/StoryStudioWorkspace.svelte';
	import TextToSpeechWorkspace from '$lib/components/TextToSpeechWorkspace.svelte';
	import VoiceChangerWorkspace from '$lib/components/VoiceChangerWorkspace.svelte';
	import VoiceCreateEditor from '$lib/components/VoiceCreateEditor.svelte';
	import VoiceLibrary from '$lib/components/VoiceLibrary.svelte';
	import { apiFetch } from '$lib/studio/api';
	import type { ApiLogEntry } from '$lib/studio/api';
	import type {
		ContentItem,
		MenuKey,
		ModelListResponse,
		ModelPreference,
		ModelPreferencesResponse,
		RuntimeHealth,
		RuntimeModelStatus,
		StudioNotice,
		VoiceProfile
	} from '$lib/studio/types';

	const DEFAULT_MODEL_ORDER: Record<string, number> = {
		omnivoice: 10,
		voxcpm: 20,
		cosyvoice: 30,
		'seed-vc': 40
	};

	let active = $state<MenuKey>('home');
	let voices = $state<VoiceProfile[]>([]);
	let contents = $state<ContentItem[]>([]);
	let models = $state<RuntimeModelStatus[]>([]);
	let health = $state<RuntimeHealth | null>(null);
	let selectedVoiceId = $state('');
	let notice = $state<StudioNotice | null>(null);
	let loading = $state(true);
	let refreshing = $state(false);
	let lastRefreshedAt = $state('');
	let creatingVoice = $state(false);
	let createSession = $state(0);
	let navigationResetKey = $state(0);
	let apiLogs = $state<ApiLogEntry[]>([]);
	let modelPreferences = $state<Record<string, ModelPreference>>({});
	let defaultTtsModelId = $state('omnivoice');

	let orderedModels = $derived(sortModels(models, modelPreferences));
	let activeModels = $derived(orderedModels.filter((model) => isModelEnabled(model.id)));

	onMount(() => {
		const onApiLog = (event: Event) => {
			apiLogs = [(event as CustomEvent<ApiLogEntry>).detail, ...apiLogs].slice(0, 8);
		};
		window.addEventListener('clonevoice:api-log', onApiLog);
		void refreshAll();
		return () => window.removeEventListener('clonevoice:api-log', onApiLog);
	});

	function defaultOrder(model: RuntimeModelStatus, index = 0) {
		return DEFAULT_MODEL_ORDER[model.id] ?? 100 + index;
	}

	function sortModels(items: RuntimeModelStatus[], preferences: Record<string, ModelPreference>) {
		return [...items].sort((a, b) => {
			const orderA = preferences[a.id]?.order ?? defaultOrder(a, items.findIndex((item) => item.id === a.id));
			const orderB = preferences[b.id]?.order ?? defaultOrder(b, items.findIndex((item) => item.id === b.id));
			return orderA - orderB || a.label.localeCompare(b.label);
		});
	}

	function isModelEnabled(modelId: string) {
		return modelPreferences[modelId]?.enabled ?? true;
	}

	function normalizeModelPreferences(nextModels: RuntimeModelStatus[], serverPreferences: Record<string, ModelPreference> = {}, serverDefaultTtsModel?: string | null) {
		const nextPreferences: Record<string, ModelPreference> = {};
		nextModels.forEach((model, index) => {
			const existing = serverPreferences[model.id];
			nextPreferences[model.id] = {
				id: model.id,
				enabled: existing?.enabled ?? true,
				order: Number.isFinite(existing?.order) ? Number(existing.order) : defaultOrder(model, index)
			};
		});

		let nextDefaultTtsModelId = serverDefaultTtsModel || defaultTtsModelId;
		let sorted = sortModels(nextModels, nextPreferences);
		let activeTtsModels = sorted.filter((model) => model.capabilities.tts && nextPreferences[model.id]?.enabled !== false);
		if (!activeTtsModels.length) {
			const firstTtsModel = sorted.find((model) => model.capabilities.tts);
			if (firstTtsModel) {
				nextPreferences[firstTtsModel.id] = { ...nextPreferences[firstTtsModel.id], enabled: true };
				activeTtsModels = [firstTtsModel];
			}
		}

		if (!activeTtsModels.some((model) => model.id === nextDefaultTtsModelId)) {
			nextDefaultTtsModelId = activeTtsModels.find((model) => model.status === 'available')?.id ?? activeTtsModels[0]?.id ?? nextDefaultTtsModelId;
		}

		modelPreferences = nextPreferences;
		defaultTtsModelId = nextDefaultTtsModelId;
	}

	function applyServerModelPreferences(payload: ModelPreferencesResponse) {
		normalizeModelPreferences(models, payload.model_preferences ?? {}, payload.default_tts_model);
	}

	async function saveModelPreferences(nextPreferences: Record<string, ModelPreference>, nextDefaultTtsModelId = defaultTtsModelId) {
		const response = await apiFetch('/api/models/preferences', {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				model_preferences: nextPreferences,
				default_tts_model: nextDefaultTtsModelId
			})
		});
		const payload: ModelPreferencesResponse = await response.json();
		applyServerModelPreferences(payload);
	}

	function firstActiveTtsModel(excludedModelId?: string) {
		return orderedModels.find(
			(model) => model.capabilities.tts && model.id !== excludedModelId && isModelEnabled(model.id) && model.status === 'available'
		) ?? orderedModels.find((model) => model.capabilities.tts && model.id !== excludedModelId && isModelEnabled(model.id));
	}

	async function setModelEnabled(modelId: string, enabled: boolean) {
		const model = models.find((item) => item.id === modelId);
		if (!model) return;
		if (!enabled && model.capabilities.tts && !firstActiveTtsModel(modelId)) {
			showNotice('info', '음성 생성에 사용할 TTS 모델은 최소 한 개 이상 켜두어야 합니다.');
			return;
		}

		const nextPreferences = {
			...modelPreferences,
			[modelId]: {
				id: modelId,
				enabled,
				order: modelPreferences[modelId]?.order ?? defaultOrder(model, models.findIndex((item) => item.id === modelId))
			}
		};
		let nextDefaultTtsModelId = defaultTtsModelId;
		if (!enabled && defaultTtsModelId === modelId) {
			nextDefaultTtsModelId = firstActiveTtsModel(modelId)?.id ?? defaultTtsModelId;
		}
		if (enabled && model.capabilities.tts && !orderedModels.some((item) => item.capabilities.tts && item.id === nextDefaultTtsModelId && nextPreferences[item.id]?.enabled !== false)) {
			nextDefaultTtsModelId = modelId;
		}

		const previousPreferences = modelPreferences;
		const previousDefaultTtsModelId = defaultTtsModelId;
		modelPreferences = nextPreferences;
		defaultTtsModelId = nextDefaultTtsModelId;
		try {
			await saveModelPreferences(nextPreferences, nextDefaultTtsModelId);
			showNotice('success', `${model.label}을 ${enabled ? '사용 중' : '미사용'}으로 변경했습니다.`);
		} catch (error) {
			modelPreferences = previousPreferences;
			defaultTtsModelId = previousDefaultTtsModelId;
			showNotice('error', error instanceof Error ? error.message : String(error));
		}
	}

	async function setDefaultTtsModel(modelId: string) {
		const model = models.find((item) => item.id === modelId);
		if (!model || !model.capabilities.tts) return;
		if (model.status === 'unavailable') {
			showNotice('info', '설정이 필요한 모델은 대표 TTS 모델로 지정할 수 없습니다.');
			return;
		}
		const nextPreferences = {
			...modelPreferences,
			[modelId]: {
				id: modelId,
				enabled: true,
				order: modelPreferences[modelId]?.order ?? defaultOrder(model, models.findIndex((item) => item.id === modelId))
			}
		};
		const previousPreferences = modelPreferences;
		const previousDefaultTtsModelId = defaultTtsModelId;
		modelPreferences = nextPreferences;
		defaultTtsModelId = modelId;
		try {
			await saveModelPreferences(nextPreferences, modelId);
			showNotice('success', `${model.label}을 대표 TTS 모델로 설정했습니다.`);
		} catch (error) {
			modelPreferences = previousPreferences;
			defaultTtsModelId = previousDefaultTtsModelId;
			showNotice('error', error instanceof Error ? error.message : String(error));
		}
	}

	async function moveModel(modelId: string, direction: 'up' | 'down') {
		const sorted = sortModels(models, modelPreferences);
		const currentIndex = sorted.findIndex((model) => model.id === modelId);
		const targetIndex = direction === 'up' ? currentIndex - 1 : currentIndex + 1;
		if (currentIndex < 0 || targetIndex < 0 || targetIndex >= sorted.length) return;

		const current = sorted[currentIndex];
		const target = sorted[targetIndex];
		const currentOrder = modelPreferences[current.id]?.order ?? defaultOrder(current, currentIndex);
		const targetOrder = modelPreferences[target.id]?.order ?? defaultOrder(target, targetIndex);
		const nextPreferences = {
			...modelPreferences,
			[current.id]: {
				id: current.id,
				enabled: isModelEnabled(current.id),
				order: targetOrder
			},
			[target.id]: {
				id: target.id,
				enabled: isModelEnabled(target.id),
				order: currentOrder
			}
		};

		const previousPreferences = modelPreferences;
		modelPreferences = nextPreferences;
		try {
			await saveModelPreferences(nextPreferences, defaultTtsModelId);
		} catch (error) {
			modelPreferences = previousPreferences;
			showNotice('error', error instanceof Error ? error.message : String(error));
		}
	}

	function showNotice(type: StudioNotice['type'], text: string) {
		notice = { type, text };
		window.setTimeout(() => {
			if (notice?.text === text) notice = null;
		}, 5000);
	}

	async function refreshAll(options: { silent?: boolean } = {}) {
		if (!options.silent) loading = true;
		refreshing = true;
		try {
			const [healthRes, modelsRes, voicesRes, contentsRes] = await Promise.all([
				apiFetch('/api/health'),
				apiFetch('/api/models'),
				apiFetch('/api/voices'),
				apiFetch('/api/contents')
			]);
			health = await healthRes.json();
			const modelsPayload: ModelListResponse = await modelsRes.json();
			models = modelsPayload.models ?? [];
			normalizeModelPreferences(models, modelsPayload.model_preferences ?? {}, modelsPayload.default_tts_model);
			voices = await voicesRes.json();
			contents = await contentsRes.json();
			if (!selectedVoiceId && voices.length) selectedVoiceId = voices[0].id;
			lastRefreshedAt = new Date().toLocaleTimeString('ko-KR');
		} catch (error) {
			showNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			loading = false;
			refreshing = false;
		}
	}

	async function refreshVoices() {
		const voicesRes = await apiFetch('/api/voices');
		voices = await voicesRes.json();
		if (!selectedVoiceId && voices.length) selectedVoiceId = voices[0].id;
	}

	async function deleteVoice(id: string) {
		try {
			await apiFetch(`/api/voices/${id}`, { method: 'DELETE' });
			voices = voices.filter((voice) => voice.id !== id);
			if (selectedVoiceId === id) selectedVoiceId = voices[0]?.id ?? '';
			showNotice('success', '목소리를 삭제했습니다.');
		} catch (error) {
			showNotice('error', error instanceof Error ? error.message : String(error));
		}
	}

	function navigate(key: MenuKey) {
		const isSameMenu = active === key;
		active = key;
		window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0 }));
		if (key === 'voices') {
			if (isSameMenu) creatingVoice = false;
		} else {
			creatingVoice = false;
		}
		if (isSameMenu) navigationResetKey += 1;
	}

	function startVoiceCreate() {
		active = 'voices';
		creatingVoice = true;
		createSession += 1;
	}

	async function onVoiceSaved(voice: VoiceProfile) {
		voices = [voice, ...voices.filter((item) => item.id !== voice.id)];
		selectedVoiceId = voice.id;
		active = 'voices';
		creatingVoice = false;
		try {
			await refreshVoices();
			selectedVoiceId = voice.id;
		} catch (error) {
			showNotice(
				'info',
				`저장은 완료됐지만 목록 재조회가 실패했습니다. 새로고침하면 표시됩니다. ${error instanceof Error ? error.message : String(error)}`
			);
		}
	}

	function updateVoice(voice: VoiceProfile) {
		voices = voices.map((item) => (item.id === voice.id ? voice : item));
		if (!selectedVoiceId) selectedVoiceId = voice.id;
	}

	function saveContentState(content: ContentItem) {
		contents = [content, ...contents.filter((item) => item.id !== content.id)];
	}

	function deleteContentState(id: string) {
		contents = contents.filter((item) => item.id !== id);
	}
</script>

<svelte:head>
	<title>Clone Voice Studio · AI 음성 제작 스튜디오</title>
	<meta
		name="description"
		content="목소리 등록, TTS, STT, 스토리 오디오, 보이스 체인저를 운영하는 음성 제작 스튜디오"
	/>
</svelte:head>

<AppShell
	{active}
	onNavigate={navigate}
>
	{#snippet children()}
		{#if notice}
			<NoticePanel {notice} />
		{/if}
		{#if notice?.type === 'error' || apiLogs.some((log) => !log.ok)}
			<ApiLogPanel logs={apiLogs} open={notice?.type === 'error'} />
		{/if}
		{#if loading}
			<section class="surface loading-panel">스튜디오 상태를 불러오는 중입니다.</section>
		{:else if active === 'home'}
			<HomeDashboard
				voicesCount={voices.length}
				models={activeModels}
				{contents}
				{health}
				{lastRefreshedAt}
				{refreshing}
				onCreateVoice={startVoiceCreate}
				onNavigateTts={() => navigate('tts')}
				onNavigateStt={() => navigate('stt')}
				onNavigateChanger={() => navigate('changer')}
				onRefresh={() => refreshAll({ silent: true })}
			/>
		{:else if active === 'voices'}
			{#if creatingVoice}
				{#key createSession}
					<VoiceCreateEditor onSaved={onVoiceSaved} onCancel={() => (creatingVoice = false)} onNotice={showNotice} />
				{/key}
			{:else}
				<VoiceLibrary
					{voices}
					{selectedVoiceId}
					onSelect={(id) => (selectedVoiceId = id)}
					onCreate={startVoiceCreate}
					onDelete={deleteVoice}
					onUpdate={updateVoice}
					onNotice={showNotice}
				/>
			{/if}
		{:else if active === 'tts'}
			{#key `tts-${navigationResetKey}`}
				<TextToSpeechWorkspace
					{voices}
					models={activeModels}
					{defaultTtsModelId}
					{contents}
					onContentSaved={saveContentState}
					onContentDeleted={deleteContentState}
					onNotice={showNotice}
				/>
			{/key}
		{:else if active === 'story'}
			{#key `story-${navigationResetKey}`}
				<StoryStudioWorkspace {voices} models={activeModels} {defaultTtsModelId} onNotice={showNotice} />
			{/key}
		{:else if active === 'stt'}
			<SpeechToTextWorkspace onNotice={showNotice} />
		{:else if active === 'changer'}
			{#key `changer-${navigationResetKey}`}
				<VoiceChangerWorkspace {voices} models={activeModels} onNotice={showNotice} />
			{/key}
		{:else if active === 'settings'}
			<ModelSettingsPanel
				models={orderedModels}
				{modelPreferences}
				{defaultTtsModelId}
				onReload={refreshAll}
				onNotice={showNotice}
				onToggleModel={setModelEnabled}
				onMakeDefaultTts={setDefaultTtsModel}
				onMoveModel={moveModel}
			/>
		{/if}
	{/snippet}
</AppShell>
