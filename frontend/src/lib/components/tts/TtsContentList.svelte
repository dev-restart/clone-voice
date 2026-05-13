<script lang="ts">
	import { FilePlus, Pencil, Sparkles, Trash2, Wand2 } from 'lucide-svelte';
	import { formatDate } from '$lib/studio/api';
	import type { ContentItem } from '$lib/studio/types';

	let {
		contents,
		onCreate,
		onOpen,
		onDelete
	}: {
		contents: ContentItem[];
		onCreate: () => void;
		onOpen: (content: ContentItem) => void;
		onDelete: (content: ContentItem) => void;
	} = $props();
</script>

<section class="surface tts-content-list">
	<div class="section-heading">
		<div>
			<h2>TTS 콘텐츠</h2>
			<p>저장한 대본과 생성된 음성 결과를 제목별로 관리합니다.</p>
		</div>
		<div class="button-row">
			<span class="soft-badge">{contents.length}개</span>
			<button class="primary-action" onclick={onCreate}><FilePlus size={18} />새 콘텐츠</button>
		</div>
	</div>
	<div class="content-card-grid">
		{#each contents as content (content.id)}
			<article class="content-card tts-content-card">
				<button class="content-card-main" onclick={() => onOpen(content)}>
					<span class="content-card-icon"><Sparkles size={20} /></span>
					<span>
						<strong>{content.title}</strong>
						<small>생성 결과 {content.results.length}개 · 최근 수정 {formatDate(content.updated_at)}</small>
						<p>{content.source_text}</p>
					</span>
				</button>
				<div class="button-row">
					<button class="secondary-action" onclick={() => onOpen(content)}><Pencil size={16} />편집</button>
					<button class="icon-button danger" aria-label="콘텐츠 삭제" onclick={() => onDelete(content)}><Trash2 size={17} /></button>
				</div>
			</article>
		{:else}
			<div class="empty-state">
				<Wand2 size={54} />
				<h3>아직 저장된 음성 콘텐츠가 없습니다</h3>
				<p>첫 대본을 저장하면 생성 결과, 번역본, 사용한 목소리를 한 카드에서 이어서 관리할 수 있습니다.</p>
				<button class="primary-action" onclick={onCreate}><FilePlus size={18} />새 콘텐츠</button>
			</div>
		{/each}
	</div>
</section>
