<script lang="ts">
	import { Check, Link, Loader2, Mic, SquarePlay, Upload } from '@lucide/svelte';
	import AudioDownload from '$lib/components/AudioDownload.svelte';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import { Button } from '$lib/components/ui/button';
	import { Switch } from '$lib/components/ui/switch';
	import * as Tabs from '$lib/components/ui/tabs';
	import { t } from '$lib/i18n/index.svelte';
	import { formatTime } from '$lib/studio/api';
	import { parseClockTime } from '$lib/studio/voice-sample';

	export type MediaInfo = { platform: 'youtube' | 'instagram'; title: string; duration_seconds: number | null; uploader: string | null; max_duration_seconds: number };

	let {
		recording, recordingSeconds, mediaUrl, mediaTitle, sourceAudioUrl = '', isolateMediaVoice, busy, importingMedia,
		mediaInfo = null, inspectingMedia = false, clipStart = '', clipEnd = '',
		onFileChange, onToggleRecord, onMediaUrlChange, onIsolateMediaVoiceChange, onImportMedia,
		onInspectMedia, onClipChange
	}: {
		recording: boolean; recordingSeconds: number; mediaUrl: string; mediaTitle: string;
		sourceAudioUrl?: string;
		isolateMediaVoice: boolean; busy: boolean; importingMedia: boolean;
		mediaInfo?: MediaInfo | null; inspectingMedia?: boolean; clipStart?: string; clipEnd?: string;
		onFileChange: (event: Event) => void; onToggleRecord: () => void;
		onMediaUrlChange: (value: string) => void;
		onIsolateMediaVoiceChange: (value: boolean) => void; onImportMedia: () => void;
		onInspectMedia: () => void; onClipChange: (start: string, end: string) => void;
	} = $props();

	let source = $state('file');
	const locked = $derived(busy || importingMedia || recording);

	const start = $derived(parseClockTime(clipStart));
	const end = $derived(parseClockTime(clipEnd));
	const rangeInvalid = $derived(Number.isNaN(start) || Number.isNaN(end) || (start !== null && end !== null && end <= start));
	const hasRange = $derived(start !== null || end !== null);
	// A clip is what gets downloaded, so a long video is fine as long as the clip fits the limit.
	const clipSeconds = $derived.by(() => {
		if (!mediaInfo || rangeInvalid) return mediaInfo?.duration_seconds ?? null;
		if (!hasRange) return mediaInfo.duration_seconds;
		const total = mediaInfo.duration_seconds ?? Infinity;
		return Math.min(end ?? total, total) - (start ?? 0);
	});
	const tooLong = $derived(Boolean(mediaInfo && clipSeconds !== null && clipSeconds > mediaInfo.max_duration_seconds));
	const canImport = $derived(!locked && Boolean(mediaUrl.trim()) && !rangeInvalid && !tooLong);
	const minutes = (seconds: number) => Math.round(seconds / 60);
</script>

<div class="source-panel grid min-w-0 gap-4">
	<div class="flex items-center gap-1">
		<h3 class="text-base font-semibold">{t('voice.source.title')}</h3>
		<HelpPopover label={t('voice.source.title')} text={t('voice.source.help')} />
	</div>

	<Tabs.Root bind:value={source}>
		<Tabs.List class="h-auto w-full flex-wrap justify-start sm:w-fit" aria-label={t('voice.source.aria')}>
			<Tabs.Trigger value="file" disabled={locked} class="gap-1.5 px-3 py-1.5"><Upload size={15} aria-hidden="true" />{t('voice.source.file')}</Tabs.Trigger>
			<Tabs.Trigger value="record" disabled={locked && !recording} class="gap-1.5 px-3 py-1.5"><Mic size={15} aria-hidden="true" />{t('voice.source.record')}</Tabs.Trigger>
			<Tabs.Trigger value="link" disabled={locked} class="gap-1.5 px-3 py-1.5"><SquarePlay size={15} aria-hidden="true" />{t('voice.source.link')}</Tabs.Trigger>
		</Tabs.List>

		<Tabs.Content value="file" class="pt-4">
			<label class="secondary-action" class:input-disabled={locked}>
				<Upload size={17} />{t('voice.file.pick')}
				<input class="hidden" type="file" accept="audio/*" disabled={locked} onchange={onFileChange} />
			</label>
		</Tabs.Content>

		<Tabs.Content value="record" class="grid gap-3 pt-4">
			{#if recording}
				<div class="recording-panel" aria-live="polite">
					<span class="recording-dot"></span>
					<strong>{t('voice.record.active', { time: formatTime(recordingSeconds) })}</strong>
					<small>{t('voice.record.hint')}</small>
				</div>
			{/if}
			<div>
				<button class="secondary-action" class:recording disabled={busy || importingMedia} onclick={onToggleRecord}>
					<Mic size={17} />{recording ? t('voice.record.stop') : t('voice.source.record')}
				</button>
			</div>
		</Tabs.Content>

		<Tabs.Content value="link" class="grid gap-4 pt-4">
			<div class="grid gap-1.5">
				<label for="voice-media-url" class="text-sm font-medium">{t('voice.link.label')}</label>
				<div class="flex flex-wrap gap-2">
					<input id="voice-media-url" class="studio-input min-w-0 flex-1" value={mediaUrl} disabled={locked}
						oninput={(event) => onMediaUrlChange(event.currentTarget.value)}
						onkeydown={(event) => { if (event.key === 'Enter' && mediaUrl.trim() && !locked) { event.preventDefault(); onInspectMedia(); } }}
						placeholder={t('voice.link.placeholder')} aria-label={t('voice.link.aria')} />
					<Button variant="outline" disabled={locked || inspectingMedia || !mediaUrl.trim()} onclick={onInspectMedia}>
						{#if inspectingMedia}<Loader2 class="animate-spin" size={15} aria-hidden="true" />{t('voice.link.checking')}{:else}<Check size={15} aria-hidden="true" />{t('voice.link.check')}{/if}
					</Button>
				</div>
			</div>

			{#if mediaInfo}
				<div class="bg-muted/60 border-border grid gap-1 rounded-lg border px-3.5 py-3" role="status">
					<strong class="text-sm break-words">{mediaInfo.title}</strong>
					<span class="text-muted-foreground text-xs">
						{mediaInfo.uploader ? `${mediaInfo.uploader} · ` : ''}{mediaInfo.duration_seconds !== null ? formatTime(mediaInfo.duration_seconds) : t('voice.link.liveOrUnknown')}
					</span>
				</div>
			{/if}

			<div class="grid gap-1.5">
				<div class="flex items-center gap-1">
					<span class="text-sm font-medium">{t('voice.link.range')}</span><span class="text-muted-foreground text-xs">{t('common.optional')}</span>
					<HelpPopover label={t('voice.link.range')} text={t('voice.link.rangeHelp', { max: minutes(mediaInfo?.max_duration_seconds ?? 3600) })} />
				</div>
				<div class="flex flex-wrap items-center gap-2">
					<input class="studio-input w-28" value={clipStart} disabled={locked} placeholder={t('voice.link.start')} aria-label={t('voice.link.start')} oninput={(event) => onClipChange(event.currentTarget.value, clipEnd)} />
					<span class="text-muted-foreground" aria-hidden="true">–</span>
					<input class="studio-input w-28" value={clipEnd} disabled={locked} placeholder={t('voice.link.end')} aria-label={t('voice.link.end')} oninput={(event) => onClipChange(clipStart, event.currentTarget.value)} />
				</div>
				{#if rangeInvalid}<small class="text-danger" role="alert">{t('voice.link.badRange')}</small>{/if}
				{#if tooLong && mediaInfo}<small class="text-warning" role="alert">{t('voice.link.tooLong', { max: minutes(mediaInfo.max_duration_seconds) })}</small>{/if}
			</div>

			<label class="flex cursor-pointer items-center gap-2.5 text-sm">
				<Switch checked={isolateMediaVoice} disabled={locked} onCheckedChange={onIsolateMediaVoiceChange} aria-label={t('voice.link.isolate')} />
				<span>{t('voice.link.isolate')}</span>
			</label>

			<div>
				<Button variant="secondary" disabled={!canImport} onclick={onImportMedia}>
					{#if importingMedia}<Loader2 class="animate-spin" size={16} aria-hidden="true" />{t('voice.link.importing')}{:else}<Link size={16} aria-hidden="true" />{t('voice.link.import')}{/if}
				</Button>
			</div>
		</Tabs.Content>
	</Tabs.Root>

	{#if mediaTitle}
		<div class="imported-audio grid min-w-0 gap-2.5">
			<p class="text-muted-foreground text-xs break-words">{t('voice.link.imported', { title: mediaTitle })}</p>
			{#if sourceAudioUrl && !importingMedia}
				{#key sourceAudioUrl}<AudioDownload path={sourceAudioUrl} filename={mediaTitle} label={t('voice.link.downloadAll')} />{/key}
			{/if}
		</div>
	{/if}
</div>

<style>
	.source-panel { padding: 4px 0; }
	.input-disabled { opacity: .55; cursor: not-allowed; }
</style>
