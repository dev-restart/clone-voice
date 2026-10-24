<script lang="ts">
	import { i18n, t } from '$lib/i18n/index.svelte';
	import { Copy, FilePlus, Pencil, Search, Sparkles, Trash2, Wand2 } from '@lucide/svelte';
	import TtsTemplatePicker from './TtsTemplatePicker.svelte';
	import type { ProductionTemplate } from '$lib/studio/production';
	import { formatDate } from '$lib/studio/api';
	import type { ContentItem } from '$lib/studio/types';

	let {
		contents,
		onCreate,
		onUseTemplate,
		onDuplicate,
		onOpen,
		onDelete
	}: {
		contents: ContentItem[];
		onCreate: () => void;
		onUseTemplate: (template: ProductionTemplate) => void;
		onDuplicate: (content: ContentItem) => void;
		onOpen: (content: ContentItem) => void;
		onDelete: (content: ContentItem) => void;
	} = $props();
	let query = $state('');
	let filter = $state('all');
	let sort = $state('recent');
	let matchingContents = $derived(contents.filter((content) => {
		const matchesQuery = `${content.title} ${content.source_text}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
		return matchesQuery && (filter === 'all' || (filter === 'generated' ? content.results.length > 0 : content.results.length === 0));
	}).sort((a, b) => sort === 'title' ? a.title.localeCompare(b.title, i18n.intl) : Date.parse(b.updated_at) - Date.parse(a.updated_at)));
</script>

<section class="tts-template-section">
	<div class="dashboard-section-head"><div><h2>{t('tts.list.start')}</h2></div><button class="secondary-action" onclick={onCreate}><FilePlus size={17} />{t('tts.list.new')}</button></div>
	<TtsTemplatePicker onSelect={onUseTemplate} />
</section>
<section class="surface tts-content-list">
	<div class="section-heading">
		<div>
			<h2>{t('tts.list.saved')}</h2>
		</div>
		<div class="button-row">
			<span class="soft-badge">{t('home.count', { count: contents.length })}</span>
			<button class="primary-action" onclick={onCreate}><FilePlus size={18} />{t('tts.list.new')}</button>
		</div>
	</div>
	<div class="tts-library-tools">
		<label class="tts-search"><Search size={17} /><input aria-label={t('tts.list.searchLabel')} placeholder={t('tts.list.searchPlaceholder')} bind:value={query} /></label>
		<div class="segmented-control" aria-label={t('tts.list.filterLabel')}>
			<button class:active={filter === 'all'} aria-pressed={filter === 'all'} onclick={() => (filter = 'all')}>{t('tts.list.all')}</button>
			<button class:active={filter === 'draft'} aria-pressed={filter === 'draft'} onclick={() => (filter = 'draft')}>{t('tts.list.draft')}</button>
			<button class:active={filter === 'generated'} aria-pressed={filter === 'generated'} onclick={() => (filter = 'generated')}>{t('tts.list.generated')}</button>
		</div>
		<select class="studio-input w-auto min-w-40 shrink-0" aria-label={t('tts.list.sortLabel')} bind:value={sort}><option value="recent">{t('tts.list.sortRecent')}</option><option value="title">{t('tts.list.sortTitle')}</option></select>
	</div>
	<p class="tts-search-count" aria-live="polite">{t('tts.list.count', { count: matchingContents.length })}</p>
	<div class="tts-project-rows">
		{#each matchingContents as content (content.id)}
			<article class="content-card tts-content-card">
				<button class="content-card-main" onclick={() => onOpen(content)}>
					<span class="content-card-icon"><Sparkles size={20} /></span>
					<span>
						<strong>{content.title}</strong>
						<small>{t('tts.list.meta', { count: content.results.length, date: formatDate(content.updated_at) })}</small>
						<p>{content.source_text}</p>
					</span>
				</button>
				<div class="button-row">
					<button class="secondary-action" onclick={() => onOpen(content)}><Pencil size={16} />{t('common.edit')}</button>
					<button class="icon-button" aria-label={t('tts.list.duplicate', { title: content.title })} title={t('tts.list.duplicateTitle')} onclick={() => onDuplicate(content)}><Copy size={17} /></button>
					<button class="icon-button danger" aria-label={t('tts.list.delete')} onclick={() => onDelete(content)}><Trash2 size={17} /></button>
				</div>
			</article>
		{:else}
			<div class="empty-state">
				<Wand2 size={54} />
				<h3>{contents.length ? t('tts.list.noMatch') : t('tts.list.none')}</h3>
				{#if contents.length}<button class="secondary-action" onclick={() => { query = ''; filter = 'all'; }}>{t('tts.list.reset')}</button>{:else}<button class="primary-action" onclick={onCreate}><FilePlus size={18} />{t('tts.list.new')}</button>{/if}
			</div>
		{/each}
	</div>
</section>
