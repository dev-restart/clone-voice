<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { onMount } from 'svelte';
	import { Download, FolderDown, Loader2, RefreshCw, UserRound, Wand2 } from '@lucide/svelte';
	import { apiFetch, audioUrl, formatDate, formatFileSize, formatTime } from '$lib/studio/api';
	import type { AudioAsset, AudioAssetCatalog, AudioAssetKind, MenuKey, VoiceProfile } from '$lib/studio/types';
	import AudioDownload from './AudioDownload.svelte';

	let {
		voices,
		onNavigate,
		onNotice
	}: {
		voices: VoiceProfile[];
		onNavigate: (key: MenuKey) => void;
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
	} = $props();

	const STORY_STORAGE_KEY = 'clonevoice.storyStudio.projects.v1';
	const SFX_STORAGE_KEY = 'clonevoice.soundEffects.history.v1';
	const COVER_STORAGE_KEY = 'clonevoice.voiceChanger.projects.v1';
	type AssetFilter = 'identified' | 'all' | AudioAssetKind;
	const FILTERS = $derived<Array<{ key: AssetFilter; label: string }>>([
		{ key: 'identified', label: t('files.filter.identified') },
		{ key: 'all', label: t('files.filter.all') },
		{ key: 'registered-voice', label: t('files.kind.voice') },
		{ key: 'tts', label: 'TTS' },
		{ key: 'dialogue', label: t('nav.story') },
		{ key: 'ai-cover', label: t('nav.changer') },
		{ key: 'sound-effect', label: t('models.domain.sfx') },
		{ key: 'other', label: t('files.kind.other') }
	]);

	type StoryResultRecord = {
		title?: string;
		source_excerpt?: string | null;
		updated_at?: string;
		result?: {
			audio_url?: string;
			duration_seconds?: number | null;
			segments?: Array<{ voice_name?: string | null }>;
		} | null;
	};

	type SoundEffectHistoryRecord = {
		id: string;
		prompt: string;
		audio_url: string;
		duration_seconds: number;
		model_id?: string;
		created_at: string;
	};

	type CoverProjectRecord = {
		title?: string;
		voice_id?: string | null;
		model_id?: string | null;
		source_audio_name?: string | null;
		source_title?: string | null;
		versions?: Array<{
			id: string;
			output_audio_url: string;
			target_voice_id?: string | null;
			model_id?: string | null;
			transcript?: string | null;
			created_at: string;
		}>;
	};

	let loading = $state(true);
	let refreshing = $state(false);
	let catalog = $state<AudioAssetCatalog>({ registered_voices: [], generated_files: [] });
	let query = $state('');
	let filter = $state<AssetFilter>('identified');
	let errorMessage = $state('');
	let visibleGeneratedCount = $state(40);

	let allAssets = $derived([...catalog.registered_voices, ...catalog.generated_files]);
	let filteredAssets = $derived.by(() => {
		const term = query.trim().toLowerCase();
		return allAssets.filter((asset) => {
			if (filter === 'identified' && asset.kind === 'other') return false;
			if (filter !== 'all' && filter !== 'identified' && asset.kind !== filter) return false;
			if (!term) return true;
			return [asset.title, asset.filename, asset.voice_name, asset.model_id, asset.source_title]
				.filter(Boolean)
				.some((value) => value!.toLowerCase().includes(term));
		});
	});
	let visibleVoices = $derived(filteredAssets.filter((asset) => asset.kind === 'registered-voice'));
	let visibleGenerated = $derived(filteredAssets.filter((asset) => asset.kind !== 'registered-voice'));
	let pagedGenerated = $derived(visibleGenerated.slice(0, visibleGeneratedCount));
	let linkedGeneratedCount = $derived(catalog.generated_files.filter((asset) => asset.voice_id || asset.voice_name).length);

	$effect(() => {
		query;
		filter;
		visibleGeneratedCount = 40;
	});

	onMount(() => {
		void loadAssets();
	});

	function kindLabel(kind: AudioAssetKind) {
		if (kind === 'registered-voice') return t('files.kind.voice');
		if (kind === 'tts') return 'TTS';
		if (kind === 'dialogue') return t('nav.story');
		if (kind === 'ai-cover') return t('nav.changer');
		if (kind === 'sound-effect') return t('models.domain.sfx');
		return t('files.kind.other');
	}

	function sourceOriginLabel(asset: AudioAsset) {
		if (asset.kind === 'registered-voice') return t('voicelib.reference');
		if (asset.kind === 'ai-cover') return t('files.origin.song');
		if (asset.kind === 'dialogue') return t('files.origin.dialogue');
		if (asset.kind === 'sound-effect') return t('files.origin.sfx');
		if (asset.kind === 'tts') return t('files.origin.text');
		return t('files.origin.none');
	}

	function downloadHref(path?: string | null) {
		if (!path) return '';
		if (typeof window === 'undefined') return audioUrl(path);
		const url = new URL(audioUrl(path), window.location.origin);
		url.searchParams.set('download', 'true');
		return url.toString();
	}

	function uniqueVoiceNames(items: Array<{ voice_name?: string | null }> = []) {
		return items
			.map((item) => item.voice_name?.trim())
			.filter((name, index, names): name is string => Boolean(name) && names.indexOf(name) === index);
	}

	function referenceVoice(voiceId?: string | null, voiceName?: string | null) {
		const voice = voices.find((item) => item.id === voiceId || (voiceName && item.name === voiceName));
		if (voice) return { name: voice.name, audio_url: voice.audio_url };
		const asset = catalog.registered_voices.find(
			(item) => item.voice_id === voiceId || item.id === voiceId || (voiceName && item.voice_name === voiceName)
		);
		return asset ? { name: asset.voice_name || asset.title, audio_url: asset.audio_url } : null;
	}

	function mergeLocalMetadata(serverCatalog: AudioAssetCatalog): AudioAssetCatalog {
		const generatedMap = new Map(serverCatalog.generated_files.map((item) => [item.audio_url, item]));
		const voiceNameById = new Map(voices.map((voice) => [voice.id, voice.name]));

		try {
			const parsedStories = JSON.parse(window.localStorage.getItem(STORY_STORAGE_KEY) || '[]');
			const stories = Array.isArray(parsedStories) ? (parsedStories as StoryResultRecord[]) : [];
			for (const project of stories) {
				const result = project.result;
				const audioPath = result?.audio_url;
				if (!audioPath) continue;
				const existing = generatedMap.get(audioPath);
				const voiceNames = uniqueVoiceNames(result.segments ?? []);
				generatedMap.set(audioPath, {
					id: existing?.id ?? `dialogue:${project.title ?? audioPath}`,
					kind: 'dialogue',
					title: project.title?.trim() || existing?.title || t('nav.story'),
					filename: existing?.filename || audioPath.split('/').pop() || 'dialogue.wav',
					audio_url: audioPath,
					source_audio_url: existing?.source_audio_url ?? null,
					available: existing?.available ?? false,
					size_bytes: existing?.size_bytes ?? null,
					duration_seconds: existing?.duration_seconds ?? result.duration_seconds ?? null,
					voice_id: existing?.voice_id ?? null,
					voice_name: voiceNames.join(', ') || existing?.voice_name || null,
					model_id: existing?.model_id ?? null,
					source_title: project.source_excerpt?.trim() || existing?.source_title || null,
					transcript: existing?.transcript ?? null,
					trim_start: existing?.trim_start ?? null,
					trim_end: existing?.trim_end ?? null,
					created_at: existing?.created_at ?? project.updated_at ?? new Date().toISOString()
				});
			}
		} catch {
			// local metadata is optional
		}

		try {
			const parsedHistory = JSON.parse(window.localStorage.getItem(SFX_STORAGE_KEY) || '[]');
			const history = Array.isArray(parsedHistory) ? (parsedHistory as SoundEffectHistoryRecord[]) : [];
			for (const entry of history) {
				const existing = generatedMap.get(entry.audio_url);
				generatedMap.set(entry.audio_url, {
					id: existing?.id ?? entry.id,
					kind: 'sound-effect',
					title: entry.prompt,
					filename: existing?.filename || entry.audio_url.split('/').pop() || 'sound-effect.wav',
					audio_url: entry.audio_url,
					source_audio_url: existing?.source_audio_url ?? null,
					available: existing?.available ?? false,
					size_bytes: existing?.size_bytes ?? null,
					duration_seconds: existing?.duration_seconds ?? entry.duration_seconds,
					voice_id: existing?.voice_id ?? null,
					voice_name: existing?.voice_name ?? null,
					model_id: entry.model_id ?? existing?.model_id ?? null,
					source_title: existing?.source_title ?? t('files.origin.sfx'),
					transcript: existing?.transcript ?? null,
					trim_start: existing?.trim_start ?? null,
					trim_end: existing?.trim_end ?? null,
					created_at: existing?.created_at ?? entry.created_at
				});
			}
		} catch {
			// local metadata is optional
		}

		try {
			const parsedProjects = JSON.parse(window.localStorage.getItem(COVER_STORAGE_KEY) || '[]');
			const projects = Array.isArray(parsedProjects) ? (parsedProjects as CoverProjectRecord[]) : [];
			for (const project of projects) {
				for (const version of project.versions ?? []) {
					const existing = generatedMap.get(version.output_audio_url);
					generatedMap.set(version.output_audio_url, {
						id: existing?.id ?? version.id,
						kind: 'ai-cover',
						title: project.title?.trim() || existing?.title || t('nav.changer'),
						filename: existing?.filename || version.output_audio_url.split('/').pop() || 'ai-cover.wav',
						audio_url: version.output_audio_url,
						source_audio_url: existing?.source_audio_url ?? null,
						available: existing?.available ?? false,
						size_bytes: existing?.size_bytes ?? null,
						duration_seconds: existing?.duration_seconds ?? null,
						voice_id: existing?.voice_id ?? version.target_voice_id ?? project.voice_id ?? null,
						voice_name: existing?.voice_name ?? null,
						model_id: existing?.model_id ?? version.model_id ?? project.model_id ?? null,
						source_title: project.source_title || project.source_audio_name || existing?.source_title || t('files.origin.song'),
						transcript: version.transcript ?? existing?.transcript ?? null,
						trim_start: existing?.trim_start ?? null,
						trim_end: existing?.trim_end ?? null,
						created_at: existing?.created_at ?? version.created_at
					});
				}
			}
		} catch {
			// local metadata is optional
		}

		const mergedGenerated = [...generatedMap.values()]
			.map((asset) => ({
				...asset,
				voice_name: asset.voice_name || (asset.voice_id ? voiceNameById.get(asset.voice_id) ?? null : null)
			}))
			.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

		return {
			registered_voices: [...serverCatalog.registered_voices].sort(
				(a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
			),
			generated_files: mergedGenerated
		};
	}

	async function loadAssets(options: { silent?: boolean } = {}) {
		errorMessage = '';
		if (options.silent) {
			refreshing = true;
		} else {
			loading = true;
		}
		try {
			const response = await apiFetch('/api/assets');
			const payload: AudioAssetCatalog = await response.json();
			catalog = mergeLocalMetadata(payload);
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : String(error);
			onNotice('error', errorMessage);
		} finally {
			loading = false;
			refreshing = false;
		}
	}
</script>

<section class="asset-library surface">
	<div class="section-heading">
		<div>
			<h2>{t('files.title')}</h2>
		</div>
		<div class="button-row wrap">
			<button class="secondary-action" onclick={() => onNavigate('voices')}><UserRound size={17} />{t('files.voices')}</button>
			<button class="secondary-action" onclick={() => onNavigate('changer')}><Wand2 size={17} />{t('cover.make')}</button>
			<button class="secondary-action" disabled={refreshing} onclick={() => loadAssets({ silent: true })}>
				{#if refreshing}<Loader2 class="spin" size={17} />{t('files.refreshing')}{:else}<RefreshCw size={17} />{t('common.refresh')}{/if}
			</button>
		</div>
	</div>

	<div class="asset-toolbar">
		<label class="asset-search">
			<span class="field-label">{t('files.search')}</span>
			<input
				class="studio-input"
				type="search"
				bind:value={query}
				placeholder={t('files.searchPlaceholder')}
				aria-label={t('files.searchLabel')}
			/>
		</label>
		<div class="asset-filter-group" aria-label={t('files.filterLabel')}>
			{#each FILTERS as item (item.key)}
				<button class:active={filter === item.key} aria-pressed={filter === item.key} onclick={() => (filter = item.key)}>{item.label}</button>
			{/each}
		</div>
	</div>
	<p class="asset-summary-line" aria-label={t('files.summary')}>
		<span>{t('files.kind.voice')} <strong>{catalog.registered_voices.length}</strong></span>
		<span>{t('files.finished')} <strong>{catalog.generated_files.length}</strong></span>
		<span>{t('files.linked')} <strong>{linkedGeneratedCount}</strong></span>
	</p>

	{#if loading}
		<div class="empty-panel">
			<Loader2 class="spin" size={26} />
			<strong>{t('files.loading')}</strong>
		</div>
	{:else if errorMessage}
		<div class="asset-error" role="alert">
			<strong>{t('files.loadFail')}</strong>
			<p>{errorMessage}</p>
			<button class="secondary-action" onclick={() => loadAssets()}>{t('tts.queue.retry')}</button>
		</div>
	{:else if !filteredAssets.length}
		<div class="empty-panel">
			<FolderDown size={28} />
			<strong>{t('files.empty')}</strong>
		</div>
	{:else}
		{#if visibleVoices.length}
			<section class="asset-section">
				<div class="section-heading compact-heading">
					<div>
						<h3>{t('files.kind.voice')}</h3>
					</div>
					<span class="soft-badge">{t('home.count', { count: visibleVoices.length })}</span>
				</div>
				<div class="asset-grid">
					{#each visibleVoices as asset (asset.id)}
						<article class="asset-card">
							<div class="asset-card-top">
								<span class="soft-badge">{kindLabel(asset.kind)}</span>
								<span class:missing={!asset.available} class="asset-status">{asset.available ? t('files.available') : t('files.missing')}</span>
							</div>
							<div class="asset-card-copy">
								<strong>{asset.title}</strong>
								<p>{asset.filename}</p>
							</div>
							<div class="asset-meta">
								<span>{sourceOriginLabel(asset)} · {asset.source_title || t('files.noSample')}</span>
								<span>{formatTime(asset.duration_seconds)} · {formatFileSize(asset.size_bytes)}</span>
								<span>{formatDate(asset.created_at)}</span>
							</div>
							{#if asset.transcript}
								<p class="asset-transcript">{asset.transcript}</p>
							{/if}
							{#if asset.available}
								<audio controls preload="none" src={audioUrl(asset.audio_url)} aria-label={t('files.listenRef', { title: asset.title })}></audio>
							{:else}
								<p class="asset-missing-note">{t('files.refMissing')}</p>
							{/if}
							<div class="button-row wrap">
								{#if asset.available}<a class="secondary-action" href={downloadHref(asset.audio_url)} download={asset.filename} aria-label={t('files.downloadRefLabel', { title: asset.title })}><Download size={16} />{t('files.downloadRef')}</a>{/if}
								{#if asset.source_audio_url}
									<a class="secondary-action" href={downloadHref(asset.source_audio_url)} download aria-label={t('files.downloadOrigLabel', { title: asset.title })}>{t('files.downloadOrig')}</a>
								{/if}
							</div>
						</article>
					{/each}
				</div>
			</section>
		{/if}

		{#if visibleGenerated.length}
			<section class="asset-section">
				<div class="section-heading compact-heading">
					<div>
						<h3>{t('files.finished')}</h3>
					</div>
					<span class="soft-badge">{t('home.count', { count: visibleGenerated.length })}</span>
				</div>
				<div class="asset-list">
					{#each pagedGenerated as asset (asset.id)}
						{@const targetVoice = referenceVoice(asset.voice_id, asset.voice_name)}
						<article class="asset-row">
							<div class="asset-row-copy">
								<div class="asset-row-badges">
									<span class="soft-badge">{kindLabel(asset.kind)}</span>
									{#if asset.voice_name}<span class="soft-badge accent">{asset.voice_name}</span>{/if}
								</div>
								<strong>{asset.title}</strong>
								<p>{asset.filename}</p>
								<div class="asset-meta">
									<span>{sourceOriginLabel(asset)} · {asset.source_title || t('files.noInfo')}</span>
									{#if ['tts', 'dialogue', 'ai-cover'].includes(asset.kind)}<span>{t('files.voiceUsed')} · <strong>{asset.voice_name || t('files.voiceNone')}</strong></span>{/if}
									<span>{formatTime(asset.duration_seconds)} · {formatFileSize(asset.size_bytes)}</span>
									<span>{formatDate(asset.created_at)}</span>
								</div>
								{#if asset.kind === 'other'}
									<p class="field-helper">{t('files.unlinked')}</p>
								{/if}
							</div>
							<div class="asset-row-player">
								{#if asset.available}
									<audio controls preload="none" src={audioUrl(asset.audio_url)} aria-label={t('files.listenResult', { title: asset.title })}></audio>
								{:else}
									<p class="asset-missing-note">{t('files.fileMissing')}</p>
								{/if}
								{#if targetVoice?.audio_url}
									<details class="asset-reference">
										<summary>{t('files.compare', { name: targetVoice.name })}</summary>
										<audio controls preload="none" src={audioUrl(targetVoice.audio_url)} aria-label={t('files.listenRef', { title: targetVoice.name })}></audio>
									</details>
								{/if}
								<div class="button-row wrap">
									{#if asset.available}<AudioDownload path={asset.audio_url} filename={asset.filename} label={t('files.resultName', { title: asset.title })} />{/if}
									{#if asset.source_audio_url}
										<a class="secondary-action" href={downloadHref(asset.source_audio_url)} download aria-label={t('files.downloadSourceLabel', { title: asset.title })}>{t('files.downloadSource')}</a>
									{/if}
								</div>
							</div>
						</article>
					{/each}
					{#if pagedGenerated.length < visibleGenerated.length}
						<button class="secondary-action asset-load-more" onclick={() => (visibleGeneratedCount += 40)}>{t('files.more', { count: visibleGenerated.length - pagedGenerated.length })}</button>
					{/if}
				</div>
			</section>
		{/if}
	{/if}
</section>

<style>
	.asset-library {
		display: grid;
		gap: 20px;
		padding: 24px;
	}

	.asset-toolbar {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 14px;
		align-items: end;
	}

	.asset-summary-line {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 18px;
		margin: -6px 0 0;
		color: var(--muted-foreground);
		font-size: 12px;
	}

	.asset-summary-line span + span {
		border-left: 1px solid var(--border-soft);
		padding-left: 18px;
	}

	.asset-summary-line strong {
		margin-left: 4px;
		color: var(--foreground);
		font-weight: 650;
	}

	.asset-search {
		display: grid;
		gap: 8px;
	}

	.asset-filter-group {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.asset-filter-group button {
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--card-elevated);
		padding: 8px 12px;
		color: var(--muted-foreground);
	}

	.asset-filter-group button:hover {
		background: var(--muted);
		color: var(--foreground);
	}

	.asset-filter-group button.active {
		border-color: var(--primary);
		background: var(--primary);
		color: var(--primary-foreground);
	}

	.asset-section {
		display: grid;
		gap: 14px;
	}

	.asset-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
		gap: 14px;
	}

	.asset-card,
	.asset-row {
		border: 1px solid var(--border-soft);
		border-radius: var(--radius-lg);
		background: var(--card-elevated);
		padding: 16px;
	}

	.asset-card {
		display: grid;
		gap: 12px;
	}

	.asset-card-top,
	.asset-row-badges {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
	}

	.asset-card-copy p,
	.asset-row-copy p {
		margin: 4px 0 0;
		color: var(--muted-foreground);
		word-break: break-word;
	}

	.asset-status {
		color: var(--success);
		font-size: 13px;
	}

	.asset-status.missing {
		color: var(--danger);
	}

	.asset-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 14px;
		color: var(--muted-foreground);
		font-size: 13px;
	}

	.asset-transcript {
		margin: 0;
		color: var(--foreground);
		font-size: 14px;
		line-height: 1.55;
	}

	.asset-list {
		display: grid;
		gap: 12px;
	}

	.asset-row {
		display: grid;
		grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
		gap: 16px;
		align-items: center;
	}

	.asset-row-copy {
		display: grid;
		gap: 10px;
	}

	.asset-row-player {
		display: grid;
		gap: 10px;
	}

	.asset-reference summary {
		cursor: pointer;
		color: var(--accent-hover);
		font-size: 13px;
	}

	.asset-reference audio {
		margin-top: 8px;
	}

	.asset-missing-note {
		margin: 0;
		color: var(--warning);
		font-size: 13px;
	}

	.asset-error {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 6px 14px;
		align-items: center;
		border: 1px solid var(--danger-border);
		border-radius: var(--radius-md);
		background: var(--danger-soft);
		padding: 14px;
		color: var(--danger);
	}

	.asset-error p {
		margin: 0;
		font-size: 12px;
	}

	.asset-error button {
		grid-column: 2;
		grid-row: 1 / span 2;
	}

	.asset-load-more {
		justify-self: center;
	}

	.soft-badge.accent {
		background: var(--accent-soft);
		color: var(--accent-hover);
	}

	@media (max-width: 960px) {
		.asset-toolbar,
		.asset-row {
			grid-template-columns: 1fr;
		}

		.asset-error {
			grid-template-columns: 1fr;
		}

		.asset-error button {
			grid-column: 1;
			grid-row: auto;
			justify-self: start;
		}

		.asset-summary-line span + span {
			border-left: 0;
			padding-left: 0;
		}
	}
</style>
