<script lang="ts">
	import { onMount, tick } from 'svelte';
	import AppShell from '$lib/components/AppShell.svelte';
	import AssetLibraryWorkspace from '$lib/components/AssetLibraryWorkspace.svelte';
	import HomeDashboard from '$lib/components/app/HomeDashboard.svelte';
	import NoticePanel from '$lib/components/app/NoticePanel.svelte';
	import GenerationQueueStatus from '$lib/components/app/GenerationQueueStatus.svelte';
	import ModelSettingsPanel from '$lib/components/ModelSettingsPanel.svelte';
	import SpeechToTextWorkspace from '$lib/components/SpeechToTextWorkspace.svelte';
	import SoundEffectWorkspace from '$lib/components/SoundEffectWorkspace.svelte';
	import StoryStudioWorkspace from '$lib/components/StoryStudioWorkspace.svelte';
	import TextToSpeechWorkspace from '$lib/components/TextToSpeechWorkspace.svelte';
	import VoiceChangerWorkspace from '$lib/components/VoiceChangerWorkspace.svelte';
	import VoiceCreateEditor from '$lib/components/VoiceCreateEditor.svelte';
	import VoiceLibrary from '$lib/components/VoiceLibrary.svelte';
	import { apiFetch } from '$lib/studio/api';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import { defaultStudioPreferences, type StudioPreferences, type StudioPreferencesResponse } from '$lib/studio/preferences';
	import { voiceSections } from '$lib/components/app/navigation';
	import { domainMeta } from '$lib/studio/model-domains';
	import { isEnabled, normalizeModelState, sortModels, withDefaultModel, withModelEnabled, withModelMoved, type ModelDefaults, type ModelState } from '$lib/studio/models';
	import type { TtsEntry } from '$lib/studio/production';
	import type {
		ContentItem,
		MenuKey,
		ModelListResponse,
		ModelDomain,
		ModelPreferencesResponse,
		RuntimeHealth,
		RuntimeModelStatus,
		StudioNotice,
		VoiceProfile
	} from '$lib/studio/types';

	const PREFERRED_VOICE_KEY = 'clonevoice.preferredVoice.v1';

	let active = $state<MenuKey>('tts');
	let studioPreferences = $state<StudioPreferences>({ ...defaultStudioPreferences });
	let voices = $state<VoiceProfile[]>([]);
	let contents = $state<ContentItem[]>([]);
	let models = $state<RuntimeModelStatus[]>([]);
	let health = $state<RuntimeHealth | null>(null);
	let selectedVoiceId = $state('');
	let notice = $state<StudioNotice | null>(null);
	let loading = $state(true);
	let preferencesLoaded = $state(false);
	const ready = $derived(!loading && preferencesLoaded);
	let refreshing = $state(false);
	let lastRefreshedAt = $state('');
	let creatingVoice = $state(false);
	let createSession = $state(0);
	let navigationResetKey = $state(0);
	let modelState = $state<ModelState>({ preferences: {}, defaults: {} });
	let ttsEntry = $state<TtsEntry | null>(null);
	let startWithVoice = $state(false);
	let initialMenuPending = true;

	let orderedModels = $derived(sortModels(models, modelState.preferences));
	let activeModels = $derived(orderedModels.filter((model) => isEnabled(modelState, model.id)));
	let defaultTtsModelId = $derived(modelState.defaults.voice ?? 'voxcpm');
	let defaultVcModelId = $derived(modelState.defaults.cover ?? 'soulx-singer');
	let defaultSfxModelId = $derived(modelState.defaults.sfx ?? 'stable-audio-sfx');

	onMount(() => {
		try { selectedVoiceId = localStorage.getItem(PREFERRED_VOICE_KEY) ?? ''; } catch { /* Storage may be unavailable; selection still works for this session. */ }
		void apiFetch('/api/studio/preferences').then((response) => response.json()).then((payload: StudioPreferencesResponse) => {
			studioPreferences = payload.preferences;
			if (initialMenuPending) active = payload.preferences.start_menu;
			initialMenuPending = false;
		}).catch(() => { /* Keep core defaults when preferences cannot be loaded. */ }).finally(() => { preferencesLoaded = true; });
		void refreshAll();
	});

	async function saveStudioPreferences(value: StudioPreferences) {
		const response = await apiFetch('/api/studio/preferences', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
		const payload: StudioPreferencesResponse = await response.json();
		studioPreferences = payload.preferences;
	}

	function applyServerModelPreferences(payload: ModelPreferencesResponse) {
		modelState = normalizeModelState(models, payload.model_preferences ?? {}, serverDefaults(payload), modelState.defaults);
	}

	function serverDefaults(payload: ModelPreferencesResponse): ModelDefaults {
		return {
			...payload.default_models,
			voice: payload.default_models?.voice ?? payload.default_tts_model,
			cover: payload.default_models?.cover ?? payload.default_vc_model
		};
	}

	/** Applies a change optimistically and rolls back when the server rejects it. */
	async function commitModelState(next: ModelState, onSuccess?: () => void) {
		const previous = modelState;
		modelState = next;
		try {
			const response = await apiFetch('/api/models/preferences', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					model_preferences: next.preferences,
					default_models: next.defaults,
					default_tts_model: next.defaults.voice,
					default_vc_model: next.defaults.cover
				})
			});
			applyServerModelPreferences(await response.json());
			onSuccess?.();
		} catch (error) {
			modelState = previous;
			showNotice('error', error instanceof Error ? error.message : String(error));
		}
	}

	async function setModelEnabled(modelId: string, enabled: boolean) {
		const model = models.find((item) => item.id === modelId);
		if (!model) return;
		const change = withModelEnabled(models, modelState, modelId, enabled);
		if (!change.ok) {
			showNotice('info', t(change.reason === 'cover' ? 'models.notice.keepOne.cover' : 'models.notice.keepOne.voice'));
			return;
		}
		await commitModelState(change.state, () => showNotice('success', t(enabled ? 'models.notice.enabled' : 'models.notice.disabled', { name: model.label })));
	}

	async function setDefaultModel(domain: ModelDomain, modelId: string) {
		const model = models.find((item) => item.id === modelId);
		if (!model) return;
		const next = withDefaultModel(models, modelState, domain, modelId);
		if (!next) {
			if (model.status === 'unavailable') showNotice('info', t('models.notice.needsSetup'));
			return;
		}
		await commitModelState(next, () => showNotice('success', t('models.notice.defaultSet', { name: model.label, domain: t(domainMeta(domain).label) })));
	}

	async function moveModel(domain: ModelDomain, modelId: string, direction: 'up' | 'down') {
		const next = withModelMoved(models, modelState, domain, modelId, direction);
		if (next) await commitModelState(next);
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
			applyServerModelPreferences(modelsPayload);
			voices = await voicesRes.json();
			contents = await contentsRes.json();
			if (selectedVoiceId && !voices.some((voice) => voice.id === selectedVoiceId)) selectVoice('');
			lastRefreshedAt = new Date().toLocaleTimeString(i18n.intl);
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
		if (selectedVoiceId && !voices.some((voice) => voice.id === selectedVoiceId)) selectVoice('');
	}

	async function deleteVoice(id: string) {
		try {
			await apiFetch(`/api/voices/${id}`, { method: 'DELETE' });
			voices = voices.filter((voice) => voice.id !== id);
			if (selectedVoiceId === id) selectVoice('');
			showNotice('success', t('app.voiceDeleted'));
		} catch (error) {
			showNotice('error', error instanceof Error ? error.message : String(error));
		}
	}

	function navigate(key: MenuKey) {
		initialMenuPending = false;
		startWithVoice = false;
		if (key === 'tts') ttsEntry = null;
		const isSameMenu = active === key;
		active = key;
		void tick().then(() => {
			window.requestAnimationFrame(() => {
				window.scrollTo({ top: 0, left: 0 });
				document.querySelector<HTMLElement>('[data-route-heading]')?.focus({ preventScroll: true });
			});
		});
		if (key === 'voices') {
			if (isSameMenu) creatingVoice = false;
		} else {
			creatingVoice = false;
		}
		if (isSameMenu) navigationResetKey += 1;
	}

	function openTts(entry: TtsEntry) {
		navigate('tts');
		ttsEntry = entry;
	}

	async function openQueuedContent(id: string) {
		try {
			const response = await apiFetch(`/api/contents/${id}`);
			const content: ContentItem = await response.json();
			saveContentState(content);
			openTts({ contentId: id });
		} catch (error) { showNotice('error', error instanceof Error ? error.message : String(error)); }
	}

	function selectVoice(id: string) {
		selectedVoiceId = voices.some((voice) => voice.id === id) ? id : '';
		try { localStorage.setItem(PREFERRED_VOICE_KEY, selectedVoiceId); }
		catch { showNotice('info', t('app.voiceNotSaved')); }
	}

	function useVoice(id: string, target: 'tts' | 'story' | 'changer') {
		selectVoice(id);
		if (target === 'tts') openTts({ newDraft: true });
		else { navigate(target); startWithVoice = true; }
	}

	function startVoiceCreate() {
		initialMenuPending = false;
		active = 'voices';
		creatingVoice = true;
		createSession += 1;
	}

	async function onVoiceSaved(voice: VoiceProfile) {
		voices = [voice, ...voices.filter((item) => item.id !== voice.id)];
		selectVoice(voice.id);
		active = 'voices';
		creatingVoice = false;
		try {
			await refreshVoices();
			selectVoice(voice.id);
		} catch (error) {
			showNotice(
				'info',
				t('app.reloadFail', { error: error instanceof Error ? error.message : String(error) })
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

<AppShell
	{active}
	{ready}
	showAuxiliaryTools={studioPreferences.show_auxiliary_tools}
	onNavigate={navigate}
>
	{#snippet children()}
		{#if notice}
			<NoticePanel {notice} />
		{/if}
		{#if ready}<GenerationQueueStatus {contents} onOpen={openQueuedContent} />{/if}
		{#if ready && (active === 'tts' || active === 'voices')}
			<nav class="voice-section-nav" aria-label={t('nav.voice.aria')}>
				{#each voiceSections as section}
					<button class:active={active === section.key && !creatingVoice} aria-current={active === section.key && !creatingVoice ? 'page' : undefined} onclick={() => navigate(section.key)}>{t(section.labelKey)}</button>
				{/each}
				<button class:active={creatingVoice} onclick={startVoiceCreate}>{t('nav.voice.register')}</button>
			</nav>
		{/if}
		{#if !ready}
			<section class="surface loading-panel">{t('app.loading')}</section>
		{:else if active === 'home'}
			<HomeDashboard
				{voices}
				{selectedVoiceId}
				voicesCount={voices.length}
				models={activeModels}
				{contents}
				{health}
				{lastRefreshedAt}
				{refreshing}
				onCreateVoice={startVoiceCreate}
				onNavigateTts={() => navigate('tts')}
				onCreateTts={() => openTts({ newDraft: true })}
				onOpenContent={(content) => openTts({ contentId: content.id })}
				onUseTemplate={(template) => openTts({ templateId: template.id })}
				onOpenSettings={() => navigate('settings')}
				onNavigateStory={() => navigate('story')}
				onNavigateStt={() => navigate('stt')}
				onNavigateChanger={() => navigate('changer')}
				onNavigateSfx={() => navigate('sfx')}
				onRefresh={() => refreshAll({ silent: true })}
				onSelectVoice={selectVoice}
				onUseVoice={useVoice}
			/>
		{:else if active === 'voices'}
			{#if creatingVoice}
				{#key createSession}
					<VoiceCreateEditor defaultSttProvider={studioPreferences.stt_provider} onSaved={onVoiceSaved} onCancel={() => (creatingVoice = false)} onNotice={showNotice} />
				{/key}
			{:else}
				<VoiceLibrary
					{voices}
					{selectedVoiceId}
					onSelect={selectVoice}
					onUse={useVoice}
					canUseCover={activeModels.some((model) => model.status === 'available' && model.capabilities.voice_conversion)}
					onCreate={startVoiceCreate}
					onDelete={deleteVoice}
					onUpdate={updateVoice}
					onNotice={showNotice}
				/>
			{/if}
		{:else if active === 'files'}
			{#key `files-${navigationResetKey}`}
				<AssetLibraryWorkspace {voices} onNavigate={navigate} onNotice={showNotice} />
			{/key}
		{:else if active === 'tts'}
			{#key `tts-${navigationResetKey}`}
				<TextToSpeechWorkspace
					entry={ttsEntry}
					{voices}
					models={activeModels}
					{defaultTtsModelId}
					defaultVoiceId={selectedVoiceId}
					{contents}
					defaultSourceLanguage={studioPreferences.source_language}
					onCreateVoice={startVoiceCreate}
					onContentSaved={saveContentState}
					onContentDeleted={deleteContentState}
					onNotice={showNotice}
				/>
			{/key}
		{:else if active === 'story'}
			{#key `story-${navigationResetKey}`}
				<StoryStudioWorkspace {voices} models={activeModels} {defaultTtsModelId} defaultSttProvider={studioPreferences.stt_provider} defaultVoiceId={selectedVoiceId} {startWithVoice} onNotice={showNotice} />
			{/key}
		{:else if active === 'sfx'}
			<SoundEffectWorkspace models={activeModels} defaultModelId={defaultSfxModelId} onNotice={showNotice} />
		{:else if active === 'stt'}
			<SpeechToTextWorkspace defaultSttProvider={studioPreferences.stt_provider} onNotice={showNotice} />
		{:else if active === 'changer'}
			{#key `changer-${navigationResetKey}`}
				<VoiceChangerWorkspace {voices} models={activeModels} {defaultVcModelId} defaultSttProvider={studioPreferences.stt_provider} defaultVoiceId={selectedVoiceId} {startWithVoice} onNotice={showNotice} />
			{/key}
		{:else if active === 'settings'}
			<ModelSettingsPanel
				{studioPreferences}
				onSaveStudioPreferences={saveStudioPreferences}
				models={orderedModels}
				modelPreferences={modelState.preferences}
				defaultModels={modelState.defaults}
				onReload={refreshAll}
				onNotice={showNotice}
				onToggleModel={setModelEnabled}
				onMakeDefault={setDefaultModel}
				onMoveModel={moveModel}
			/>
		{/if}
	{/snippet}
</AppShell>
<style>
.voice-section-nav { display: flex; flex-wrap: wrap; gap: 5px; padding: 0 0 18px; }
.voice-section-nav button { padding: 9px 18px; min-height: 42px; border: 1px solid transparent; border-radius: 8px; color: var(--muted-foreground); font-weight: 600; font-size: 13px; }
.voice-section-nav button.active { color: var(--accent-hover); background: var(--card); border-color: var(--border); }
.voice-section-nav button:hover { background: var(--accent-soft); }
@media (max-width: 700px) {
	:global(.story-title-row) { min-width: 0; width: 100%; }
	:global(.story-title-row > .story-title-input), :global(.story-title-row > .button-row) { width: 100%; min-width: 0; max-width: 100%; }
	:global(.story-title-row > .button-row) { flex-wrap: wrap; }
}
</style>
