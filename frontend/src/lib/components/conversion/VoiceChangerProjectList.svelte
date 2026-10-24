<script lang="ts">
	import { i18n, t } from '$lib/i18n/index.svelte';
	import { FilePlus, Pencil, Trash2, Wand2 } from '@lucide/svelte';
	import { audioUrl } from '$lib/studio/api';
	import type { VoiceConversionJob, VoiceProfile } from '$lib/studio/types';

	type VoiceChangerProject = {
		id: string;
		title: string;
		voice_id: string;
		model_id: string;
		source_origin?: 'file' | 'youtube' | 'instagram';
		source_page_url?: string | null;
		source_title?: string | null;
		source_duration_seconds?: number | null;
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

	function sourceOriginLabel(origin?: VoiceChangerProject['source_origin']) {
		if (origin === 'youtube') return 'YouTube';
		if (origin === 'instagram') return 'Instagram';
		return t('cover.origin.upload');
	}
</script>

<section class="surface">
	<div class="section-heading">
		<div>
			<h2>{t('cover.list.title')}</h2>
		</div>
		<div class="button-row">
			<button class="primary-action" onclick={onCreate}><FilePlus size={18} />{t('cover.list.new')}</button>
		</div>
	</div>
	<div class="voice-change-project-grid">
		{#each projects as project (project.id)}
			<article class="voice-change-project-card">
				<button class="voice-change-project-main" onclick={() => onOpen(project.id)}>
					<span class="voice-change-project-icon"><Wand2 size={20} /></span>
					<span>
						<strong>{project.title}</strong>
						<small>
							{t('cover.list.versions', { count: project.versions.length })} ·
							{t('cover.list.song', { title: project.source_title || project.source_audio_name || t('cover.list.none') })} ·
							{t('cover.list.origin', { origin: sourceOriginLabel(project.source_origin) })} ·
							{t('cover.list.target', { name: voices.find((voice) => voice.id === project.voice_id)?.name ?? t('cover.list.noVoice') })} ·
							{t('cover.list.edited', { date: new Date(project.updated_at).toLocaleString(i18n.intl) })}
						</small>
						<p>{project.transcript || t('cover.list.noLyrics')}</p>
					</span>
				</button>
				{#if project.versions[0]}
					<div class="story-card-player">
						<span><Wand2 size={16} />{t('cover.list.latest')}</span>
						<audio controls src={audioUrl(project.versions[0].output_audio_url)}></audio>
					</div>
				{:else}
					<div class="story-card-empty">{t('cover.list.noCover')}</div>
				{/if}
				<div class="button-row">
					<button class="secondary-action" onclick={() => onOpen(project.id)}><Pencil size={16} />{t('common.edit')}</button>
					<button class="icon-button danger" aria-label={t('cover.list.delete')} onclick={() => onDelete(project.id)}><Trash2 size={17} /></button>
				</div>
			</article>
		{:else}
			<div class="empty-state">
				<Wand2 size={54} />
				<h3>{t('cover.list.empty')}</h3>
				<button class="primary-action" onclick={onCreate}><FilePlus size={18} />{t('cover.make')}</button>
			</div>
		{/each}
	</div>
</section>