<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
 import { onDestroy, onMount, tick } from 'svelte';
 import { Plus, RefreshCw, Save, Copy, Trash2, Plug, LoaderCircle, LogIn, Check } from '@lucide/svelte';
 import HelpPopover from '$lib/components/HelpPopover.svelte';
 import { apiFetch } from '$lib/studio/api';
 import type { AiTextProviderCatalog, AiProviderLoginSession, AiTranslationMode, StudioNotice } from '$lib/studio/types';
 import { presets, protocolLabels, taskLabels, taskKeys, newModel, newProfile, profileDraft, endpointPreview, parseSelection, selectionValue, type ApiProfile, type ProfileDraft, type ProfilesResponse, type TaskKey } from '$lib/studio/ai-connections';

 let { onNotice, onChanged, showTranslation = true }: { onNotice?: (type: StudioNotice['type'], text: string) => void; onChanged?: () => void; showTranslation?: boolean } = $props();
 let catalog = $state<AiTextProviderCatalog | null>(null);
 let data = $state<ProfilesResponse | null>(null);
 let catalogLoading = $state(false);
 let catalogWarning = $state('');
 let catalogEpoch = 0;
 let busy = $state('');
 let error = $state('');
 let status = $state('');
 let editorOpen = $state(false);
 let editingId = $state('');
 let editingRevision = $state(0);
 let savedProfile = $state<ApiProfile | null>(null);
 let draft = $state<ProfileDraft>(newProfile());
 let key = $state('');
 let clearKey = $state(false);
 let destinationConfirmed = $state(false);
 let headersText = $state('{}');
 let baseline = $state('');
 let presetId = $state('custom');
 let discovered = $state<{ id: string; label: string }[]>([]);
 let discoveredId = $state('');
 let modelToTest = $state('');
 let probe = $state<{ elapsed_ms: number; content: string; instruction_followed: boolean; model_id: string } | null>(null);
 let checkedProfiles = $state<Record<string, { revision: number; model_id: string; elapsed_ms: number }>>({});
 let removeId = $state('');
 let defaultValue = $state('');
 let defaultBaseline = $state('');
 let taskValues = $state<Record<TaskKey, string>>({ translation: '', writing: '', sound_prompt: '' });
 let taskBaseline = $state('');
 let routingRevision = $state(0);
 let translationMode = $state<AiTranslationMode>('auto');
 let translationBaseline = $state<AiTranslationMode>('auto');
 let loginSession = $state<AiProviderLoginSession | null>(null);
 let loginProvider = $state('');
 let loginTimer: ReturnType<typeof setTimeout> | undefined;
 let alive = true;
 const requests = new Set<AbortController>();

 const allProviders = $derived([...(catalog?.providers ?? []), ...(catalog?.api_providers ?? [])].filter(p => !['local', 'compatible', 'nvidia'].includes(p.id) || catalog?.selection.provider_id === p.id || Object.values(data?.routing ?? {}).some(r => r?.provider_id === p.id)));
 const nativeProviders = $derived((catalog?.providers ?? []).filter(p => p.id === 'apple' || p.id === 'chatgpt' || p.id === 'kimi'));
 const choices = $derived([
  ...allProviders.filter(p => !p.id.startsWith('api-')).flatMap(p => p.models.map(m => ({ value: selectionValue({ provider_id: p.id, model_id: m.id }), label: `${p.label} · ${m.label}`, disabled: Boolean(catalog?.connections.local_only && p.connection_type !== 'local') }))),
  ...(data?.profiles ?? []).flatMap(p => p.models.map(m => ({ value: selectionValue({ provider_id: p.id, model_id: m.id }), label: `${p.name} · ${m.label || m.id}`, disabled: !p.enabled || p.blocked || (p.auth_type !== 'none' && !p.has_api_key) })))
 ]);
 const dirty = $derived(editorOpen && (JSON.stringify({ draft, headersText }) !== baseline || Boolean(key) || clearKey));
 const destinationChanged = $derived(Boolean(savedProfile && (savedProfile.base_url !== draft.base_url || savedProfile.protocol !== draft.protocol || savedProfile.auth_type !== draft.auth_type)));
 const taskDirty = $derived(JSON.stringify(taskValues) !== taskBaseline);

 async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController(); requests.add(controller);
  try { return await (await apiFetch(path, { ...init, signal: controller.signal })).json(); }
  finally { requests.delete(controller); }
 }
 const body = (value: unknown, method = 'POST'): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
 async function run(label: string, action: () => Promise<void>) {
  if (busy) return;
  busy = label; error = ''; status = '';
  try { await action(); }
  catch (e) { if (alive) { error = e instanceof Error ? e.message : String(e); onNotice?.('error', error); } }
  finally { if (alive) busy = ''; }
 }
 function success(text: string) { status = text; onNotice?.('success', text); onChanged?.(); }
 function updateData(value: ProfilesResponse, resetRoutes = false) {
  const preserveRoutes = !resetRoutes && taskDirty;
  const serverValues = { translation: selectionValue(value.routing.translation), writing: selectionValue(value.routing.writing), sound_prompt: selectionValue(value.routing.sound_prompt) };
  data = value;
  if (!preserveRoutes) {
   taskValues = serverValues;
   taskBaseline = JSON.stringify(serverValues); routingRevision = value.revision;
  } else if (JSON.stringify(serverValues) === taskBaseline) {
   // Editing an unrelated connection does not invalidate the user's task choices.
   routingRevision = value.revision;
  }
 }
 function invalidateCatalogRead() { catalogEpoch += 1; catalogLoading = false; }
 async function refreshCatalog(initial = false, afterWrite = false) {
  const epoch = ++catalogEpoch;
  catalogLoading = true; catalogWarning = '';
  try {
   const nextCatalog = await json<AiTextProviderCatalog>('/api/ai/providers');
   if (!alive || epoch !== catalogEpoch) return;
   catalog = nextCatalog;
   if (initial || defaultValue === defaultBaseline) { defaultValue = selectionValue(nextCatalog.selection); defaultBaseline = defaultValue; }
   if (initial || translationMode === translationBaseline) { translationMode = nextCatalog.translation?.mode ?? 'auto'; translationBaseline = translationMode; }
  } catch {
   if (alive && epoch === catalogEpoch) catalogWarning = afterWrite
    ? t('ai.catalogAfterWrite')
    : t('ai.catalogFail');
  } finally { if (alive && epoch === catalogEpoch) catalogLoading = false; }
 }
 async function catalogAfterWrite(): Promise<string> {
  void refreshCatalog(false, true);
  return '';
 }
 async function refresh(initial = false) {
  void refreshCatalog(initial);
  const nextData = await json<ProfilesResponse>('/api/ai/connections');
  if (alive) updateData(nextData, initial);
 }
 onMount(() => { void run('loading', () => refresh(true)); });
 onDestroy(() => { alive = false; clearTimeout(loginTimer); requests.forEach(c => c.abort()); key = ''; });
 function mayLeave() { return !dirty || window.confirm(t('ai.confirmLeave')); }
 async function focusEditor() { await tick(); document.getElementById('ai-connection-name')?.focus(); document.getElementById('ai-connection-editor')?.scrollIntoView({ block: 'start', behavior: 'smooth' }); }
 function openEditor(profile?: ApiProfile, duplicate = false) {
  if (!mayLeave()) return;
  savedProfile = duplicate ? null : profile ?? null; editingId = duplicate ? '' : profile?.id ?? ''; editingRevision = duplicate ? 0 : profile?.revision ?? 0;
  draft = profile ? profileDraft(profile) : newProfile();
  if (duplicate) draft.name += t('ai.copySuffix');
  headersText = JSON.stringify(profile?.extra_headers ?? {}, null, 2);
  key = ''; clearKey = false; destinationConfirmed = false; error = ''; status = ''; discovered = []; probe = null;
  presetId = 'custom'; modelToTest = draft.default_model_id; baseline = JSON.stringify({ draft, headersText }); editorOpen = true;
  void focusEditor();
 }
 function presetChanged() {
  const preset = presets.find(p => p.id === presetId); if (!preset || preset.id === 'custom') return;
  draft = { ...draft, name: preset.label, protocol: preset.protocol, base_url: preset.base_url, auth_type: preset.auth_type, local_engine: preset.local_engine ?? 'generic' };
  key = ''; clearKey = false; destinationConfirmed = false; probe = null;
 }
 async function saveProfile() {
  await run('saving', async () => {
   let extra_headers: Record<string, string>;
   try { extra_headers = JSON.parse(headersText); }
   catch { throw new Error(t('ai.headersJson')); }
   const models = draft.models.filter(m => m.id.trim()).map(m => ({ ...m, id: m.id.trim(), label: m.label.trim() }));
   if (draft.models.some(m => !m.id.trim())) throw new Error(t('ai.modelIdMissing'));
   const payload = { ...draft, models, default_model_id: draft.default_model_id || models[0]?.id || '', extra_headers,
    expected_revision: editingRevision, confirm_destination_change: destinationConfirmed, clear_api_key: clearKey, ...(key.trim() ? { api_key: key.trim() } : {}) };
   const result = await json<ProfilesResponse & { profile: ApiProfile & { credential_warning?: string } }>(editingId ? `/api/ai/connections/${editingId}` : '/api/ai/connections', body(payload, editingId ? 'PUT' : 'POST'));
   key = ''; clearKey = false; destinationConfirmed = false;
   updateData(result); savedProfile = result.profile; editingId = result.profile.id; editingRevision = result.profile.revision;
   draft = profileDraft(result.profile); headersText = JSON.stringify(result.profile.extra_headers, null, 2); baseline = JSON.stringify({ draft, headersText });
   modelToTest = draft.default_model_id; probe = null;
   const refreshWarning = await catalogAfterWrite();
   success((result.profile.credential_warning || t('ai.saved')) + refreshWarning);
  });
 }
 function addModel(id = '', label = '') {
  if (id && draft.models.some(m => m.id === id)) return;
  draft.models = [...draft.models, newModel(id, label)];
  if (!draft.default_model_id && id) draft.default_model_id = id;
  probe = null;
 }
 function removeModel(index: number) {
  const id = draft.models[index].id; draft.models = draft.models.filter((_, i) => i !== index);
  if (draft.default_model_id === id) draft.default_model_id = draft.models[0]?.id ?? '';
  probe = null;
 }
 async function discover() {
  await run('models', async () => {
   const result = await json<{ models: { id: string; label: string }[]; message: string; has_more: boolean }>(`/api/ai/connections/${editingId}/models`, body({ expected_revision: editingRevision }));
   discovered = result.models; discoveredId = result.models[0]?.id ?? '';
   status = result.message + (result.has_more ? ' ' + t('ai.first200') : '');
  });
 }
 async function testProfile() {
  await run('testing', async () => {
   probe = null;
   const checkedId = editingId;
   checkedProfiles = Object.fromEntries(Object.entries(checkedProfiles).filter(([id]) => id !== checkedId));
   probe = await json(`/api/ai/connections/${checkedId}/test`, body({ expected_revision: editingRevision, model_id: modelToTest }));
   if (probe) checkedProfiles = { ...checkedProfiles, [checkedId]: { revision: editingRevision, model_id: probe.model_id, elapsed_ms: probe.elapsed_ms } };
   success(t('ai.tested'));
  });
 }
 async function saveDefault() {
  const selection = parseSelection(defaultValue); if (!selection) return;
  await run('default', async () => { invalidateCatalogRead(); catalog = await json('/api/ai/providers/selection', body(selection, 'PUT')); defaultBaseline = defaultValue; catalogWarning = ''; success(t('ai.defaultSaved')); });
 }
 async function saveRoutes() {
  await run('routing', async () => {
   const result = await json<ProfilesResponse>('/api/ai/routing', body({ expected_revision: routingRevision, translation: parseSelection(taskValues.translation), writing: parseSelection(taskValues.writing), sound_prompt: parseSelection(taskValues.sound_prompt) }, 'PUT'));
   updateData(result, true); success(t('ai.routesSaved'));
  });
 }
 async function setLocalOnly(enabled: boolean) {
  await run('policy', async () => { invalidateCatalogRead(); catalog = await json('/api/ai/providers/connections', body({ local_only: enabled }, 'PUT')); await refresh(); success(enabled ? t('ai.localOn') : t('ai.localOff')); });
 }
 async function deleteProfile() {
  const target = data?.profiles.find(p => p.id === removeId); if (!target) return;
  await run('delete', async () => {
   const result = await json<ProfilesResponse & { warning?: string }>(`/api/ai/connections/${target.id}?expected_revision=${target.revision}`, { method: 'DELETE' });
   updateData(result); if (editingId === target.id) { editorOpen = false; key = ''; }
   removeId = ''; const refreshWarning = await catalogAfterWrite(); success((result.warning || t('ai.deleted')) + refreshWarning);
  });
 }
 async function startLogin(provider: string) {
  await run('login', async () => {
   loginProvider = provider; loginSession = await json(`/api/ai/providers/${provider}/login`, { method: 'POST' });
   if (loginSession?.status === 'running') loginTimer = setTimeout(pollLogin, 1500);
  });
 }
 async function pollLogin() {
  if (!alive || !loginSession) return;
  try { loginSession = await json(`/api/ai/providers/login/${loginSession.id}`); if (!alive) return;
   if (loginSession?.status === 'running') loginTimer = setTimeout(pollLogin, 1500); else await run('refresh', () => refresh());
  } catch (e) { if (alive) error = e instanceof Error ? e.message : String(e); }
 }
 async function setTranslation() { await run('translation', async () => { invalidateCatalogRead(); catalog = await json('/api/ai/providers/connections', body({ translation_mode: translationMode }, 'PUT')); translationBaseline = translationMode; catalogWarning = ''; success(t('prefs.trSavedNotice')); }); }
</script>

<section class="ai-connections" aria-labelledby="ai-connections-title">
 <header class="panel-header">
  <div class="title-line"><h2 id="ai-connections-title">{t('ai.title')}</h2><HelpPopover label={t('ai.title')} text={t('ai.help')} /></div>
  <button class="secondary-action" aria-label={t('ai.refreshLabel')} disabled={Boolean(busy)} onclick={() => run('refresh', () => refresh())}><RefreshCw size={16} />{t('common.refresh')}</button>
 </header>
 {#if error}<div class="feedback error" role="alert">{error}<p>{t('ai.errorHint')}</p></div>{/if}
 {#if status}<div class="feedback" role="status">{status}</div>{/if}
 {#if busy}<div class="busy" role="status"><LoaderCircle size={16} class="spin" />{busy === 'testing' ? t('ai.testing') : t('ai.processing')}</div>{/if}
 {#if catalogLoading}<p role="status">{t('ai.catalogLoading')}</p>{/if}
 {#if catalogWarning}<div class="feedback warning" role="status">{catalogWarning}</div>{/if}
 {#if data}
  {#if catalog}
  <div class="policy">
   <label class="check"><input type="checkbox" checked={catalog.connections.local_only} disabled={Boolean(busy)} onchange={e => setLocalOnly(e.currentTarget.checked)} />{t('ai.localOnly')}</label><HelpPopover label={t('ai.localOnly')} text={catalog.connections.local_only ? t('ai.localOnlyOn') : t('ai.localOnlyOff')} />
  </div>
  <div class="default-picker">
   <label for="default-ai">{t('ai.default')}</label>
   <div class="inline"><select id="default-ai" bind:value={defaultValue} disabled={Boolean(busy)}>
    {#if defaultValue && !choices.some(c => c.value === defaultValue)}<option value={defaultValue}>{t('ai.previousChoice')}</option>{/if}
    <option value="">{t('ai.pickModel')}</option>{#each choices as choice (choice.value)}<option value={choice.value} disabled={choice.disabled}>{choice.label}</option>{/each}
   </select><button class="primary-action" disabled={Boolean(busy) || !defaultValue || defaultValue === defaultBaseline} onclick={saveDefault}>{t('ai.saveDefault')}</button></div>
  </div>
  <details class="native-connections">
   <summary>{t('ai.advanced')}</summary>
   {#each nativeProviders as provider (provider.id)}
    <article class="native-row"><div><strong>{provider.label}</strong><p>{provider.message}</p>
     {#if provider.id === 'chatgpt'}<small>{t('ai.chatgptNote')}</small>{/if}
    </div>
    {#if provider.connection_type === 'subscription'}<button class="secondary-action" disabled={Boolean(busy) || catalog.connections.local_only || loginSession?.status === 'running'} onclick={() => startLogin(provider.id)}><LogIn size={15}/>{provider.authenticated ? t('ai.reconnect') : t('ai.connectAccount')}</button>{/if}
    {#if loginSession && loginProvider === provider.id}<div class="feedback" role="status"><p>{loginSession.message}</p>{#if loginSession.user_code}<code>{loginSession.user_code}</code>{/if}{#if loginSession.authorization_url && loginSession.authorization_url.startsWith('https://')}<a href={loginSession.authorization_url} target="_blank" rel="noreferrer">{t('ai.openAuth')}</a>{/if}</div>{/if}
    </article>
   {/each}
  </details>
  {#if showTranslation}<div class="default-picker"><label for="ai-translation-mode">{t('ai.translationMode')}</label><div class="inline"><select id="ai-translation-mode" bind:value={translationMode} disabled={Boolean(busy)}><option value="auto">{t('ai.trAuto')}</option><option value="apple">{t('ai.trApple')}</option><option value="selected">{t('ai.trSelected')}</option></select><button class="secondary-action" onclick={setTranslation} disabled={Boolean(busy)}>{t('prefs.trSave')}</button></div></div>{/if}
  {/if}
  <div class="list-header"><h3>{t('ai.apiConnections')} <span>{data.profiles.length}</span></h3><button class="secondary-action" disabled={Boolean(busy)} onclick={() => openEditor()}><Plus size={16}/>{t('ai.add')}</button></div>
  <div class="profile-list">
   {#each data.profiles as profile (profile.id)}
    <article class:editing={editingId === profile.id && editorOpen} class="profile-row">
     <button class="profile-copy" disabled={Boolean(busy)} onclick={() => openEditor(profile)} aria-label={t('ai.editLabel', { name: profile.name })}><strong><Plug size={15}/>{profile.name}</strong><span>{protocolLabels[profile.protocol]} · {t('ai.modelCount', { count: profile.models.length })}</span><small>{profile.base_url}</small></button>
     <div class="profile-actions"><span class="badge" class:blocked={profile.blocked}>{profile.blocked ? t('ai.status.blocked') : !profile.enabled ? t('ai.status.disabled') : profile.auth_type !== 'none' && !profile.has_api_key ? t('ai.status.needKey') : !profile.models.length ? t('ai.status.needModel') : checkedProfiles[profile.id]?.revision === profile.revision ? t('ai.status.verified') : t('ai.status.registered')}</span>{#if checkedProfiles[profile.id]?.revision === profile.revision}<small class="checked-model" title={t('ai.checkedTitle')}>{checkedProfiles[profile.id].model_id} · {checkedProfiles[profile.id].elapsed_ms} ms</small>{/if}
      <button class="icon-button" aria-label={t('ai.copyLabel', { name: profile.name })} disabled={Boolean(busy)} onclick={() => openEditor(profile, true)}><Copy size={16}/></button>
      <button class="icon-button" aria-label={t('ai.deleteLabel', { name: profile.name })} disabled={Boolean(busy)} onclick={() => { removeId = profile.id; }}><Trash2 size={16}/></button>
     </div>
    </article>
   {/each}
   {#if !data.profiles.length}<p class="empty">{t('ai.empty')}</p>{/if}
  </div>
  {#if removeId}<div class="feedback" role="alert"><strong>{t('ai.confirmDelete', { name: data.profiles.find(p => p.id === removeId)?.name ?? '' })}</strong><p>{t('ai.confirmDeleteBody')}</p><div class="inline"><button class="secondary-action" disabled={Boolean(busy)} onclick={() => removeId = ''}>{t('ai.cancelDelete')}</button><button class="primary-action" disabled={Boolean(busy)} onclick={deleteProfile}>{t('ai.confirmDeleteAction')}</button></div></div>{/if}
  {#if editorOpen}
   <section id="ai-connection-editor" class="editor" aria-label={t('ai.editor')}>
    {#if editingId && data.profiles.find(p => p.id === editingId)?.revision !== editingRevision}<div class="feedback warning"><p>{t('ai.changedElsewhere')}</p><div class="inline"><button class="secondary-action" disabled={Boolean(busy)} onclick={() => { const latest = data?.profiles.find(p => p.id === editingId); if (latest) openEditor(latest); }}>{t('ai.reopen')}</button><button class="secondary-action" disabled={Boolean(busy)} onclick={() => { editingId = ''; editingRevision = 0; savedProfile = null; draft.name += t('ai.recoveredSuffix'); destinationConfirmed = false; }}>{t('ai.saveAsNew')}</button></div></div>{/if}
    <div class="list-header"><h3>{editingId ? t('ai.editTitle') : t('ai.newTitle')}</h3><button class="secondary-action" disabled={Boolean(busy)} onclick={() => { if (mayLeave()) { editorOpen = false; key = ''; } }}>{t('common.close')}</button></div>
    {#if savedProfile?.id.startsWith('api-legacy-')}<p class="feedback">{t('ai.legacy')}</p>{/if}
    <fieldset disabled={Boolean(busy)}>
     {#if !editingId}<label for="ai-preset">{t('ai.preset')}</label><select id="ai-preset" bind:value={presetId} onchange={e => { presetId = e.currentTarget.value; presetChanged(); }}>{#each presets as preset}<option value={preset.id}>{preset.label}</option>{/each}</select>{/if}
     <div class="form-grid"><div><label for="ai-connection-name">{t('ai.name')}</label><input id="ai-connection-name" bind:value={draft.name} maxlength="100" placeholder={t('ai.namePlaceholder')} /></div><div><label for="ai-protocol">{t('ai.protocol')}</label><select id="ai-protocol" bind:value={draft.protocol} onchange={e => { probe = null; destinationConfirmed = false; if (e.currentTarget.value === 'anthropic_messages') draft.models = draft.models.map(m => ({ ...m, structured_output: 'prompt' })); }}>{#each Object.entries(protocolLabels) as [value, label]}<option {value}>{label}</option>{/each}</select></div></div>
     <label for="ai-base-url">{t('ai.baseUrl')}</label><input id="ai-base-url" type="url" bind:value={draft.base_url} placeholder="https://example.com/v1" oninput={() => { destinationConfirmed = false; probe = null; }} />
     <small class="endpoint">{t('ai.actualRequest')} <code>{endpointPreview(draft.base_url, draft.protocol)}</code></small>
     <div class="form-grid"><div><label for="ai-auth">{t('ai.auth')}</label><select id="ai-auth" bind:value={draft.auth_type} onchange={() => { destinationConfirmed = false; probe = null; }}><option value="none">{t('ai.auth.none')}</option><option value="bearer">{t('ai.auth.bearer')}</option><option value="x-api-key">{t('ai.auth.xkey')}</option></select></div><div><label for="ai-key-storage">{t('ai.keyStorage')}</label><select id="ai-key-storage" bind:value={draft.credential_storage} disabled={draft.auth_type === 'none'}><option value="keychain">{t('ai.keychain')}</option><option value="private_file">{t('ai.privateFile')}</option></select></div></div>
     {#if draft.auth_type !== 'none'}<label for="ai-api-key">{t('ai.apiKey')}</label><input id="ai-api-key" type="password" autocomplete="new-password" bind:value={key} disabled={clearKey} placeholder={savedProfile?.has_api_key ? t('ai.keyKeep') : t('ai.keyNew')} />
      {#if savedProfile?.has_api_key}<label class="check"><input type="checkbox" bind:checked={clearKey} onchange={e => { if (e.currentTarget.checked) key = ''; }} />{t('ai.clearKey')}</label>{/if}
      <small>{savedProfile?.credential_storage === 'legacy' ? t('ai.keyLegacy') : draft.credential_storage === 'private_file' ? t('ai.keyFile') : t('ai.keyKeychain')}</small>
     {/if}
     {#if destinationChanged}<div class="feedback warning"><p>{t('ai.destChanged')}</p><label class="check"><input type="checkbox" bind:checked={destinationConfirmed}/>{t('ai.destConfirm')}</label>{#if savedProfile?.has_api_key && draft.auth_type !== 'none'}<small>{t('ai.destKey')}</small>{/if}</div>{/if}
     <div class="list-header"><h4>{t('ai.models')}</h4><button class="secondary-action" type="button" onclick={() => addModel()}><Plus size={15}/>{t('ai.addModel')}</button></div>
     <div class="inline"><button class="secondary-action" type="button" onclick={discover} disabled={!editingId || dirty || !draft.enabled}>{t('ai.discover')}</button><HelpPopover label={t('ai.discover')} text={t('ai.discoverHelp')} /></div>
     {#if discovered.length}<div class="inline"><select aria-label={t('ai.discovered')} bind:value={discoveredId}>{#each discovered as m (m.id)}<option value={m.id}>{m.label} · {m.id}</option>{/each}</select><button class="secondary-action" type="button" onclick={() => { const m = discovered.find(m => m.id === discoveredId); if (m) addModel(m.id, m.label); }}>{t('ai.addDiscovered')}</button></div>{/if}
     {#each draft.models as model, index}
      <div class="model-row"><div class="model-inputs"><div><label for={`ai-model-id-${index}`}>{t('ai.modelId', { n: index + 1 })}</label><input id={`ai-model-id-${index}`} bind:value={model.id} maxlength="255" placeholder={t('ai.modelIdPlaceholder')} oninput={e => { if (draft.models.length === 1 || draft.default_model_id === model.id) draft.default_model_id = e.currentTarget.value; }} /></div><div><label for={`ai-model-name-${index}`}>{t('ai.modelName')}</label><input id={`ai-model-name-${index}`} bind:value={model.label} maxlength="120" placeholder={t('ai.modelNamePlaceholder')}/></div><button class="icon-button" type="button" aria-label={t('ai.modelRemove', { n: index + 1 })} onclick={() => removeModel(index)}><Trash2 size={15}/></button></div>
       <details><summary>{t('ai.modelAdvanced')}</summary><div class="form-grid"><div><label for={`ai-input-${index}`}>{t('ai.inputBudget')}</label><input id={`ai-input-${index}`} type="number" bind:value={model.max_input_chars} min="256" max="120000"/></div><div><label for={`ai-output-${index}`}>{t('ai.maxOutput')}</label><input id={`ai-output-${index}`} type="number" bind:value={model.max_output_tokens} min="32" max="65536"/></div><div><label for={`ai-temperature-${index}`}>{t('ai.temperature')}</label><input id={`ai-temperature-${index}`} type="number" min="0" max={draft.protocol === 'anthropic_messages' ? 1 : 2} step="0.1" value={model.temperature ?? ''} oninput={e => model.temperature = e.currentTarget.value === '' ? null : Number(e.currentTarget.value)} /></div><div><label for={`ai-json-${index}`}>{t('ai.structured')}</label><select id={`ai-json-${index}`} bind:value={model.structured_output}><option value="prompt">{t('ai.structPrompt')}</option>{#if draft.protocol !== 'anthropic_messages'}<option value="json_schema">{t('ai.structSchema')}</option>{/if}</select></div>
       {#if draft.protocol === 'openai_chat'}<div><label for={`ai-token-${index}`}>{t('ai.tokenField')}</label><select id={`ai-token-${index}`} bind:value={model.token_parameter}><option value="max_tokens">{t('ai.tokenCommon')}</option><option value="max_completion_tokens">max_completion_tokens</option></select></div>{/if}</div><small>{t('ai.budgetNote')}</small></details>
      </div>
     {/each}
     {#if draft.models.length}<label for="profile-default-model">{t('ai.defaultModel')}</label><select id="profile-default-model" bind:value={draft.default_model_id}>{#each draft.models as model}<option value={model.id}>{model.label || model.id || t('ai.modelIdNeeded')}</option>{/each}</select>{/if}
     <details><summary>{t('ai.connAdvanced')}</summary><div class="form-grid"><div><label for="ai-timeout">{t('ai.timeout')}</label><input id="ai-timeout" type="number" bind:value={draft.timeout_seconds} min="5" max="600"/></div><div><label for="ai-concurrency">{t('ai.concurrency')}</label><select id="ai-concurrency" bind:value={draft.max_concurrency}><option value={1}>{t('ai.concurrency1')}</option><option value={2}>2</option><option value={3}>3</option><option value={4}>4</option></select></div><div><label for="ai-local-engine">{t('ai.localCheck')}</label><select id="ai-local-engine" bind:value={draft.local_engine}><option value="generic">{t('ai.generic')}</option><option value="ollama">{t('ai.ollama')}</option></select></div></div><label for="ai-headers">{t('ai.headers')}</label><textarea id="ai-headers" rows="3" bind:value={headersText} spellcheck="false"></textarea><small>{t('ai.headersNote')}</small></details>
     <label class="check"><input type="checkbox" bind:checked={draft.enabled} />{t('ai.enabled')}</label>
    </fieldset>
    <div class="save-row"><small>{dirty ? t('ai.dirty') : editingId ? t('ai.savedState') : t('ai.writing')}</small><button class="primary-action" disabled={Boolean(busy) || !draft.name.trim() || !draft.base_url.trim() || (destinationChanged && !destinationConfirmed)} onclick={saveProfile}><Save size={16}/>{t('ai.save')}</button></div>
    <div class="test-box"><div class="inline-flex items-center gap-1"><h4 class="title-line">{t('ai.test')}</h4><HelpPopover label={t('ai.test')} text={t('ai.testHelp')} /></div><div class="inline"><select aria-label={t('ai.testModel')} bind:value={modelToTest} disabled={Boolean(busy)}><option value="">{t('ai.pickSaved')}</option>{#each savedProfile?.models ?? [] as m}<option value={m.id}>{m.label || m.id}</option>{/each}</select><button class="secondary-action" disabled={Boolean(busy) || !editingId || dirty || !modelToTest || !draft.enabled} onclick={testProfile}><Check size={16}/>{t('ai.testRun')}</button></div>
     {#if probe && !dirty}<div class="feedback" role="status"><strong>{t('ai.status.verified')} · {probe.elapsed_ms.toLocaleString()} ms</strong><p>{probe.model_id} · {probe.instruction_followed ? t('ai.followed') : t('ai.notFollowed')}</p><pre>{probe.content}</pre><small>{t('ai.testScope')}</small></div>{/if}
    </div>
   </section>
  {/if}
  <details class="task-settings"><summary>{t('ai.tasks')}</summary>
   {#if data.revision !== routingRevision && taskDirty}<div class="feedback warning"><p>{t('ai.routesChanged')}</p><button class="secondary-action" disabled={Boolean(busy)} onclick={() => { if (window.confirm(t('ai.confirmReloadRoutes'))) updateData(data!, true); }}>{t('ai.routesReload')}</button></div>{/if}
   {#each taskKeys as task}<label for={`task-${task}`}>{taskLabels[task]}</label><select id={`task-${task}`} bind:value={taskValues[task]} disabled={Boolean(busy)}><option value="">{t('ai.useDefault')}</option>{#if taskValues[task] && !choices.some(c => c.value === taskValues[task])}<option value={taskValues[task]}>{t('ai.previousRoute')}</option>{/if}{#each choices as c (c.value)}<option value={c.value} disabled={c.disabled}>{c.label}</option>{/each}</select>{/each}
   <button class="secondary-action" disabled={Boolean(busy) || !taskDirty} onclick={saveRoutes}>{t('ai.saveRoutes')}</button>
  </details>
 {/if}
</section>

<style>
 .ai-connections { display:grid; gap:20px; padding:22px; border:1px solid var(--border); border-radius:12px; background:var(--card); color:var(--foreground); word-break:keep-all; }
 h2,h3,h4,p { margin:0; } h2 {font-size:19px;} h3 {font-size:16px;} h4 {font-size:14px;}
 p,small {color:var(--muted-foreground); line-height:1.65;} p {font-size:13px;} small {font-size:12px; display:block;}
 .panel-header,.list-header,.save-row,.inline,.profile-actions {display:flex; align-items:center; gap:10px;} .panel-header,.list-header,.save-row {justify-content:space-between;}
 .title-line{display:flex;align-items:center;gap:4px} .panel-header>div,.inline>select {min-width:0;} .inline>select {flex:1;} .inline {flex-wrap:wrap;} .list-header h3 span {font-size:12px; color:var(--muted-foreground); margin-left:5px;}
 .policy,.default-picker,.native-connections,.task-settings,.test-box {background:var(--background); padding:16px; border:1px solid var(--border-soft); border-radius:9px; display:grid; gap:10px;}
 .check {display:flex; align-items:center; gap:8px; font-size:13px;} input[type=checkbox] {width:16px; height:16px; flex:none;}
 label {display:block; font-size:12px; font-weight:600; margin:0 0 5px;} input:not([type=checkbox]),select,textarea {width:100%; min-width:0; max-width:100%; min-height:40px; border:1px solid var(--border); border-radius:6px; padding:9px 10px; background:var(--card); color:var(--foreground); font:inherit; font-size:13px; box-shadow:none;}
 textarea {line-height:1.6;} input:focus-visible,select:focus-visible,textarea:focus-visible,button:focus-visible {outline:2px solid var(--accent); outline-offset:2px;}
 .profile-list {display:grid; border:1px solid var(--border); border-radius:9px; overflow:hidden;}
 .profile-row {display:flex; gap:12px; padding:13px; border-bottom:1px solid var(--border-soft); align-items:center;} .profile-row:last-child {border-bottom:0;} .profile-row.editing {background:var(--accent-soft);}
 .profile-copy {display:grid; gap:3px; min-width:0; flex:1; text-align:left;} .profile-copy strong {display:flex; gap:6px; align-items:center; font-size:14px;} .profile-copy span {font-size:12px; color:var(--muted-foreground);} .profile-copy small {overflow-wrap:anywhere;}
 .profile-actions { flex-wrap:wrap; justify-content:flex-end; max-width:360px; } .checked-model {font-size:11px;overflow-wrap:anywhere;max-width:160px;}
 .badge {padding:4px 7px; border-radius:5px; background:var(--background); color:var(--muted-foreground); font-size:11px;white-space:nowrap;} .badge.blocked {color:var(--warning);}
 .editor {display:grid; gap:16px; border:1px solid var(--accent); border-radius:10px; padding:20px; scroll-margin-top:95px;}
 fieldset {padding:0; margin:0; border:0; min-width:0; display:grid; gap:10px;} .form-grid {display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px;}
 .endpoint {overflow-wrap:anywhere;} .model-row {border:1px solid var(--border-soft); padding:12px; border-radius:8px; display:grid; gap:10px;} .model-inputs {display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto; gap:8px; align-items:end;}
 summary {cursor:pointer; font-size:13px; font-weight:600; padding:5px 0;} details>div,details>small,details>label,details>select,details>button {margin-top:10px;}
 .feedback {padding:12px; border:1px solid var(--border); border-radius:8px; background:var(--accent-soft); font-size:13px; overflow-wrap:anywhere;} .feedback.error,.feedback.warning {border-color:var(--warning);background:var(--background);} .feedback.error {color:var(--warning);} .feedback pre {white-space:pre-wrap; word-break:break-word; font-size:12px; margin:8px 0;}
 .native-row {display:flex; flex-wrap:wrap; gap:12px; align-items:center; padding:12px 0; border-top:1px solid var(--border-soft);} .native-row>div:first-child {flex:1; min-width:200px;} .native-row .feedback {flex-basis:100%;}
 .task-settings>button {justify-self:end;} .empty {padding:18px;} .busy {display:flex; align-items:center; gap:7px; color:var(--muted-foreground); font-size:12px;}
 button:disabled {opacity:.5;cursor:not-allowed;} .save-row {border-top:1px solid var(--border-soft);padding-top:14px;}
 @media(max-width:700px) { .ai-connections {padding:14px;} .panel-header {align-items:flex-start;flex-wrap:wrap;} .profile-row {flex-wrap:wrap;} .profile-copy {flex-basis:100%;} .profile-actions {width:100%;} .profile-actions .badge {margin-right:auto;} .form-grid,.model-inputs {grid-template-columns:minmax(0,1fr);} .model-inputs .icon-button {justify-self:end;} .editor {padding:13px;} .inline>select {flex-basis:100%;} .inline>button {flex:1;} .save-row {flex-wrap:wrap;} }
</style>
