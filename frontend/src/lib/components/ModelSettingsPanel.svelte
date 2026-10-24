<script lang="ts">
	import { RefreshCw } from '@lucide/svelte';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Tabs from '$lib/components/ui/tabs';
	import { t } from '$lib/i18n/index.svelte';
	import { apiFetch } from '$lib/studio/api';
	import { modelDomainMeta } from '$lib/studio/model-domains';
	import { allModelsFor, isEnabled, type ModelDefaults } from '$lib/studio/models';
	import type { StudioPreferences } from '$lib/studio/preferences';
	import type { ModelDomain, ModelPreference, RuntimeModelStatus } from '$lib/studio/types';
	import AiModelManager from './app/AiModelManager.svelte';
	import AiPromptManager from './app/AiPromptManager.svelte';
	import ModelDomainSection from './model-picker/ModelDomainSection.svelte';
	import StudioPreferencesPanel from './StudioPreferencesPanel.svelte';

	let {
		models,
		studioPreferences,
		onSaveStudioPreferences,
		modelPreferences = {},
		defaultModels = {},
		onReload,
		onNotice,
		onToggleModel,
		onMakeDefault,
		onMoveModel
	}: {
		models: RuntimeModelStatus[];
		studioPreferences: StudioPreferences;
		onSaveStudioPreferences: (value: StudioPreferences) => Promise<void>;
		modelPreferences?: Record<string, ModelPreference>;
		defaultModels?: ModelDefaults;
		onReload: () => Promise<void>;
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
		onToggleModel: (modelId: string, enabled: boolean) => void | Promise<void>;
		onMakeDefault: (domain: ModelDomain, modelId: string) => void | Promise<void>;
		onMoveModel: (domain: ModelDomain, modelId: string, direction: 'up' | 'down') => void | Promise<void>;
	} = $props();

	let tab = $state('general');
	let loadingModel = $state('');
	let aiCatalogRevision = $state(0);
	const modelState = $derived({ preferences: modelPreferences, defaults: defaultModels });

	async function preload(model: RuntimeModelStatus) {
		loadingModel = model.id;
		try {
			await apiFetch(`/api/models/${model.id}/preload`, { method: 'POST' });
			onNotice('success', t('models.notice.preloaded', { name: model.label }));
			await onReload();
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			loadingModel = '';
		}
	}
</script>

<Tabs.Root bind:value={tab} class="max-w-[920px] gap-6">
	<Tabs.List aria-label={t('settings.tab.aria')}>
		<Tabs.Trigger value="general">{t('settings.tab.general')}</Tabs.Trigger>
		<Tabs.Trigger value="models">{t('settings.tab.models')}</Tabs.Trigger>
		<Tabs.Trigger value="ai">{t('settings.tab.ai')}</Tabs.Trigger>
	</Tabs.List>

	<!-- Panels stay mounted so an unsaved connection form or a running status check survives switching tabs. -->
	<div role="tabpanel" hidden={tab !== 'general'}>
		<StudioPreferencesPanel preferences={studioPreferences} onSave={onSaveStudioPreferences} {onNotice} refreshRevision={aiCatalogRevision} />
	</div>

	<div role="tabpanel" class="grid gap-7" hidden={tab !== 'models'}>
		<header class="flex items-center gap-1">
			<h2 class="text-lg font-semibold">{t('models.title')}</h2>
			<HelpPopover label={t('models.title')} text={t('models.titleHelp')} />
			<Button variant="ghost" size="icon" class="ml-auto" onclick={onReload} aria-label={t('models.reload')}><RefreshCw size={16} aria-hidden="true" /></Button>
		</header>
		{#each modelDomainMeta as meta (meta.domain)}
			<ModelDomainSection
				{meta}
				models={allModelsFor(models, modelState, meta.domain)}
				defaultId={defaultModels[meta.domain] ?? ''}
				isEnabled={(modelId) => isEnabled(modelState, modelId)}
				loadingId={loadingModel}
				onToggle={onToggleModel}
				onMakeDefault={(modelId) => onMakeDefault(meta.domain, modelId)}
				onMove={(modelId, direction) => onMoveModel(meta.domain, modelId, direction)}
				onPreload={preload}
			/>
		{/each}
	</div>

	<div role="tabpanel" class="grid gap-8" hidden={tab !== 'ai'}>
		<AiModelManager {onNotice} onChanged={() => (aiCatalogRevision += 1)} showTranslation={false} />
		<AiPromptManager {onNotice} />
	</div>
</Tabs.Root>
