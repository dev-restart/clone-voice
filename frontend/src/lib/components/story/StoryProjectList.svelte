<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { FilePlus, Pencil, Sparkles, Trash2, Volume2 } from '@lucide/svelte';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import { localizedRecord } from '$lib/i18n/core';
	import { audioUrl, formatDate, formatTime } from '$lib/studio/api';
	import type { StoryDialogueFormat, StoryProject } from '$lib/studio/types';

	const dialogueFormatLabels: Record<StoryDialogueFormat, string> = localizedRecord({
		'deep-dive': 'story.format.deep-dive',
		interview: 'story.format.interview',
		debate: 'story.format.debate',
		briefing: 'story.format.briefing'
	});

	function excerptFor(project: StoryProject) {
		const sourceExcerpt = project.source_excerpt?.trim();
		if (sourceExcerpt) return sourceExcerpt;
		return project.segments.map((segment) => segment.text).join(' ');
	}

	let {
		projects,
		onCreate,
		onCreateAi,
		onOpen,
		onDelete
	}: {
		projects: StoryProject[];
		onCreate: () => void;
		onCreateAi: () => void;
		onOpen: (id: string) => void;
		onDelete: (id: string) => void;
	} = $props();
</script>

<section class="surface">
	<div class="story-project-hero">
		<div class="story-project-hero-copy">
			<div class="inline-flex items-center gap-1"><h2 class="inline-flex items-center gap-1">{t('nav.story')}</h2><HelpPopover label={t('nav.story')} text={t('story.list.help')} /></div>
		</div>
		<div class="story-project-hero-actions">
			<button class="primary-action" onclick={onCreateAi}><Sparkles size={18} />{t('story.list.ai')}</button>
			<button class="secondary-action" onclick={onCreate}><FilePlus size={18} />{t('story.list.write')}</button>
		</div>
	</div>
	<div class="story-project-grid">
		{#each projects as project (project.id)}
			<article class="story-project-card">
				<button class="story-project-main" onclick={() => onOpen(project.id)}>
					<span class="story-project-icon"><Sparkles size={20} /></span>
					<span>
						<strong>{project.title}</strong>
						<small>{t('story.list.meta', { segments: project.segments.length, duration: project.result ? formatTime(project.result.duration_seconds) : t('story.list.noAudio'), date: formatDate(project.updated_at) })}</small>
						{#if project.dialogue_format || project.source_excerpt}
							<div class="story-project-meta">
								{#if project.dialogue_format}<span>{dialogueFormatLabels[project.dialogue_format]}</span>{/if}
								{#if project.source_excerpt}<span>{t('story.list.fromSource')}</span>{/if}
							</div>
						{/if}
						<p>{excerptFor(project)}</p>
					</span>
				</button>
				{#if project.result}
					<div class="story-card-player">
						<span><Volume2 size={16} />{project.result.title}</span>
						<audio controls src={audioUrl(project.result.audio_url)}></audio>
					</div>
				{:else}
					<div class="story-card-empty">{t('story.list.noAudioYet')}</div>
				{/if}
					<div class="button-row">
						<button class="secondary-action" aria-label={t('ai.editLabel', { name: project.title })} onclick={() => onOpen(project.id)}><Pencil size={16} />{t('common.edit')}</button>
						<button class="icon-button danger" aria-label={t('ai.deleteLabel', { name: project.title })} onclick={() => onDelete(project.id)}><Trash2 size={17} /></button>
					</div>
			</article>
		{:else}
			<div class="empty-state">
				<Sparkles size={54} />
				<h3>{t('story.list.empty')}</h3>
				<div class="button-row">
					<button class="primary-action" onclick={onCreateAi}><Sparkles size={18} />{t('story.list.paste')}</button>
					<button class="secondary-action" onclick={onCreate}><FilePlus size={18} />{t('story.list.blank')}</button>
				</div>
			</div>
		{/each}
	</div>
</section>
