<script lang="ts">
	import { i18n, t } from '$lib/i18n/index.svelte';
	import { browser } from '$app/environment';
	import { onDestroy, onMount, tick } from 'svelte';
	import { ArrowLeft, FileAudio, Link2, Loader2, Pause, Play, RotateCcw, Wand2 } from '@lucide/svelte';
	import WaveSurfer from 'wavesurfer.js';
	import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import { apiFetch, apiWebSocketUrl, audioUrl, formatTime } from '$lib/studio/api';
	import ProgressPanel from '$lib/components/app/ProgressPanel.svelte';
	import ProductionAssistPanel from '$lib/components/app/ProductionAssistPanel.svelte';
	import type { ProductionAssistResponse } from '$lib/studio/ai-prompts';
	import VoiceChangerProjectList from '$lib/components/conversion/VoiceChangerProjectList.svelte';
	import VoiceChangerResultsPanel from '$lib/components/conversion/VoiceChangerResultsPanel.svelte';
	import VoiceChangerSettingsPanel from '$lib/components/conversion/VoiceChangerSettingsPanel.svelte';
	import AudioDownload from '$lib/components/AudioDownload.svelte';
	import type { RuntimeModelStatus, VoiceConversionJob, VoiceProfile } from '$lib/studio/types';

	let {
		voices,
		models,
		defaultVcModelId = 'soulx-singer',
		defaultSttProvider = 'apple-speech',
		defaultVoiceId = '',
		startWithVoice = false,
		onNotice
	}: {
		voices: VoiceProfile[];
		models: RuntimeModelStatus[];
		defaultVcModelId?: string;
		defaultSttProvider?: 'apple-speech' | 'whisper';
		defaultVoiceId?: string;
		startWithVoice?: boolean;
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
	} = $props();

	type VoiceChangerProject = {
		id: string;
		title: string;
		voice_id: string;
		model_id: string;
		quality?: 'fast' | 'balanced' | 'quality';
		cfg_scale?: number;
		auto_shift?: boolean;
		pitch_shift?: number;
		separate_vocals?: boolean;
		mix_accompaniment?: boolean;
		seed?: number;
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

	const STORAGE_KEY = 'clonevoice.voiceChanger.projects.v1';

	let mode = $state<'list' | 'detail'>('list');
	let projects = $state<VoiceChangerProject[]>([]);
	let selectedProjectId = $state('');
	let title = $state('');
	let file = $state<File | null>(null);
	let voiceId = $state('');
	let modelId = $state('');
	let quality = $state<'fast' | 'balanced' | 'quality'>('balanced');
	let cfgScale = $state(2.0);
	let autoShift = $state(true);
	let pitchShift = $state(0);
	let separateVocals = $state(true);
	let mixAccompaniment = $state(true);
	let seed = $state(42);
	let sttProvider = $state<'whisper' | 'apple-speech'>('apple-speech');
	let sttLanguage = $state('ko');
	let busy = $state(false);
	let transcribing = $state(false);
	let savingSource = $state(false);
	let importingMedia = $state(false);
	let mediaUrl = $state('');
	let mediaImportError = $state('');
	let outputUrl = $state('');
	let history = $state<VoiceConversionJob[]>([]);
	let projectVersions = $state<VoiceConversionJob[]>([]);
	let transcript = $state('');
	let previewUrl = $state('');
	let duration = $state(0);
	let trimStart = $state(0);
	let trimEnd = $state(10);
	let waveformEl = $state<HTMLDivElement | null>(null);
	let wave: WaveSurfer | null = null;
	let regions: ReturnType<typeof RegionsPlugin.create> | null = null;
	let activeRegion: any = null;
	let progress = $state({ percent: 0, message: '', elapsed: 0, active: false });
	let vcModels = $derived(models.filter((model) => model.capabilities.voice_conversion));
	let selectedVoiceId = $derived(voiceId);
	let selectedVoice = $derived(voices.find((voice) => voice.id === selectedVoiceId));
	let selectedProject = $derived(projects.find((project) => project.id === selectedProjectId) ?? null);
	let selectedModel = $derived(vcModels.find((model) => model.id === modelId));
	let selectedDuration = $derived(Math.max(0, trimEnd - trimStart));
	let selectionTooShort = $derived(previewUrl && selectedDuration < 1);
	let canConvert = $derived(
		Boolean(file && selectedVoiceId && selectedModel?.status === 'available' && !selectionTooShort && !savingSource && !importingMedia)
	);
	let generationSteps = $derived(quality === 'fast' ? 2 : quality === 'quality' ? 8 : 4);
	let timelineTicks = $derived.by(() => {
		if (!duration) return [];
		const segments = Math.min(8, Math.max(2, Math.ceil(duration)));
		return Array.from({ length: segments + 1 }, (_, index) => (duration / segments) * index);
	});

	onMount(() => {
		sttProvider = defaultSttProvider;
		modelId = vcModels.find((model) => model.id === defaultVcModelId)?.id ?? vcModels[0]?.id ?? 'soulx-singer';
		projects = loadProjects();
		voiceId = voices.some((voice) => voice.id === defaultVoiceId) ? defaultVoiceId : '';
		if (startWithVoice) startNew();
		void loadHistory();
	});

	onDestroy(() => {
		wave?.destroy();
		if (previewUrl) URL.revokeObjectURL(previewUrl);
	});

	function loadProjects() {
		if (!browser) return [];
		try {
			const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '[]');
			return Array.isArray(parsed) ? (parsed as VoiceChangerProject[]) : [];
		} catch {
			return [];
		}
	}

	function persistProjects(nextProjects = projects) {
		if (!browser) return;
		window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextProjects));
	}

	function createProject(): VoiceChangerProject {
		const now = new Date().toISOString();
		return {
			id: crypto.randomUUID(),
			title: t('cover.newTitle', { time: new Date().toLocaleString(i18n.intl, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }),
			voice_id: selectedVoiceId,
			model_id: modelId,
			quality,
			cfg_scale: cfgScale,
			auto_shift: autoShift,
			pitch_shift: pitchShift,
			separate_vocals: separateVocals,
			mix_accompaniment: mixAccompaniment,
			seed,
			source_origin: 'file',
			source_page_url: null,
			source_title: null,
			source_duration_seconds: null,
			source_audio_url: null,
			source_audio_name: null,
			transcript: '',
			versions: [],
			created_at: now,
			updated_at: now
		};
	}

	function startNew() {
		voiceId = voices.some((voice) => voice.id === defaultVoiceId) ? defaultVoiceId : '';
		modelId = vcModels.find((model) => model.id === defaultVcModelId)?.id ?? vcModels[0]?.id ?? 'soulx-singer';
		const project = createProject();
		const nextProjects = [project, ...projects];
		projects = nextProjects;
		persistProjects(nextProjects);
		openProject(project.id, nextProjects);
	}

	function openProject(id: string, sourceProjects = projects) {
		const project = sourceProjects.find((item) => item.id === id);
		if (!project) return;
		selectedProjectId = project.id;
		title = project.title;
		voiceId = project.voice_id || voiceId;
		modelId = vcModels.some((model) => model.id === project.model_id)
			? project.model_id
			: vcModels.find((model) => model.id === defaultVcModelId)?.id ?? vcModels[0]?.id ?? 'soulx-singer';
		quality = project.quality ?? 'balanced';
		cfgScale = project.cfg_scale ?? 2.0;
		autoShift = project.auto_shift ?? true;
		pitchShift = project.pitch_shift ?? 0;
		separateVocals = project.separate_vocals ?? true;
		mixAccompaniment = project.mix_accompaniment ?? true;
		seed = project.seed ?? 42;
		transcript = project.transcript ?? '';
		projectVersions = project.versions ?? [];
		outputUrl = projectVersions[0]?.output_audio_url ?? '';
		mediaUrl = project.source_page_url ?? '';
		mediaImportError = '';
		mode = 'detail';
		void restoreSourceFromProject(project);
	}

	function saveCurrentProject(patch: Partial<VoiceChangerProject> = {}) {
		if (!selectedProjectId) return;
		const current = projects.find((project) => project.id === selectedProjectId) ?? createProject();
		const updated: VoiceChangerProject = {
			...current,
			id: selectedProjectId,
			title: title.trim() || current.title,
			voice_id: selectedVoiceId,
			model_id: modelId,
			quality,
			cfg_scale: cfgScale,
			auto_shift: autoShift,
			pitch_shift: pitchShift,
			separate_vocals: separateVocals,
			mix_accompaniment: mixAccompaniment,
			seed,
			source_origin: current.source_origin ?? 'file',
			source_page_url: current.source_page_url ?? null,
			source_title: current.source_title ?? null,
			source_duration_seconds: current.source_duration_seconds ?? null,
			source_audio_url: current.source_audio_url ?? null,
			source_audio_name: current.source_audio_name ?? null,
			transcript,
			versions: projectVersions,
			...patch,
			updated_at: new Date().toISOString()
		};
		const nextProjects = [updated, ...projects.filter((project) => project.id !== selectedProjectId)];
		projects = nextProjects;
		persistProjects(nextProjects);
	}

	function backToList() {
		mode = 'list';
		progress = { percent: 0, message: '', elapsed: 0, active: false };
	}

	function deleteProject(id: string) {
		const project = projects.find((item) => item.id === id);
		if (!project || !window.confirm(t('cover.confirmDelete', { title: project.title }))) return;
		const nextProjects = projects.filter((item) => item.id !== id);
		projects = nextProjects;
		persistProjects(nextProjects);
		if (selectedProjectId === id) {
			selectedProjectId = '';
			projectVersions = [];
			outputUrl = '';
			mode = 'list';
		}
		onNotice('success', t('cover.deleted'));
	}

	function sourceUrlFromJob(job?: VoiceConversionJob) {
		if (job?.source_audio_url) return job.source_audio_url;
		if (!job?.source_audio_path) return '';
		const filename = job.source_audio_path.split('/').pop();
		return filename ? `/api/files/uploads/${filename}` : '';
	}

	function sourceUrlFromProject(project: VoiceChangerProject) {
		return project.source_audio_url || sourceUrlFromJob(project.versions?.[0]);
	}

	async function restoreSourceFromProject(project: VoiceChangerProject) {
		const sourceUrl = sourceUrlFromProject(project);
		if (!sourceUrl) {
			file = null;
			if (previewUrl) URL.revokeObjectURL(previewUrl);
			previewUrl = '';
			wave?.destroy();
			wave = null;
			return;
		}
		try {
			const response = await fetch(audioUrl(sourceUrl));
			if (!response.ok) return;
			const blob = await response.blob();
			await setSourcePreview(
				new File([blob], project.source_audio_name || sourceUrl.split('/').pop() || 'voice-change-source.wav', { type: blob.type || 'audio/wav' })
			);
		} catch {
			// Existing conversion result can still be played even if the source file cannot be restored.
		}
	}

	async function setSourcePreview(sourceFile: File) {
		file = sourceFile;
		if (previewUrl) URL.revokeObjectURL(previewUrl);
		previewUrl = URL.createObjectURL(sourceFile);
		await setupWaveform(previewUrl);
	}

	async function applySourceFile(
		sourceFile: File,
		projectPatch: Partial<VoiceChangerProject> = {},
		options: { titleCandidate?: string | null } = {}
	) {
		await setSourcePreview(sourceFile);
		if (!title.trim() || (title.startsWith(t('cover.newTitlePrefix')) || title.startsWith('새 노래 커버 ') || title.startsWith('새 AI 커버 ') || title.startsWith('New song cover '))) {
			const nextTitle = options.titleCandidate?.trim() || sourceFile.name.replace(/\.[^.]+$/, '');
			if (nextTitle) title = nextTitle;
		}
		transcript = '';
		outputUrl = '';
		projectVersions = [];
		saveCurrentProject({
			source_audio_name: projectPatch.source_audio_name ?? sourceFile.name,
			transcript: '',
			versions: [],
			...projectPatch
		});
	}

	async function persistSourceFile(sourceFile: File) {
		savingSource = true;
		try {
			const form = new FormData();
			form.append('audio', sourceFile);
			const response = await apiFetch('/api/audio/uploads', { method: 'POST', body: form });
			const payload = await response.json();
			saveCurrentProject({
				source_audio_url: payload.audio_url,
				source_audio_name: payload.filename || sourceFile.name,
				transcript,
				versions: []
			});
			onNotice('success', t('cover.sourceSaved'));
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			savingSource = false;
		}
	}

	async function setupWaveform(url: string) {
		await tick();
		if (!waveformEl) return;
		const theme = getComputedStyle(document.documentElement);
		const waveColor = theme.getPropertyValue('--muted-strong').trim() || '#e1d4c0';
		const progressColor = theme.getPropertyValue('--accent').trim() || '#b96d32';
		const cursorColor = theme.getPropertyValue('--foreground').trim() || '#1e1a14';
		wave?.destroy();
		regions = RegionsPlugin.create();
		wave = WaveSurfer.create({
			container: waveformEl,
			height: 132,
			waveColor,
			progressColor,
			cursorColor,
			barWidth: 2,
			barGap: 2,
			barRadius: 3,
			plugins: [regions]
		});
		wave.on('decode', (decodedDuration) => {
			duration = decodedDuration;
			trimStart = 0;
			trimEnd = decodedDuration;
			activeRegion = regions?.addRegion({
				start: trimStart,
				end: trimEnd,
				color: 'rgba(39, 37, 30, 0.2)',
				drag: true,
				resize: true
			});
		});
		regions.on('region-updated', (region: any) => {
			activeRegion = region;
			trimStart = region.start;
			trimEnd = region.end;
		});
		regions.on('region-clicked', (region: any, event: Event) => {
			event.stopPropagation();
			region.play();
		});
		wave.load(url);
	}

	async function importMediaSource() {
		if (!mediaUrl.trim()) {
			mediaImportError = t('cover.needUrl');
			return;
		}
		importingMedia = true;
		mediaImportError = '';
		try {
			const response = await apiFetch('/api/audio/media-import', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ url: mediaUrl.trim(), isolate_voice: false })
			});
			const payload: {
				platform: 'youtube' | 'instagram';
				title: string;
				webpage_url: string;
				duration_seconds?: number | null;
				audio_url: string;
				filename: string;
			} = await response.json();
			const sourceResponse = await fetch(audioUrl(payload.audio_url));
			if (!sourceResponse.ok) {
				throw new Error(t('cover.openFail'));
			}
			const blob = await sourceResponse.blob();
			const importedFile = new File([blob], payload.filename || 'cover-source.wav', { type: blob.type || 'audio/wav' });
			await applySourceFile(
				importedFile,
				{
					source_origin: payload.platform,
					source_page_url: payload.webpage_url,
					source_title: payload.title,
					source_duration_seconds: payload.duration_seconds ?? null,
					source_audio_url: payload.audio_url,
					source_audio_name: payload.filename || importedFile.name
				},
				{ titleCandidate: payload.title }
			);
			onNotice('success', t('cover.imported'));
		} catch (error) {
			mediaImportError = error instanceof Error ? error.message : String(error);
			onNotice('error', mediaImportError);
		} finally {
			importingMedia = false;
		}
	}

	async function onFileChange(event: Event) {
		const sourceFile = (event.target as HTMLInputElement).files?.[0] ?? null;
		if (!sourceFile) return;
		mediaImportError = '';
		await applySourceFile(
			sourceFile,
			{
				source_origin: 'file',
				source_page_url: null,
				source_title: null,
				source_duration_seconds: null,
				source_audio_url: null,
				source_audio_name: sourceFile.name
			},
			{ titleCandidate: sourceFile.name.replace(/\.[^.]+$/, '') }
		);
		await persistSourceFile(sourceFile);
	}

	function watchProgress(progressId: string) {
		let elapsed = 0;
		progress = { percent: 1, message: t('cover.preparing'), elapsed, active: true };
		const timer = window.setInterval(() => {
			elapsed += 1;
			progress = { ...progress, elapsed };
		}, 1000);
		const socket = new WebSocket(apiWebSocketUrl(`/api/ws/progress/${progressId}`));
		const finish = (message: string) => {
			window.clearInterval(timer);
			progress = { percent: 100, message, elapsed, active: false };
			window.setTimeout(() => {
				progress = { percent: 0, message: '', elapsed: 0, active: false };
			}, 1800);
			socket.close();
		};
		socket.onmessage = (event) => {
			const payload = JSON.parse(event.data);
			progress = {
				percent: Number(payload.percent ?? progress.percent),
				message: payload.message ?? progress.message,
				elapsed,
				active: !payload.done
			};
			if (payload.done) {
				finish(payload.message ?? t('cover.done'));
			}
		};
		return (doneMessage?: string) => {
			window.clearInterval(timer);
			socket.close();
			if (doneMessage) {
				progress = { percent: 100, message: doneMessage, elapsed, active: false };
				window.setTimeout(() => {
					progress = { percent: 0, message: '', elapsed: 0, active: false };
				}, 1800);
			}
		};
	}

	async function loadHistory() {
		try {
			const response = await apiFetch('/api/voice-conversion/jobs');
			history = await response.json();
		} catch {
			history = [];
		}
	}

	async function transcribeSource() {
		if (!file) {
			onNotice('error', t('cover.needSongLyrics'));
			return;
		}
		transcribing = true;
		try {
			const form = new FormData();
			form.append('audio', file);
			form.append('provider', sttProvider);
			if (sttLanguage) form.append('language', sttLanguage);
			form.append('trim_start', String(trimStart));
			form.append('trim_end', String(trimEnd));
			const response = await apiFetch('/api/audio/transcript-segments', { method: 'POST', body: form });
			const payload = await response.json();
			transcript = payload.text ?? '';
			saveCurrentProject({ transcript });
			onNotice('success', t('cover.lyricsDone', { engine: sttProvider === 'apple-speech' ? 'Apple Speech' : 'Whisper' }));
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			transcribing = false;
		}
	}

	function applyCoverRecommendation(result: ProductionAssistResponse) {
		if (!selectedProjectId || busy || savingSource || importingMedia || transcribing) throw new Error(t('cover.applyState'));
		if (result.kind !== 'cover' || !result.settings) throw new Error(t('cover.noSettings'));
		const settings = result.settings;
		const previous = { quality, cfgScale, pitchShift, autoShift, separateVocals, mixAccompaniment, projects };
		try {
			quality = settings.quality;
			cfgScale = settings.cfg_scale;
			pitchShift = settings.pitch_shift;
			autoShift = settings.auto_shift;
			separateVocals = settings.separate_vocals;
			mixAccompaniment = settings.mix_accompaniment && settings.separate_vocals;
			saveCurrentProject();
		} catch {
			({ quality, cfgScale, pitchShift, autoShift, separateVocals, mixAccompaniment, projects } = previous);
			throw new Error(t('cover.applyFail'));
		}
	}

	async function convert() {
		if (!file) {
			onNotice('error', t('cover.needSong'));
			return;
		}
		if (!selectedVoiceId) {
			onNotice('error', t('cover.needVoice'));
			return;
		}
		if (selectionTooShort) {
			onNotice('error', t('cover.tooShort'));
			return;
		}
		if (selectedModel?.status !== 'available') {
			onNotice('error', selectedModel?.message || t('cover.modelUnavailable'));
			return;
		}
		const progressId = crypto.randomUUID();
		const stopProgress = watchProgress(progressId);
		busy = true;
		try {
			const form = new FormData();
			form.append('audio', file);
			form.append('voice_id', selectedVoiceId);
			form.append('model_id', modelId);
			form.append('progress_id', progressId);
			form.append('trim_start', String(trimStart));
			form.append('trim_end', String(trimEnd));
			form.append('conversion_mode', 'singing');
			form.append('steps', String(generationSteps));
			form.append('cfg_scale', String(cfgScale));
			form.append('auto_shift', String(autoShift));
			form.append('pitch_shift', String(pitchShift));
			form.append('separate_vocals', String(separateVocals));
			form.append('mix_accompaniment', String(mixAccompaniment && separateVocals));
			form.append('seed', String(seed));
			const response = await apiFetch('/api/voice-conversion', { method: 'POST', body: form });
			const payload: {
				audio_url: string;
				transcript?: string | null;
				voice_id?: string | null;
				model_id?: string | null;
				job_id?: string | null;
				created_at?: string | null;
			} = await response.json();
			outputUrl = payload.audio_url;
			await loadHistory();
			const latest =
				(payload.job_id ? history.find((item) => item.id === payload.job_id) : null) ??
				history.find((item) => item.output_audio_url === payload.audio_url) ??
				(payload.job_id
					? {
							id: payload.job_id,
							model_id: payload.model_id || modelId,
							source_audio_url: selectedProject?.source_audio_url || null,
							target_voice_id: payload.voice_id || selectedVoiceId,
							output_audio_url: payload.audio_url,
							transcript: payload.transcript ?? null,
							created_at: payload.created_at || new Date().toISOString()
						}
					: null);
			if (latest) {
				projectVersions = [latest, ...projectVersions.filter((item) => item.id !== latest.id)];
			}
			transcript = payload.transcript || transcript;
			saveCurrentProject({ versions: projectVersions, transcript });
			onNotice('success', t('cover.finished'));
			stopProgress(t('cover.done'));
		} catch (error) {
			stopProgress();
			progress = { percent: 0, message: '', elapsed: 0, active: false };
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			busy = false;
		}
	}

</script>

{#if mode === 'list'}
	<VoiceChangerProjectList {projects} {voices} onCreate={startNew} onOpen={openProject} onDelete={deleteProject} />
{:else}
	<div class="workspace-grid">
		<section class="surface workspace-main">
			<div class="section-heading">
				<div>
					<label class="inline-title-label">
						<span class="hidden">{t('cover.titleLabel')}</span>
						<input class="inline-title-input" value={title} oninput={(event) => { title = event.currentTarget.value; saveCurrentProject(); }} aria-label={t('cover.titleLabel')} />
					</label>
				</div>
				<div class="button-row wrap">
					<button class="secondary-action" onclick={backToList}><ArrowLeft size={17} />{t('voice.ed.list')}</button>
					<button class="primary-action" disabled={busy || !canConvert} onclick={convert}>
						{#if busy}<Loader2 class="spin" size={18} />{t('cover.making')}{:else}<Wand2 size={18} />{t('cover.make')}{/if}
					</button>
				</div>
			</div>
			<div class="cover-source-entry">
				<div class="cover-source-heading">
					<FileAudio size={26} />
					<div>
						<h3>{file?.name ?? selectedProject?.source_title ?? t('cover.importTitle')}</h3>
					</div>
				</div>
								<div class="cover-url-input">
					<label class="field-label inline-flex items-center gap-1" for="cover-media-url">{t('cover.link')}<HelpPopover label={t('cover.link')} text={t('cover.linkHelp')} /></label>
					<div class="button-row wrap">
						<input
							id="cover-media-url"
							class="studio-input flex-input"
							type="url"
							bind:value={mediaUrl}
							placeholder="https://www.youtube.com/watch?v=..."
							aria-label={t('cover.linkLabel')}
						/>
						<button class="secondary-action" disabled={importingMedia || savingSource || busy || !mediaUrl.trim()} onclick={importMediaSource}>
							{#if importingMedia}<Loader2 class="spin" size={17} />{t('voice.link.importing')}{:else}<Link2 size={17} />{t('voice.link.import')}{/if}
						</button>
					</div>
					{#if mediaImportError}
						<p class="field-error">{mediaImportError}</p>
					{/if}
				</div>
				{#if savingSource}
					<p class="field-helper">{t('cover.saving')}</p>
				{/if}
				<div class="button-row">
					<label class="secondary-action">{file ? t('cover.replace') : t('cover.pickFile')}<input class="hidden" type="file" accept="audio/*" onchange={onFileChange} /></label>
					<button class="secondary-action" disabled={!file || transcribing || savingSource || importingMedia} onclick={transcribeSource}>
						{#if transcribing}<Loader2 class="spin" size={17} />{t('cover.lyricsBusy')}{:else}<FileAudio size={17} />{t('cover.lyrics')}{/if}
					</button>
				</div>
			</div>
			{#if selectedProject?.source_origin || selectedProject?.source_title || selectedProject?.source_page_url}
				<div class="result-preview cover-source-summary">
					<div class="section-heading compact-heading">
						<div>
							<h3>{t('cover.info')}</h3>
							<p>
								{selectedProject?.source_origin === 'instagram'
									? t('cover.origin.instagram')
									: selectedProject?.source_origin === 'youtube'
										? t('cover.origin.youtube')
										: t('cover.origin.file')}
								{#if selectedProject?.source_duration_seconds}
									· {formatTime(selectedProject.source_duration_seconds)}
								{/if}
							</p>
						</div>
						{#if selectedProject?.source_page_url}
							<a class="secondary-action" href={selectedProject.source_page_url} target="_blank" rel="noreferrer">{t('cover.original')}</a>
						{/if}
					</div>
					<strong>{selectedProject?.source_title || selectedProject?.source_audio_name || file?.name}</strong>
					{#if selectedProject?.source_audio_name}
						<p class="field-helper">{selectedProject.source_audio_name}</p>
					{/if}
					{#if selectedProject?.source_audio_url && !savingSource && !importingMedia}
						{#key selectedProject.source_audio_url}
							<AudioDownload path={selectedProject.source_audio_url} filename={selectedProject.source_title || selectedProject.source_audio_name || 'cover-source'} label={t('cover.fullSong')} />
						{/key}
					{/if}
				</div>
			{/if}
			{#if previewUrl}
				<div class="result-preview">
					<h3>{t('cover.preview')}</h3>
					<audio controls src={previewUrl}></audio>
				</div>
			{/if}
			{#if transcript}
				<div class="result-preview">
					<h3>{t('cover.lyricsText')}</h3>
					<textarea class="studio-input compact-textarea" value={transcript} oninput={(event) => { transcript = event.currentTarget.value; saveCurrentProject({ transcript }); }}></textarea>
				</div>
			{/if}
			<div class="wave-editor">
				<div bind:this={waveformEl}></div>
				{#if previewUrl && timelineTicks.length}
					<div class="wave-timeline" aria-label={t('voice.wave.ticks')}>
						{#each timelineTicks as tick (tick)}
							<span>{formatTime(tick)}</span>
						{/each}
					</div>
				{/if}
				{#if !previewUrl}
					<div class="wave-placeholder">{t('cover.placeholder')}</div>
				{/if}
			</div>
			{#if previewUrl}
				<div class="transport-row">
					<button class="icon-button" onclick={() => activeRegion?.play()} aria-label={t('voice.wave.playLabel')}><Play size={18} /></button>
					<button class="icon-button" onclick={() => wave?.pause()} aria-label={t('voice.wave.pause')}><Pause size={18} /></button>
					<button class="icon-button" onclick={() => wave?.seekTo(0)} aria-label={t('voice.wave.restart')}><RotateCcw size={18} /></button>
					<button class="secondary-action compact" onclick={() => {
						trimStart = 0;
						trimEnd = duration;
						activeRegion?.setOptions?.({ start: 0, end: duration });
					}}>{t('cover.selectAll')}</button>
					<span>{t('cover.selection', { range: formatTime(trimStart) + ' - ' + formatTime(trimEnd), seconds: selectedDuration.toFixed(1) })}</span>
				</div>
				{#if selectionTooShort}
					<p class="warning-note">{t('cover.tooShortNote')}</p>
				{/if}
			{/if}
			<ProductionAssistPanel
				panelId="cover"
				kinds={['cover']}
				contextKey={JSON.stringify({ project: selectedProjectId, title, voice: selectedVoiceId, model: modelId, source: selectedProject?.source_audio_url, file: file ? [file.name, file.size, file.lastModified] : null, trimStart, trimEnd, transcript })}
				currentSettings={{ quality, cfg_scale: cfgScale, pitch_shift: pitchShift, auto_shift: autoShift, separate_vocals: separateVocals, mix_accompaniment: mixAccompaniment && separateVocals }}
				disabled={busy || savingSource || importingMedia || transcribing}
				allowApply={Boolean(selectedProjectId)}
				onApply={applyCoverRecommendation}
			/>
			<ProgressPanel {progress} fallbackMessage={t('cover.progress')} />
			<VoiceChangerResultsPanel {projectVersions} {voices} />
		</section>
		<VoiceChangerSettingsPanel
			{voices}
			{vcModels}
			{selectedVoice}
			{selectedModel}
			{sttProvider}
			{sttLanguage}
			voiceId={selectedVoiceId}
			{modelId}
			{quality}
			{cfgScale}
			{autoShift}
			{pitchShift}
			{separateVocals}
			{mixAccompaniment}
			{seed}
			onSttProviderChange={(value) => (sttProvider = value)}
			onSttLanguageChange={(value) => (sttLanguage = value)}
			onModelChange={(value) => {
				modelId = value;
				saveCurrentProject();
			}}
			onVoiceChange={(value) => {
				voiceId = value;
				saveCurrentProject();
			}}
			onQualityChange={(value) => {
				quality = value;
				saveCurrentProject();
			}}
			onCfgScaleChange={(value) => {
				cfgScale = value;
				saveCurrentProject();
			}}
			onAutoShiftChange={(value) => {
				autoShift = value;
				saveCurrentProject();
			}}
			onPitchShiftChange={(value) => {
				pitchShift = value;
				saveCurrentProject();
			}}
			onSeparateVocalsChange={(value) => {
				separateVocals = value;
				if (!value) mixAccompaniment = false;
				saveCurrentProject();
			}}
			onMixAccompanimentChange={(value) => {
				mixAccompaniment = value;
				saveCurrentProject();
			}}
			onSeedChange={(value) => {
				seed = value;
				saveCurrentProject();
			}}
		/>
	</div>
{/if}

<style>
	.cover-url-input {
		display: grid;
		gap: 8px;
		width: 100%;
	}

	.cover-source-entry {
		display: grid;
		gap: 12px;
		border-block: 1px solid var(--border-soft);
		padding: 18px 0;
	}

	.cover-source-heading {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: 12px;
		align-items: start;
	}

	.cover-source-heading :global(svg) {
		margin-top: 2px;
		color: var(--accent-hover);
	}

	.cover-source-heading h3 {
		margin: 0;
	}

	.flex-input {
		flex: 1 1 320px;
		min-width: 0;
	}

	.cover-source-summary strong {
		display: block;
		margin-top: 6px;
	}
</style>
