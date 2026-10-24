<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
  import {
    ImagePlus,
    Pencil,
    Plus,
    Save,
    Search,
    Trash2,
    UserRound,
    Wand2,
    AudioLines,
    BookOpenText,
    X,
  } from "@lucide/svelte";
  import { apiFetch, audioUrl, formatDate, formatTime } from "$lib/studio/api";
  import type { VoiceProfile } from "$lib/studio/types";
  import { cloneReadiness } from "$lib/studio/voices";

  let {
    voices,
    selectedVoiceId,
    onSelect,
    onCreate,
    onDelete,
    onUpdate,
    onNotice,
    onUse,
    canUseCover = false,
  }: {
    voices: VoiceProfile[];
    selectedVoiceId: string;
    onSelect: (id: string) => void;
    onCreate: () => void;
    onDelete: (id: string) => Promise<void>;
    onUpdate: (voice: VoiceProfile) => void;
    onNotice: (type: "success" | "error" | "info", text: string) => void;
    onUse: (id: string, target: 'tts' | 'story' | 'changer') => void;
    canUseCover?: boolean;
  } = $props();

  let query = $state("");
  let filter = $state<"all" | "precise" | "missing">("all");
  let editingId = $state("");
  let editName = $state("");
  let editDescription = $state("");
  let editTranscript = $state("");
  let editAvatarPreview = $state<string | null>(null);
  let busyId = $state("");
  let transcribingId = $state("");
  let selectedVoice = $derived(voices.find((voice) => voice.id === selectedVoiceId));
  let preciseCount = $derived(voices.filter((voice) => cloneReadiness(voice).precise).length);
  let filtered = $derived(
    voices.filter((voice) => {
      const target =
        `${voice.name} ${voice.description ?? ""} ${voice.transcript ?? ""}`.toLowerCase();
      if (filter === "precise" && !cloneReadiness(voice).precise) return false;
      if (filter === "missing" && cloneReadiness(voice).precise) return false;
      return target.includes(query.toLowerCase());
    }),
  );

  function range(voice: VoiceProfile) {
    if (!voice.trim_end) return t('voicelib.noRange');
    return `${formatTime(voice.trim_start ?? 0)} - ${formatTime(voice.trim_end)}`;
  }

  function startEdit(voice: VoiceProfile) {
    editingId = voice.id;
    editName = voice.name;
    editDescription = voice.description ?? "";
    editTranscript = voice.transcript ?? "";
    editAvatarPreview = voice.avatar ?? null;
  }

  function cancelEdit() {
    editingId = "";
    editName = "";
    editDescription = "";
    editTranscript = "";
    editAvatarPreview = null;
  }

  async function saveEdit(voice: VoiceProfile) {
    busyId = voice.id;
    try {
      const response = await apiFetch(`/api/voices/${voice.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: editName,
          description: editDescription,
          transcript: editTranscript,
        }),
      });
      const updated = await response.json();
      onUpdate(updated);
      cancelEdit();
      onNotice("success", t('voicelib.updated'));
    } catch (error) {
      onNotice("error", error instanceof Error ? error.message : String(error));
    } finally {
      busyId = "";
    }
  }

  async function autoTranscribe(voice: VoiceProfile) {
    transcribingId = voice.id;
    try {
      const params = new URLSearchParams({ language: voice.language || "ko" });
      if (voice.trim_end) {
        params.set("trim_start", String(voice.trim_start ?? 0));
        params.set("trim_end", String(voice.trim_end));
      }
      const response = await apiFetch(`/api/voices/${voice.id}/transcript-segments?${params}`);
      const payload = await response.json();
      const text = String(payload.text ?? "").trim();
      if (!text) throw new Error(t('voicelib.emptyTranscript'));
      editTranscript = text;
      onNotice("info", t('voicelib.transcribed'));
    } catch (error) {
      onNotice("error", error instanceof Error ? error.message : String(error));
    } finally {
      transcribingId = "";
    }
  }

  async function uploadAvatar(voice: VoiceProfile, event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    busyId = voice.id;
    try {
      editAvatarPreview = URL.createObjectURL(file);
      const form = new FormData();
      form.append("avatar", file);
      const response = await apiFetch(`/api/voices/${voice.id}/avatar`, {
        method: "POST",
        body: form,
      });
      const updated = await response.json();
      onUpdate(updated);
      editAvatarPreview = updated.avatar ?? null;
      onNotice("success", t('voicelib.avatarUpdated'));
    } catch (error) {
      onNotice("error", error instanceof Error ? error.message : String(error));
    } finally {
      input.value = "";
      busyId = "";
    }
  }
</script>

<section class="surface">
  <div class="section-heading">
    <div>
      <h2>{t('voicelib.title')}</h2>
    </div>
    <button class="primary-action" onclick={onCreate}
      ><Plus size={18} />{t('nav.voice.register')}</button
    >
  </div>
  {#if selectedVoice}
    <div class="voice-use-bar">
      <span><strong>{selectedVoice.name}</strong><small>{t('voicelib.selectedHint')}</small></span>
      <div>
        <button class="primary-action" onclick={() => onUse(selectedVoice.id, 'tts')}><AudioLines size={16} />{t('voicelib.narrate')}</button>
        <button class="secondary-action" onclick={() => onUse(selectedVoice.id, 'story')}><BookOpenText size={16} />{t('voicelib.dialogue')}</button>
        <button class="secondary-action" disabled={!canUseCover} onclick={() => onUse(selectedVoice.id, 'changer')}><Wand2 size={16} />{t('voicelib.cover')}</button>
      </div>
    </div>
  {/if}
    <label class="search-box">
      <Search size={18} />
      <input
        bind:value={query}
        placeholder={t('voicelib.searchPlaceholder')}
        aria-label={t('voicelib.searchLabel')}
      />
    </label>
    <div class="voice-filter" role="group" aria-label={t('voicelib.filterLabel')}>
      <button type="button" class:active={filter === "all"} onclick={() => (filter = "all")}>{t('voicelib.filter.all', { count: voices.length })}</button>
      <button type="button" class:active={filter === "precise"} onclick={() => (filter = "precise")}>{t('voicelib.filter.precise', { count: preciseCount })}</button>
      <button type="button" class:active={filter === "missing"} onclick={() => (filter = "missing")}>{t('voicelib.filter.missing', { count: voices.length - preciseCount })}</button>
    </div>
    <div class="voice-card-grid">
      {#each filtered as voice (voice.id)}
        <article
          class="voice-card"
          class:selected={selectedVoiceId === voice.id}
          class:editing={editingId === voice.id}
        >
          <div class="voice-card-head">
            {#if editingId === voice.id}
              <div class="voice-main editing">
                <label
                  class="avatar voice-avatar avatar-edit-trigger"
                  aria-label={t('voicelib.avatarLabel')}
                >
                  {#if editAvatarPreview}
                    <img src={audioUrl(editAvatarPreview)} alt="" />
                  {:else if voice.avatar}
                    <img src={audioUrl(voice.avatar)} alt="" />
                  {:else}
                    <UserRound size={22} />
                  {/if}
                  <span class="avatar-edit-overlay"
                    ><ImagePlus size={13} /></span
                  >
                  <input
                    class="hidden"
                    type="file"
                    accept="image/*"
                    disabled={busyId === voice.id}
                    onchange={(event) => uploadAvatar(voice, event)}
                  />
                </label>
                <span>
                  <strong>{voice.name}</strong>
                  <small>{t('voicelib.avatarHint')}</small>
                </span>
              </div>
            {:else}
              <button class="voice-main" aria-label={t('voicelib.pick', { name: voice.name })} aria-pressed={selectedVoiceId === voice.id} onclick={() => onSelect(voice.id)}>
                <span class="avatar voice-avatar">
                  {#if voice.avatar}
                    <img src={audioUrl(voice.avatar)} alt="" />
                  {:else}
                    <UserRound size={22} />
                  {/if}
                </span>
                <span>
                  <strong>{voice.name}</strong>
                  <small>{range(voice)} · {formatDate(voice.created_at)}</small>
                </span>
              </button>
            {/if}
            <div class="voice-card-actions">
              {#if editingId === voice.id}
                <button
                  class="icon-button"
                  disabled={busyId === voice.id}
                  aria-label={t('voicelib.saveEdit')}
                  onclick={() => saveEdit(voice)}><Save size={17} /></button
                >
                <button
                  class="icon-button"
                  disabled={busyId === voice.id}
                  aria-label={t('voicelib.cancelEdit')}
                  onclick={cancelEdit}><X size={17} /></button
                >
              {:else}
                <button
                  class="icon-button"
                  aria-label={t('voicelib.edit')}
                  onclick={() => startEdit(voice)}><Pencil size={17} /></button
                >
                <button
                  class="icon-button danger"
                  aria-label={t('voicelib.delete')}
                  onclick={() => onDelete(voice.id)}
                  ><Trash2 size={17} /></button
                >
              {/if}
            </div>
          </div>

          {#if editingId === voice.id}
            <div class="voice-edit-form">
              <label
                >{t('voice.script.name')}<input
                  class="studio-input"
                  bind:value={editName}
                /></label
              >
              <label
                >{t('voicelib.description')}<textarea
                  class="studio-input compact-textarea"
                  bind:value={editDescription}
                  placeholder={t('voicelib.descriptionPlaceholder')}
                ></textarea></label
              >
              <label>{t('voicelib.script')}<textarea class="studio-input compact-textarea" bind:value={editTranscript} placeholder={t('voicelib.transcriptPlaceholder')}></textarea></label>
              <button type="button" class="secondary-action mini" disabled={transcribingId === voice.id || busyId === voice.id} onclick={() => autoTranscribe(voice)}>{transcribingId === voice.id ? t('voice.script.busy') : t('voicelib.autoTranscribe')}</button>
            </div>
          {:else}
            <p class="voice-description">
              {voice.description || t('voicelib.noDescription')}
            </p>
            {#if voice.transcript}<p class="voice-transcript">
                {voice.transcript}
              </p>{/if}
            {@const readiness = cloneReadiness(voice)}
            <div class="clone-state" class:precise={readiness.precise}>
              <strong>{readiness.label}</strong>
              <span>{readiness.hint}</span>
              {#if readiness.warning}<em>{readiness.warning}</em>{/if}
              {#if !readiness.precise}<button type="button" onclick={() => startEdit(voice)}>{t('voicelib.addScript')}</button>{/if}
            </div>
          {/if}

          <div class="voice-audio-panel">
            <span>{t('voicelib.reference')}</span>
            {#if voice.audio_url}<audio controls src={audioUrl(voice.audio_url)}
              ></audio>{/if}
          </div>
        </article>
      {:else}
        <div class="empty-state">
          <UserRound size={54} />
          <h3>{t('voicelib.empty')}</h3>
          <button class="primary-action" onclick={onCreate}
            ><Plus size={18} />{t('nav.voice.register')}</button
          >
        </div>
      {/each}
    </div>
</section>

<style>
  .voice-use-bar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px; padding: 14px; margin-bottom: 18px; border: 1px solid #c9dcd7; border-radius: 8px; background: #f3f8f6; }
  .voice-use-bar > span { display: grid; gap: 4px; min-width: 0; }
  .voice-use-bar small { color: #60706d; font-size: 12px; }
  .voice-use-bar > div { display: flex; flex-wrap: wrap; gap: 8px; }
  .voice-filter { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0 4px; }
  .voice-filter button { min-height: 30px; border: 1px solid var(--border); border-radius: 999px; background: var(--card); padding: 0 14px; color: var(--muted-foreground); font-size: 12.5px; cursor: pointer; }
  .voice-filter button.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent-hover); font-weight: 650; }
  .clone-state { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 8px; margin-top: 8px; font-size: 12px; color: var(--muted-foreground); }
  .clone-state strong { color: var(--warning); font-weight: 650; }
  .clone-state.precise strong { color: var(--success); }
  .clone-state em { flex-basis: 100%; color: var(--warning); font-style: normal; }
  .clone-state button { border: 0; background: transparent; padding: 0; color: var(--accent-hover); font-size: 12px; text-decoration: underline; cursor: pointer; }
</style>