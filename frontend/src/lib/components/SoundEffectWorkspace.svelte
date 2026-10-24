<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { ArrowLeft, Ellipsis, Loader2, Plus, RefreshCw, X } from '@lucide/svelte';
  import { Badge } from '$lib/components/ui/badge';
  import { Button } from '$lib/components/ui/button';
  import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
  import { t } from '$lib/i18n/index.svelte';
  import { apiFetch, formatDate } from '$lib/studio/api';
  import { modelsFor, type ModelState } from '$lib/studio/models';
  import ModelPicker from './model-picker/ModelPicker.svelte';
  import SoundResultList from './SoundResultList.svelte';
  import HelpPopover from './HelpPopover.svelte';
  import ProductionAssistPanel from './app/ProductionAssistPanel.svelte';
  import type { ProductionAssistResponse } from '$lib/studio/ai-prompts';
  import type { RuntimeModelStatus, SoundEffectResult } from '$lib/studio/types';
  import {
    ASSET_CATEGORIES, PROJECT_CATEGORIES, SOUND_STARTER_PACKS, assetCategoryLabel,
    copySoundProject, legacySoundProject, makeSoundAsset, makeSoundProject, markLegacySoundImported,
    mergeSoundProject, projectCategoryLabel, projectContentKey, readLegacySoundResults,
    readSoundRecoveries, readUnlinkedSounds, removeSoundRecovery, saveSoundRecovery, saveUnlinkedSounds, soundId,
    type SoundAsset, type SoundAssetCategory, type SoundProject, type SoundProjectCategory,
    type SoundProjectRecovery, type SoundRecoveryResult, type SoundStarterPack, type SoundTemplate,
  } from '$lib/studio/sound-projects';

  let { models, defaultModelId = '', onNotice }: {
    models: RuntimeModelStatus[];
    defaultModelId?: string;
    onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
  } = $props();

  let projects = $state<SoundProject[]>([]);
  let draft = $state<SoundProject | null>(null);
  let baseline = $state<SoundProject | null>(null);
  let selectedId = $state('');
  let loading = $state(true);
  let saving = $state(false);
  let generation = $state<{ project_id: string; asset_id: string; title: string } | null>(null);
  let feedback = $state<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);
  let recoveryWarning = $state('');
  let recoveries = $state<SoundProjectRecovery[]>([]);
  let recoveryConflict = $state<SoundProjectRecovery | null>(null);
  let unlinked = $state<SoundRecoveryResult[]>([]);
  let legacyResults = $state<SoundEffectResult[]>([]);
  let newTitle = $state('');
  let newCategory = $state<SoundProjectCategory>('game');
  let examplePack = $state(SOUND_STARTER_PACKS[0].id);
  let showExamples = $state(false);

  const selected = $derived(draft?.assets.find((asset) => asset.id === selectedId) ?? null);
  const dirty = $derived(Boolean(draft && baseline && projectContentKey(draft) !== projectContentKey(baseline)));
  const card = 'border-border bg-card rounded-xl border';
  let modelId = $state('');
  const sfxModels = $derived(models.filter((model) => model.capabilities.sound_effect_generation));
  const engine = $derived(sfxModels.find((model) => model.id === modelId) ?? sfxModels.find((model) => model.id === defaultModelId) ?? sfxModels[0]);
  const engineReady = $derived(Boolean(engine?.enabled && engine.status === 'available'));
  const examples = $derived(SOUND_STARTER_PACKS.find((pack) => pack.id === examplePack) ?? SOUND_STARTER_PACKS[0]);
  const generatingSelected = $derived(generation?.project_id === draft?.id && generation?.asset_id === selectedId);
  const totalResults = $derived(draft?.assets.reduce((total, asset) => total + asset.results.length, 0) ?? 0);

  function notice(type: 'success' | 'error' | 'info', text: string) {
    feedback = { type, text };
    onNotice(type, text);
  }
  function errorText(error: unknown): string { return error instanceof Error ? error.message : t('sound.requestFailed'); }
  function replaceProject(project: SoundProject) {
    if (projects.some((item) => item.id === project.id && item.revision > project.revision)) return;
    projects = [project, ...projects.filter((item) => item.id !== project.id)]
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at));
  }
  function refreshRecoveries() { recoveries = readSoundRecoveries(); }
  function backup(project: SoundProject, base: SoundProject): boolean {
    try { saveSoundRecovery(project, base); recoveryWarning = ''; return true; }
    catch { recoveryWarning = t('sound.backupUnavailable'); return false; }
  }
  function clearBackup(id: string) {
    try { removeSoundRecovery(id); } catch { /* Server save already succeeded. */ }
    refreshRecoveries();
  }
  function changeProject(change: Partial<SoundProject>) {
    if (!draft || !baseline || saving) return;
    const next = { ...draft, ...change, updated_at: new Date().toISOString() };
    backup(next, baseline);
    draft = next;
  }
  function changeAsset(change: Partial<SoundAsset>) {
    if (!draft || !selected || saving) return;
    const id = selected.id;
    changeProject({ assets: draft.assets.map((asset) => asset.id === id ? { ...asset, ...change, updated_at: new Date().toISOString() } : asset) });
  }
  function applySoundRecommendation(result: ProductionAssistResponse) {
    if (!draft || !selected || saving || generation) throw new Error(t('sound.applyState'));
    if (result.kind !== 'sound_effect' || !result.generation_prompt.trim() || result.generation_prompt.length > 2000) throw new Error(t('sound.applyLength'));
    changeAsset({ prompt: result.generation_prompt });
  }
  function selectAsset(id: string) { selectedId = id; showExamples = false; }
  function addAsset(template?: SoundTemplate) {
    if (!draft || saving) return;
    if (draft.assets.length >= 300) { notice('error', t('sound.max300')); return; }
    const asset = makeSoundAsset(template);
    changeProject({ assets: [...draft.assets, asset] });
    selectedId = asset.id;
    showExamples = !template;
  }

  async function loadProjects() {
    loading = true;
    try {
      const response = await apiFetch('/api/sound-projects');
      const data = await response.json() as { projects: SoundProject[] };
      projects = data.projects;
    } catch (error) { notice('error', t('sound.loadFail', { error: errorText(error) })); }
    finally { loading = false; }
  }
  async function focusProjectStart(projectId: string) {
    await tick();
    const titleField = document.getElementById('sound-project-title');
    if (!titleField || draft?.id !== projectId) return;
    titleField.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  async function openProject(project: SoundProject) {
    if (saving || loading) return;
    loading = true;
    try {
      const response = await apiFetch(`/api/sound-projects/${project.id}`);
      const current = await response.json() as SoundProject;
      replaceProject(current);
      baseline = copySoundProject(current); draft = copySoundProject(current);
      selectedId = current.assets[0]?.id ?? ''; showExamples = false; feedback = null;
    } catch (error) { notice('error', errorText(error)); }
    finally { loading = false; }
    if (draft?.id === project.id) await focusProjectStart(project.id);
  }
  function backToProjects() {
    if (saving) return;
    if (draft && baseline && dirty) {
      const stored = backup(draft, baseline);
      if (!stored && !window.confirm(t('sound.confirmLeave'))) return;
      if (stored) notice('info', t('sound.keptUnsaved'));
    }
    draft = null; baseline = null; selectedId = ''; refreshRecoveries();
  }
  async function createProject(pack?: SoundStarterPack) {
    if (saving || loading) return;
    const title = pack ? t('sound.packProject', { title: pack.title }) : newTitle.trim();
    if (!title) { notice('error', t('sound.needProjectName')); return; }
    saving = true;
    try {
      const project = makeSoundProject(title, pack?.category ?? newCategory, pack);
      const response = await apiFetch(`/api/sound-projects/${project.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(project) });
      const saved = await response.json() as SoundProject;
      replaceProject(saved); baseline = copySoundProject(saved); draft = copySoundProject(saved);
      selectedId = saved.assets[0]?.id ?? ''; newTitle = ''; feedback = null;
      notice('success', pack ? t('sound.createdFromPack', { title: pack.title, count: pack.examples.length }) : t('sound.created'));
    } catch (error) { notice('error', errorText(error)); }
    finally { saving = false; }
    if (draft) await focusProjectStart(draft.id);
  }
  async function persistDraft(): Promise<SoundProject | null> {
    if (!draft || !baseline || saving) return null;
    if (!draft.title.trim()) { notice('error', t('sound.needProjectName')); return null; }
    if (draft.assets.some((asset) => !asset.title.trim())) { notice('error', t('sound.needAssetNames')); return null; }
    const submitted = copySoundProject(draft);
    const backedUp = backup(submitted, baseline);
    saving = true;
    try {
      const response = await apiFetch(`/api/sound-projects/${submitted.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(submitted) });
      const saved = await response.json() as SoundProject;
      replaceProject(saved); baseline = copySoundProject(saved); draft = copySoundProject(saved); clearBackup(saved.id);
      return saved;
    } catch (error) { notice('error', t('sound.saveFail', { hint: backedUp ? t('sound.saveFail.kept') : t('sound.saveFail.again'), error: errorText(error) })); return null; }
    finally { saving = false; }
  }
  async function saveProject() {
    if (await persistDraft()) notice('success', t('sound.saved'));
  }
  async function reloadSavedProject() {
    if (!draft || saving) return;
    if (dirty && !window.confirm(t('sound.confirmReload'))) return;
    if (baseline && dirty) backup(draft, baseline);
    await openProject(draft);
    refreshRecoveries();
  }
  async function deleteProject() {
    if (!draft || !baseline || saving) return;
    if (!window.confirm(t('sound.confirmDeleteProject', { title: draft.title }))) return;
    const id = draft.id; const revision = baseline.revision;
    saving = true;
    try {
      await apiFetch(`/api/sound-projects/${id}?revision=${revision}`, { method: 'DELETE' });
      projects = projects.filter((project) => project.id !== id); clearBackup(id);
      draft = null; baseline = null; selectedId = '';
      notice('success', t('sound.projectDeleted'));
    } catch (error) { notice('error', errorText(error)); }
    finally { saving = false; }
  }
  function deleteAsset() {
    if (!draft || !selected || saving) return;
    if (!window.confirm(t('sound.confirmRemoveAsset', { title: selected.title }))) return;
    const assets = draft.assets.filter((asset) => asset.id !== selectedId);
    changeProject({ assets }); selectedId = assets[0]?.id ?? '';
    notice('info', t('sound.removedPending'));
  }
  function removeVersion(id: string) {
    if (!selected || saving || !window.confirm(t('sound.confirmRemoveVersion'))) return;
    changeAsset({ results: selected.results.filter((result) => result.id !== id) });
    notice('info', t('sound.removedVersion'));
  }
  function reuseResult(result: SoundEffectResult) {
    if (!selected || saving) return;
    changeAsset({ prompt: result.prompt, negative_prompt: result.negative_prompt,
      duration_seconds: Math.min(15, Math.max(0.5, result.duration_seconds)), auto_duration: false,
      seed: result.seed >= 0 && result.seed <= 2147483643 ? result.seed : null });
    notice('info', t('sound.reused'));
  }
  function similarAsset(result?: SoundEffectResult) {
    if (!draft || !selected || saving) return;
    if (draft.assets.length >= 300) { notice('error', t('sound.max300short')); return; }
    const now = new Date().toISOString();
    const asset: SoundAsset = {
      ...selected, id: soundId(), title: t('sound.variantTitle', { title: selected.title.slice(0, 152) }), seed: null, results: [],
      prompt: result?.prompt ?? selected.prompt, negative_prompt: result?.negative_prompt ?? selected.negative_prompt,
      duration_seconds: result ? Math.min(15, Math.max(0.5, result.duration_seconds)) : selected.duration_seconds,
      created_at: now, updated_at: now,
    };
    changeProject({ assets: [...draft.assets, asset] }); selectedId = asset.id;
    notice('info', t('sound.similarAdded'));
  }
  function keepUnlinked(item: SoundRecoveryResult) {
    unlinked = [item, ...unlinked.filter((entry) => entry.id !== item.id)].slice(0, 16);
    try { saveUnlinkedSounds(unlinked); } catch { recoveryWarning = t('sound.keepUnlinkedFail'); }
  }
  function receiveProject(server: SoundProject): boolean {
    replaceProject(server);
    if (!draft || !baseline || draft.id !== server.id || server.revision < baseline.revision) return true;
    const merged = mergeSoundProject(draft, baseline, server);
    draft = merged.project;
    if (!draft.assets.some((asset) => asset.id === selectedId)) selectedId = draft.assets[0]?.id ?? "";
    if (merged.conflicts.length) {
      backup(draft, baseline);
      notice('error', t('sound.conflictNotice'));
      return false;
    }
    baseline = copySoundProject(server);
    if (projectContentKey(draft) !== projectContentKey(server)) backup(draft, baseline);
    else clearBackup(server.id);
    return true;
  }
  async function generateSound() {
    if (!draft || !selected || generation || saving) return;
    if (!selected.prompt.trim()) { notice('error', t('sound.needPrompt')); return; }
    if (!engineReady) { notice('info', t('sound.engineNotReady')); return; }
    const projectId = draft.id; const assetId = selected.id; const projectTitle = draft.title; const assetTitle = selected.title;
    generation = { project_id: projectId, asset_id: assetId, title: assetTitle };
    try {
      const saved = await persistDraft();
      if (!saved) return;
      const asset = saved.assets.find((item) => item.id === assetId);
      if (!asset) return;
      const response = await apiFetch('/api/sound-effects/generate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, asset_id: assetId, prompt: asset.prompt,
          negative_prompt: asset.negative_prompt, duration_seconds: asset.duration_seconds,
          auto_duration: asset.auto_duration, variations: asset.variations, guidance_scale: asset.guidance_scale, seed: asset.seed, steps: 8, model_id: engine?.id }),
      });
      const data = await response.json() as { results: SoundEffectResult[]; project?: SoundProject; storage_warning?: string; generation_warning?: string };
      const merged = data.project ? receiveProject(data.project) : true;
      if (data.storage_warning || !data.project) {
        const warning = data.storage_warning ?? t('sound.unlinkedWarning');
        keepUnlinked({ id: soundId(), project_title: projectTitle, asset_title: assetTitle, warning, results: data.results });
        notice('info', t('sound.unlinkedNotice', { warning }));
      } else if (merged) notice(data.generation_warning ? 'info' : 'success', data.generation_warning ? t('sound.partial', { warning: data.generation_warning }) : t('sound.generated', { title: assetTitle, count: data.results.length }));
    } catch (error) { notice('error', t('sound.generateFail', { error: errorText(error) })); }
    finally { generation = null; }
  }

  async function restoreRecovery(record: SoundProjectRecovery) {
    if (saving || loading) return;
    loading = true;
    try {
      const response = await apiFetch(`/api/sound-projects/${record.draft.id}`);
      const current = await response.json() as SoundProject;
      const restored = mergeSoundProject(record.draft, record.base, current);
      if (restored.conflicts.length) { recoveryConflict = record; return; }
      replaceProject(current); baseline = copySoundProject(current); draft = restored.project;
      selectedId = draft.assets[0]?.id ?? ''; backup(draft, baseline); recoveryConflict = null;
      notice('info', t('sound.restored'));
    } catch { recoveryConflict = record; }
    finally { loading = false; }
  }
  async function restoreAsCopy(record: SoundProjectRecovery) {
    if (saving) return;
    const project = copySoundProject(record.draft);
    project.id = soundId(); project.revision = 0; project.title = t('sound.recoveredTitle', { title: project.title.slice(0, 153) });
    project.assets = project.assets.map((asset) => ({ ...asset, id: soundId() }));
    saving = true;
    try {
      const response = await apiFetch(`/api/sound-projects/${project.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(project) });
      const saved = await response.json() as SoundProject;
      replaceProject(saved); baseline = copySoundProject(saved); draft = copySoundProject(saved); selectedId = saved.assets[0]?.id ?? '';
      clearBackup(record.draft.id); recoveryConflict = null; notice('success', t('sound.restoredAsCopy'));
    } catch (error) { notice('error', errorText(error)); }
    finally { saving = false; }
  }
  function discardRecovery(record: SoundProjectRecovery) {
    if (window.confirm(t('sound.confirmDiscard'))) clearBackup(record.draft.id);
  }
  async function importLegacy() {
    if (saving || !legacyResults.length) return;
    saving = true;
    let project: SoundProject | null = null;
    try {
      project = legacySoundProject(legacyResults);
      const existing = projects.find((item) => item.id === project?.id);
      let saved: SoundProject;
      if (existing) saved = await (await apiFetch(`/api/sound-projects/${existing.id}`)).json() as SoundProject;
      else {
        try { saved = await (await apiFetch(`/api/sound-projects/${project.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(project) })).json() as SoundProject; }
        catch (error) {
          try { saved = await (await apiFetch(`/api/sound-projects/${project.id}`)).json() as SoundProject; }
          catch { throw error; }
        }
      }
      replaceProject(saved); baseline = copySoundProject(saved); draft = copySoundProject(saved); selectedId = saved.assets[0]?.id ?? '';
      try { markLegacySoundImported(); } catch { /* The stable project ID still makes retries safe. */ }
      legacyResults = []; notice('success', t('sound.legacyImported'));
    } catch (error) { notice('error', t('sound.legacyFail', { error: errorText(error) })); }
    finally { saving = false; }
  }

  onMount(() => {
    refreshRecoveries(); legacyResults = readLegacySoundResults(); unlinked = readUnlinkedSounds(); void loadProjects();
    const beforeLeave = (event: BeforeUnloadEvent) => {
      if (draft && baseline && dirty) { backup(draft, baseline); event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', beforeLeave);
    return () => {
      if (draft && baseline && dirty) { try { saveSoundRecovery(draft, baseline); } catch { /* beforeunload warns if applicable. */ } }
      window.removeEventListener('beforeunload', beforeLeave);
    };
  });
</script>

<div class="grid min-w-0 gap-6">
  {#if feedback}
    <div class="flex items-center justify-between gap-3 rounded-lg border px-4 py-3 text-sm {feedback.type === 'error' ? 'border-danger/30 bg-danger-soft text-danger' : 'border-success/25 bg-success-soft text-foreground'}" role={feedback.type === 'error' ? 'alert' : 'status'}>
      <span class="break-words">{feedback.text}</span>
      <Button variant="ghost" size="icon-sm" onclick={() => feedback = null} aria-label={t('sound.closeNotice')}><X size={14} aria-hidden="true" /></Button>
    </div>
  {/if}
  {#if recoveryWarning}<div class="border-danger/30 bg-danger-soft text-danger rounded-lg border px-4 py-3 text-sm" role="alert">{recoveryWarning}</div>{/if}
  {#if generation}
    <div class="bg-muted flex flex-wrap items-center gap-2.5 rounded-lg px-4 py-3 text-sm" role="status"><Loader2 size={15} class="text-brand animate-spin" aria-hidden="true" /><strong>{generation.title}</strong><span class="text-muted-foreground">{t('sound.generating')}</span></div>
  {/if}

  {#if !draft}
    <header class="flex flex-wrap items-center justify-between gap-3">
      <h2 class="text-xl font-semibold">{t('sound.projects')}</h2>
      <div class="flex items-center gap-2">
        {#if sfxModels.length > 1}
          <div class="w-52"><ModelPicker models={sfxModels} value={modelId} domain="sfx" onChange={(id) => (modelId = id)} /></div>
        {:else}
          <Badge variant={engineReady ? 'success' : 'warning'}>{engineReady ? t('sound.engineReady') : t('sound.engineNeeded')}</Badge>
        {/if}
      </div>
    </header>

    {#if recoveries.length}
      <section class="{card} grid gap-3 p-5" aria-label={t('sound.unsaved')}>
        <h3 class="text-base font-semibold">{t('sound.unsaved')}</h3>
        {#each recoveries as record (record.draft.id)}
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="grid min-w-0"><strong class="text-sm break-words">{record.draft.title}</strong><span class="text-muted-foreground text-xs">{formatDate(record.saved_at)}</span></div>
            <div class="flex items-center gap-2"><Button variant="secondary" size="sm" disabled={saving || loading} onclick={() => restoreRecovery(record)}>{t('sound.continueEditing')}</Button><Button variant="ghost" size="sm" disabled={saving} onclick={() => discardRecovery(record)}>{t('sound.discardBackup')}</Button></div>
          </div>
        {/each}
      </section>
    {/if}
    {#if recoveryConflict}
      <div class="border-warning/30 bg-warning-soft flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3 text-sm" role="alert"><div class="min-w-0 flex-1"><strong>{t('sound.conflict.title')}</strong><p class="text-muted-foreground mt-0.5 text-xs">{t('sound.conflict.body')}</p></div><Button disabled={saving} onclick={() => restoreAsCopy(recoveryConflict!)}>{t('sound.conflict.copy')}</Button><Button variant="ghost" onclick={() => recoveryConflict = null}>{t('common.close')}</Button></div>
    {/if}
    {#if legacyResults.length}
      <div class="bg-muted flex flex-wrap items-center gap-3 rounded-lg px-4 py-3 text-sm"><strong class="min-w-0 flex-1">{t('sound.legacy.title', { count: legacyResults.length })}</strong><Button variant="secondary" disabled={saving || loading} onclick={importLegacy}>{t('sound.legacy.import')}</Button></div>
    {/if}

    <section class="{card} p-5" aria-labelledby="new-sound-project-title">
      <h3 id="new-sound-project-title" class="text-base font-semibold">{t('sound.new.title')}</h3>
      <form class="mt-4 grid items-end gap-3 sm:grid-cols-[minmax(180px,1fr)_160px_auto]" onsubmit={(event) => { event.preventDefault(); void createProject(); }}>
        <label class="grid gap-1.5 text-sm font-medium">{t('sound.new.name')}<input class="studio-input" aria-label={t('sound.new.nameLabel')} placeholder={t('sound.new.namePlaceholder')} maxlength="160" bind:value={newTitle} disabled={saving} required /></label>
        <label class="grid gap-1.5 text-sm font-medium">{t('sound.new.purpose')}<select class="studio-input" bind:value={newCategory} disabled={saving}>{#each PROJECT_CATEGORIES as item}<option value={item.value}>{item.label}</option>{/each}</select></label>
        <Button type="submit" disabled={saving || loading || !newTitle.trim()}>{saving ? t('tts.editor.saving') : t('sound.new.create')}</Button>
      </form>
    </section>

    <section class="grid gap-3" aria-labelledby="sound-starters-title">
      <div class="flex items-center gap-1"><h3 id="sound-starters-title" class="text-base font-semibold">{t('sound.starters.title')}</h3><HelpPopover label={t('sound.starters.title')} text={t('sound.starters.help')} /></div>
      <div class="grid gap-3.5 md:grid-cols-2 xl:grid-cols-3">
        {#each SOUND_STARTER_PACKS as pack}
          <article class="{card} flex min-w-0 flex-col gap-3 p-5">
            <Badge variant="secondary" class="self-start">{projectCategoryLabel(pack.category)}</Badge>
            <div><h4 class="text-base font-semibold">{pack.title}</h4><p class="text-muted-foreground mt-1 text-xs">{pack.description}</p></div>
            <div class="flex flex-wrap gap-1.5">{#each pack.examples as example}<span class="border-border text-muted-foreground rounded border px-1.5 py-0.5 text-[11px]">{example.title}</span>{/each}</div>
            <details class="text-xs"><summary class="text-muted-foreground hover:text-foreground cursor-pointer">{t('sound.starters.preview', { count: pack.examples.length })}</summary>{#each pack.examples as example}<div class="mt-3"><strong>{example.title}</strong><p class="text-muted-foreground mt-1 break-words">{example.prompt}</p></div>{/each}</details>
            <Button variant="secondary" class="mt-auto" disabled={saving || loading} onclick={() => createProject(pack)}>{t('sound.starters.use')}</Button>
          </article>
        {/each}
      </div>
    </section>

    <section class="grid gap-3" aria-labelledby="sound-project-list-title">
      <div class="flex items-center justify-between gap-3"><div class="flex items-baseline gap-2"><h3 id="sound-project-list-title" class="text-base font-semibold">{t('sound.list.title')}</h3><span class="text-muted-foreground text-xs">{t('sound.list.count', { count: projects.length })}</span></div><Button variant="ghost" size="sm" disabled={loading || saving} onclick={loadProjects}><RefreshCw size={14} aria-hidden="true" />{t('common.refresh')}</Button></div>
      {#if loading}<div class="{card} text-muted-foreground p-8 text-center text-sm" role="status">{t('sound.list.loading')}</div>
      {:else if !projects.length}<div class="{card} p-8 text-center"><h4 class="text-sm font-medium">{t('sound.list.empty')}</h4></div>
      {:else}
        <div class="grid gap-3.5 md:grid-cols-2 xl:grid-cols-3">
          {#each projects as project (project.id)}
            <button class="project-card {card} hover:border-brand grid min-w-0 gap-2 p-5 text-left transition-colors" disabled={saving} onclick={() => openProject(project)}>
              <Badge variant="secondary" class="self-start">{projectCategoryLabel(project.category)}</Badge>
              <strong class="text-base break-words">{project.title}</strong>
              <span class="text-muted-foreground text-xs">{t('sound.list.meta', { sounds: project.assets.length, results: project.assets.reduce((count, asset) => count + asset.results.length, 0) })}</span>
              <small class="text-subtle-foreground text-[11px]">{formatDate(project.updated_at)}</small>
            </button>
          {/each}
        </div>
      {/if}
    </section>
  {:else}
    <header class="grid min-w-0 gap-3">
      <div><Button variant="ghost" size="sm" disabled={saving} onclick={backToProjects}><ArrowLeft size={14} aria-hidden="true" />{t('sound.back')}</Button></div>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex min-w-0 flex-1 flex-wrap items-center gap-2.5">
          <label class="sr-only" for="sound-project-title">{t('sound.new.name')}</label>
          <input id="sound-project-title" class="hover:border-border focus:border-border min-w-20 max-w-lg flex-1 rounded-lg border border-transparent bg-transparent px-1 py-0.5 text-2xl font-semibold" value={draft.title} maxlength="160" disabled={saving} oninput={(event) => changeProject({ title: event.currentTarget.value })} />
          <label class="sr-only" for="sound-project-category">{t('sound.new.purpose')}</label>
          <select id="sound-project-category" class="studio-input w-32 text-xs" value={draft.category} disabled={saving} onchange={(event) => changeProject({ category: event.currentTarget.value as SoundProjectCategory })}>{#each PROJECT_CATEGORIES as item}<option value={item.value}>{item.label}</option>{/each}</select>
        </div>
        <div class="flex items-center gap-2.5">
          <span class="text-xs whitespace-nowrap {dirty ? 'text-warning' : 'text-muted-foreground'}">{saving ? t('tts.editor.saving') : dirty ? t('tts.editor.unsaved') : t('tts.editor.saved')}</span>
          <Button disabled={saving || !dirty} onclick={saveProject}>{t('sound.save')}</Button>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger aria-label={t('sound.more')} class="border-border hover:bg-muted inline-flex size-8 items-center justify-center rounded-lg border"><Ellipsis size={16} aria-hidden="true" /></DropdownMenu.Trigger>
            <DropdownMenu.Content align="end" class="min-w-56">
              <DropdownMenu.Item disabled={saving} onSelect={reloadSavedProject}>{t('sound.reload')}</DropdownMenu.Item>
              <DropdownMenu.Item variant="destructive" disabled={saving} onSelect={deleteProject}>{t('sound.deleteProject')}</DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </div>
      </div>
      <p class="text-muted-foreground text-xs">{t('sound.list.meta', { sounds: draft.assets.length, results: totalResults })}</p>
    </header>

    <div class="grid items-start gap-5 lg:grid-cols-[246px_minmax(0,1fr)]">
      <aside class="{card} min-w-0 p-3 lg:sticky lg:top-20" aria-label={t('sound.sidebar')}>
        <div class="border-border-soft flex items-center justify-between border-b px-1 pb-3"><h3 class="text-sm font-semibold">{t('sound.assets')}</h3><Button variant="secondary" size="sm" disabled={saving || draft.assets.length >= 300} onclick={() => addAsset()}><Plus size={13} aria-hidden="true" />{t('sound.add')}</Button></div>
        {#if !draft.assets.length}<p class="text-muted-foreground px-2 py-4 text-xs">{t('sound.noAssets')}</p>{/if}
        <div class="mt-2 flex gap-1.5 overflow-x-auto lg:grid lg:max-h-[70vh] lg:overflow-y-auto">
          {#each draft.assets as asset (asset.id)}
            <button class="min-w-44 rounded-lg border px-3 py-2.5 text-left transition-colors lg:min-w-0 {asset.id === selectedId ? 'border-border bg-muted' : 'hover:bg-muted/60 border-transparent'}" onclick={() => selectAsset(asset.id)}>
              <div class="flex items-center justify-between gap-2"><strong class="truncate text-xs">{asset.title || t('sound.untitled')}</strong><span class="bg-muted text-muted-foreground shrink-0 rounded px-1.5 text-[10px]">{asset.results.length}</span></div>
              <small class="text-subtle-foreground mt-1 block text-[10px]">{assetCategoryLabel(asset.category)}{generation?.project_id === draft.id && generation?.asset_id === asset.id ? ' · ' + t('sound.assetGenerating') : ''}</small>
              <p class="text-muted-foreground mt-1 line-clamp-2 text-[11px] break-words">{asset.prompt || t('sound.describe')}</p>
            </button>
          {/each}
        </div>
      </aside>

      <div class="grid min-w-0 gap-5">
        {#if selected}
          <section class="{card} min-w-0 p-5 sm:p-6" aria-label={t('sound.editor')}>
            <div class="mb-4 flex items-center justify-between gap-3">
              <div class="inline-flex items-center gap-1"><h3 class="flex items-center gap-1 text-base font-semibold">{t('sound.editor.title')}</h3><HelpPopover label={t('sound.editor.promptHelpLabel')} text={t('sound.editor.promptHelp')} /></div>
              <Button variant="ghost" size="sm" class="text-danger" disabled={saving} onclick={deleteAsset}>{t('sound.deleteAsset')}</Button>
            </div>
            <div class="grid gap-3.5 sm:grid-cols-[minmax(0,1fr)_160px]">
              <label class="grid gap-1.5 text-sm font-medium">{t('sound.assetName')}<input class="studio-input" aria-label={t('sound.assetName')} value={selected.title} maxlength="160" disabled={saving} oninput={(event) => changeAsset({ title: event.currentTarget.value })} /></label>
              <label class="grid gap-1.5 text-sm font-medium">{t('sound.assetType')}<select class="studio-input" value={selected.category} disabled={saving} onchange={(event) => changeAsset({ category: event.currentTarget.value as SoundAssetCategory })}>{#each ASSET_CATEGORIES as item}<option value={item.value}>{item.label}</option>{/each}</select></label>
            </div>
            <label class="mt-4 grid gap-1.5 text-sm font-medium">{t('sound.prompt')}<textarea class="studio-input min-h-36 leading-relaxed" aria-label={t('sound.promptLabel')} value={selected.prompt} maxlength="2000" rows="5" disabled={saving} placeholder={t('sound.promptPlaceholder')} oninput={(event) => changeAsset({ prompt: event.currentTarget.value })}></textarea></label>
            <div class="text-muted-foreground mt-1.5 text-xs"><span>{t('sound.promptCount', { count: selected.prompt.length })}</span></div>
            <div class="mt-5 grid gap-4 sm:grid-cols-[minmax(0,1fr)_160px]">
              <div>
                <span class="mb-1.5 block text-sm font-medium">{t('sound.duration')}</span>
                <div class="flex min-h-10 flex-wrap items-center gap-4">
                  <label class="flex items-center gap-2 text-sm"><input type="checkbox" checked={selected.auto_duration} disabled={saving} onchange={(event) => changeAsset({ auto_duration: event.currentTarget.checked })} />{t('sound.durationAuto')}</label>
                  {#if !selected.auto_duration}
                    <label class="flex items-center gap-1.5 text-sm"><span class="sr-only">{t('sound.durationLabel')}</span><input class="studio-input w-20" aria-label={t('sound.durationLabel')} type="number" min="0.5" max="15" step="0.5" value={selected.duration_seconds} disabled={saving} onchange={(event) => changeAsset({ duration_seconds: Math.min(15, Math.max(0.5, Number(event.currentTarget.value) || 3)) })} /><span>{t('sound.seconds')}</span></label>
                  {:else}<small class="text-muted-foreground text-xs">{t('sound.durationRange')}</small>{/if}
                </div>
              </div>
              <label class="grid gap-1.5 text-sm font-medium">{t('sound.variations')}<select class="studio-input" aria-label={t('sound.variationsLabel')} value={selected.variations} disabled={saving} onchange={(event) => changeAsset({ variations: Number(event.currentTarget.value) })}>{#each [1, 2, 3, 4] as count}<option value={count}>{t('home.count', { count })}</option>{/each}</select></label>
            </div>
            <details class="border-border-soft mt-5 border-t pt-4">
              <summary class="text-muted-foreground hover:text-foreground cursor-pointer text-sm">{t('tts.set.advanced')}</summary>
              <div class="mt-4 grid gap-4 sm:grid-cols-2">
                <label class="grid gap-1.5 text-sm font-medium sm:col-span-2">{t('sound.negative')}<textarea class="studio-input" value={selected.negative_prompt} rows="2" maxlength="1000" disabled={saving} oninput={(event) => changeAsset({ negative_prompt: event.currentTarget.value })}></textarea></label>
                <label class="grid gap-1.5 text-sm font-medium"><span class="inline-flex items-center gap-1">{t('sound.seed')}<HelpPopover label={t('sound.seed')} text={t('sound.seedHelp')} /></span><input class="studio-input" aria-label={t('sound.seedLabel')} type="number" min="0" max="2147483643" step="1" value={selected.seed ?? ''} disabled={saving} onchange={(event) => changeAsset({ seed: event.currentTarget.value === '' ? null : Math.min(2147483643, Math.max(0, Math.floor(Number(event.currentTarget.value) || 0))) })} /></label>
                <label class="grid gap-1.5 text-sm font-medium"><span>{t('sound.guidance')} <span class="text-muted-foreground font-normal">{selected.guidance_scale.toFixed(1)}</span></span><input type="range" min="0" max="8" step="0.1" value={selected.guidance_scale} disabled={saving} oninput={(event) => changeAsset({ guidance_scale: Number(event.currentTarget.value) })} /></label>
              </div>
            </details>
            <div class="border-border-soft mt-5 flex flex-wrap items-center justify-between gap-4 border-t pt-5">
              <div class="flex min-w-0 items-center gap-1">
                <strong class="text-sm">{engineReady ? (generatingSelected ? t('sound.generatingSelected') : t('sound.ready')) : t('sound.engineNeeded')}</strong>
                {#if engineReady}<HelpPopover label={t('sound.generateHelpLabel')} text={t('sound.generateHelp')} />{:else}<span class="text-muted-foreground text-xs">{t('sound.saveOnly')}</span>{/if}
              </div>
              <div class="flex items-center gap-2.5">
                {#if sfxModels.length > 1}<div class="w-44"><ModelPicker models={sfxModels} value={modelId} domain="sfx" disabled={Boolean(generation)} onChange={(id) => (modelId = id)} /></div>{/if}
                <Button disabled={saving || Boolean(generation) || !engineReady || !selected.prompt.trim()} onclick={generateSound}>{generatingSelected ? t('sound.generatingShort') : generation ? t('sound.otherGenerating') : t('sound.generate')}</Button>
              </div>
            </div>
            {#if !engineReady}<details class="bg-muted mt-3 rounded-lg px-3.5 py-3 text-xs"><summary class="cursor-pointer">{t('sound.engineStatus')}</summary><p class="text-muted-foreground mt-2 break-words">{engine?.message || t('sound.engineCheck')}</p>{#if engine}<p class="text-muted-foreground mt-1">{engine.label}{!engine.enabled ? ' · ' + t('sound.disabled') : ''}</p>{/if}</details>{/if}
          </section>
        {:else}
          <section class="{card} grid justify-items-center gap-3 p-10 text-center"><h3 class="text-base font-semibold">{t('sound.firstSound')}</h3><Button disabled={saving} onclick={() => addAsset()}><Plus size={14} aria-hidden="true" />{t('sound.addSound')}</Button></section>
        {/if}

        <section class="{card} p-5" aria-label={t('sound.examples.aria')}>
          <div class="flex items-center justify-between gap-3">
            <div class="inline-flex items-center gap-1"><h3 class="flex items-center gap-1 text-sm font-semibold">{t('sound.examples.title')}</h3><HelpPopover label={t('sound.examples.title')} text={t('sound.examples.help')} /></div>
            {#if selected}<Button variant="ghost" size="sm" aria-expanded={showExamples} onclick={() => showExamples = !showExamples}>{showExamples ? t('sound.examples.hide') : t('sound.examples.show')}</Button>{/if}
          </div>
          {#if showExamples || !selected}
            <div class="mt-4 flex flex-wrap gap-1.5" role="group" aria-label={t('sound.examples.kind')}>{#each SOUND_STARTER_PACKS as pack}<button class="rounded-lg border px-2.5 py-1 text-xs {examplePack === pack.id ? 'bg-primary text-primary-foreground border-primary' : 'border-border hover:bg-muted'}" aria-pressed={examplePack === pack.id} onclick={() => examplePack = pack.id}>{pack.title}</button>{/each}</div>
            <div class="mt-3.5 grid gap-3 md:grid-cols-2">
              {#each examples.examples as example}
                <article class="border-border flex min-w-0 flex-col gap-2 rounded-xl border p-3.5">
                  <div class="flex items-center justify-between gap-2"><strong class="text-xs">{example.title}</strong><small class="text-muted-foreground text-[10px] whitespace-nowrap">{t('sound.examples.seconds', { seconds: example.duration_seconds })}</small></div>
                  <p class="text-muted-foreground text-[11px] break-words">{example.prompt}</p>
                  <Button variant="secondary" size="sm" class="mt-auto self-start" disabled={saving || draft.assets.length >= 300} onclick={() => addAsset(example)}>{t('sound.examples.add')}</Button>
                </article>
              {/each}
            </div>
          {/if}
        </section>

        {#if selected}
          <section class="grid gap-3" aria-label={t('sound.results.aria')}>
            <div class="flex items-center justify-between gap-3"><h3 class="text-base font-semibold">{t('sound.results.title')} <span class="text-muted-foreground text-xs font-normal">{selected.results.length}</span></h3><Button variant="ghost" size="sm" disabled={saving} onclick={() => similarAsset()}>{t('sound.results.similar')}</Button></div>
            {#if !selected.results.length}<div class="{card} text-muted-foreground p-6 text-center text-sm">{t('sound.results.empty')}</div>
            {:else}<SoundResultList results={selected.results} title={selected.title} {saving} onReuse={reuseResult} onSimilar={similarAsset} onRemove={removeVersion} />{/if}
          </section>
        {/if}
      </div>
    </div>
  {/if}

  <ProductionAssistPanel
    panelId="sound"
    kinds={['sound_effect', 'music', 'song']}
    contextKey={JSON.stringify({ project: draft?.id, asset: selected?.id, prompt: selected?.prompt, negative_prompt: selected?.negative_prompt, category: selected?.category, duration: selected?.duration_seconds, auto_duration: selected?.auto_duration })}
    initialBrief={selected?.prompt ?? ''}
    disabled={saving || Boolean(generation)}
    allowApply={Boolean(draft && selected)}
    onApply={applySoundRecommendation}
  />

  {#if unlinked.length}
    <section class="grid gap-3.5" aria-label={t('sound.unlinked.title')}>
      <div class="flex items-center gap-1"><h3 class="text-base font-semibold">{t('sound.unlinked.title')}</h3><HelpPopover label={t('sound.unlinked.title')} text={t('sound.unlinked.help')} /></div>
      {#each unlinked as item (item.id)}<article class="{card} border-warning/40 grid gap-3 p-5"><div><h4 class="text-sm font-semibold">{item.asset_title}</h4><p class="text-muted-foreground text-xs">{item.project_title} · {item.warning}</p></div><SoundResultList results={item.results} title={item.asset_title} /></article>{/each}
    </section>
  {/if}
</div>

<style>
  details > summary { list-style: none; }
  details > summary::-webkit-details-marker { display: none; }
</style>
