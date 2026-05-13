<script lang="ts">
	import { FilePlus, Pencil, Sparkles, Trash2, Volume2 } from 'lucide-svelte';
	import { audioUrl, formatDate, formatTime } from '$lib/studio/api';
	import type { StoryProject } from '$lib/studio/types';

	let {
		projects,
		onCreate,
		onOpen,
		onDelete
	}: {
		projects: StoryProject[];
		onCreate: () => void;
		onOpen: (id: string) => void;
		onDelete: (id: string) => void;
	} = $props();
</script>

<section class="surface">
	<div class="section-heading">
		<div>
			<h2>스토리 오디오</h2>
			<p>화자와 언어가 섞인 단락을 하나의 오디오 프로젝트로 관리합니다.</p>
		</div>
		<button class="primary-action" onclick={onCreate}><FilePlus size={18} />새 스토리</button>
	</div>
	<div class="story-project-grid">
		{#each projects as project (project.id)}
			<article class="story-project-card">
				<button class="story-project-main" onclick={() => onOpen(project.id)}>
					<span class="story-project-icon"><Sparkles size={20} /></span>
					<span>
						<strong>{project.title}</strong>
						<small>{project.segments.length}개 단락 · {project.result ? formatTime(project.result.duration_seconds) : '오디오 미생성'} · 최근 수정 {formatDate(project.updated_at)}</small>
						<p>{project.segments.map((segment) => segment.text).join(' ')}</p>
					</span>
				</button>
				{#if project.result}
					<div class="story-card-player">
						<span><Volume2 size={16} />{project.result.title}</span>
						<audio controls src={audioUrl(project.result.audio_url)}></audio>
					</div>
				{:else}
					<div class="story-card-empty">아직 생성된 오디오가 없습니다.</div>
				{/if}
				<div class="button-row">
					<button class="secondary-action" onclick={() => onOpen(project.id)}><Pencil size={16} />편집</button>
					<button class="icon-button danger" aria-label="스토리북 삭제" onclick={() => onDelete(project.id)}><Trash2 size={17} /></button>
				</div>
			</article>
		{:else}
			<div class="empty-state">
				<Sparkles size={54} />
				<h3>아직 스토리북이 없습니다</h3>
				<p>여러 단락과 화자를 추가하면 긴 내레이션이나 대화형 오디오를 한 번에 관리할 수 있습니다.</p>
				<button class="primary-action" onclick={onCreate}><FilePlus size={18} />새 스토리</button>
			</div>
		{/each}
	</div>
</section>
