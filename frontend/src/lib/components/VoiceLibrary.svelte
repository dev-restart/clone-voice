<script lang="ts">
  import {
    ImagePlus,
    Pencil,
    Plus,
    Save,
    Search,
    Trash2,
    UserRound,
    Wand2,
    X,
  } from "lucide-svelte";
  import { apiFetch, audioUrl, formatDate, formatTime } from "$lib/studio/api";
  import type { VoiceProfile } from "$lib/studio/types";

  let {
    voices,
    selectedVoiceId,
    onSelect,
    onCreate,
    onDelete,
    onUpdate,
    onNotice,
  }: {
    voices: VoiceProfile[];
    selectedVoiceId: string;
    onSelect: (id: string) => void;
    onCreate: () => void;
    onDelete: (id: string) => Promise<void>;
    onUpdate: (voice: VoiceProfile) => void;
    onNotice: (type: "success" | "error" | "info", text: string) => void;
  } = $props();

  let query = $state("");
  let tab = $state<"mine" | "defaults">("mine");
  let editingId = $state("");
  let editName = $state("");
  let editDescription = $state("");
  let editAvatarPreview = $state<string | null>(null);
  let busyId = $state("");
  const defaultPresets = [
    {
      name: "Korean Female Narrator",
      desc: "차분한 한국어 여성 내레이션",
      tags: ["female", "moderate pitch", "korean accent"],
    },
    {
      name: "Korean Male Guide",
      desc: "신뢰감 있는 남성 안내 음성",
      tags: ["male", "low pitch", "korean accent"],
    },
    {
      name: "Bright Child",
      desc: "밝고 높은 피치의 아이 목소리 프리셋",
      tags: ["child", "high pitch"],
    },
    {
      name: "English Storyteller",
      desc: "영어 스토리텔링용 미국식 억양",
      tags: ["young adult", "american accent"],
    },
  ];
  let filtered = $derived(
    voices.filter((voice) => {
      const target =
        `${voice.name} ${voice.description ?? ""} ${voice.transcript ?? ""}`.toLowerCase();
      return target.includes(query.toLowerCase());
    }),
  );

  function range(voice: VoiceProfile) {
    if (!voice.trim_end) return "구간 미설정";
    return `${formatTime(voice.trim_start ?? 0)} - ${formatTime(voice.trim_end)}`;
  }

  function startEdit(voice: VoiceProfile) {
    editingId = voice.id;
    editName = voice.name;
    editDescription = voice.description ?? "";
    editAvatarPreview = voice.avatar ?? null;
  }

  function cancelEdit() {
    editingId = "";
    editName = "";
    editDescription = "";
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
        }),
      });
      const updated = await response.json();
      onUpdate(updated);
      cancelEdit();
      onNotice("success", "목소리 정보를 수정했습니다.");
    } catch (error) {
      onNotice("error", error instanceof Error ? error.message : String(error));
    } finally {
      busyId = "";
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
      onNotice("success", "아바타 이미지를 수정했습니다.");
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
      <h2>음성 라이브러리</h2>
      <p>제작에 사용할 기준 목소리와 프리셋을 관리합니다.</p>
    </div>
    <button class="primary-action" onclick={onCreate}
      ><Plus size={18} />새 목소리</button
    >
  </div>
  <div class="tabs">
    <button class:active={tab === "mine"} onclick={() => (tab = "mine")}
      >나의 목소리</button
    >
    <button class:active={tab === "defaults"} onclick={() => (tab = "defaults")}
      >기본 음성</button
    >
  </div>
  {#if tab === "mine"}
    <label class="search-box">
      <Search size={18} />
      <input
        bind:value={query}
        placeholder="이름, 설명, 대본으로 목소리 검색"
      />
    </label>
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
                  aria-label="아바타 이미지 수정"
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
                  <small>아바타를 눌러 이미지를 수정할 수 있습니다.</small>
                </span>
              </div>
            {:else}
              <button class="voice-main" onclick={() => onSelect(voice.id)}>
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
                  aria-label="수정 저장"
                  onclick={() => saveEdit(voice)}><Save size={17} /></button
                >
                <button
                  class="icon-button"
                  disabled={busyId === voice.id}
                  aria-label="수정 취소"
                  onclick={cancelEdit}><X size={17} /></button
                >
              {:else}
                <button
                  class="icon-button"
                  aria-label="목소리 수정"
                  onclick={() => startEdit(voice)}><Pencil size={17} /></button
                >
                <button
                  class="icon-button danger"
                  aria-label="목소리 삭제"
                  onclick={() => onDelete(voice.id)}
                  ><Trash2 size={17} /></button
                >
              {/if}
            </div>
          </div>

          {#if editingId === voice.id}
            <div class="voice-edit-form">
              <label
                >목소리 타이틀<input
                  class="studio-input"
                  bind:value={editName}
                /></label
              >
              <label
                >설명<textarea
                  class="studio-input compact-textarea"
                  bind:value={editDescription}
                  placeholder="이 목소리의 톤, 용도, 특징을 적어두세요."
                ></textarea></label
              >
            </div>
          {:else}
            <p class="voice-description">
              {voice.description || "설명이 없습니다."}
            </p>
            {#if voice.transcript}<p class="voice-transcript">
                {voice.transcript}
              </p>{/if}
          {/if}

          <div class="voice-audio-panel">
            <span>녹음 음성</span>
            {#if voice.audio_url}<audio controls src={audioUrl(voice.audio_url)}
              ></audio>{/if}
          </div>
        </article>
      {:else}
        <div class="empty-state">
          <UserRound size={54} />
          <h3>아직 등록된 목소리가 없습니다</h3>
          <p>
            깨끗한 5~10초 샘플을 등록하면 TTS, 스토리, 보이스 체인저에서 바로
            사용할 수 있습니다.
          </p>
          <button class="primary-action" onclick={onCreate}
            ><Plus size={18} />새 목소리</button
          >
        </div>
      {/each}
    </div>
  {:else}
    <div class="preset-grid">
      {#each defaultPresets as preset (preset.name)}
        <article class="preset-card">
          <div class="preset-avatar"><Wand2 size={22} /></div>
          <h3>{preset.name}</h3>
          <p>{preset.desc}</p>
          <div class="tag-row">
            {#each preset.tags as tag (tag)}<span>{tag}</span>{/each}
          </div>
        </article>
      {/each}
    </div>
  {/if}
</section>
