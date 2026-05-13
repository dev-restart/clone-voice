<script lang="ts">
	import { FilePlus, Pencil, Trash2, Wand2 } from 'lucide-svelte';
	import { audioUrl } from '$lib/studio/api';
	import type { VoiceConversionJob, VoiceProfile } from '$lib/studio/types';

	type VoiceChangerProject = {
		id: string;
		title: string;
		voice_id: string;
		model_id: string;
		source_audio_url?: string | null;
		source_audio_name?: string | null;
		transcript?: string | null;
		versions: VoiceConversionJob[];
		created_at: string;
		updated_at: string;
	};

	let {
		projects,
		voices,
		onCreate,
		onOpen,
		onDelete
	}: {
		projects: VoiceChangerProject[];
		voices: VoiceProfile[];
		onCreate: () => void;
		onOpen: (id: string) => void;
		onDelete: (id: string) => void;
	} = $props();
</script>

<section class="surface">
	<div class="section-heading">
		<div>
			<h2>보이스 체인저 작업</h2>
			<p>원본 음성, 대상 목소리, 버전별 변환 결과를 한곳에서 비교합니다.</p>
		</div>
		<button class="primary-action" onclick={onCreate}><FilePlus size={18} />새 작업</button>
	</div>
	<div class="voice-change-project-grid">
		{#each projects as project (project.id)}
			<article class="voice-change-project-card">
				<button class="voice-change-project-main" onclick={() => onOpen(project.id)}>
					<span class="voice-change-project-icon"><Wand2 size={20} /></span>
					<span>
						<strong>{project.title}</strong>
						<small>{project.versions.length}개 버전 · 원본 {project.source_audio_name || '미등록'} · 대상 {voices.find((voice) => voice.id === project.voice_id)?.name ?? '목소리 미선택'} · 최근 수정 {new Date(project.updated_at).toLocaleString('ko-KR')}</small>
						<p>{project.transcript || '아직 원본 대본이 없습니다.'}</p>
					</span>
				</button>
				{#if project.versions[0]}
					<div class="story-card-player">
						<span><Wand2 size={16} />최신 변환 결과</span>
						<audio controls src={audioUrl(project.versions[0].output_audio_url)}></audio>
					</div>
				{:else}
					<div class="story-card-empty">아직 생성된 변환 결과가 없습니다.</div>
				{/if}
				<div class="button-row">
					<button class="secondary-action" onclick={() => onOpen(project.id)}><Pencil size={16} />편집</button>
					<button class="icon-button danger" aria-label="작업 삭제" onclick={() => onDelete(project.id)}><Trash2 size={17} /></button>
				</div>
			</article>
		{:else}
			<div class="empty-state">
				<Wand2 size={54} />
				<h3>아직 보이스 체인저 작업이 없습니다</h3>
				<p>원본 음성과 대상 목소리를 고르면 변환 버전을 쌓아가며 품질을 비교할 수 있습니다.</p>
				<button class="primary-action" onclick={onCreate}><FilePlus size={18} />새 작업</button>
			</div>
		{/each}
	</div>
</section>
