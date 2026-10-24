<script lang="ts">
	import { browser } from '$app/environment';
	import { onMount, tick } from 'svelte';
	import { ArrowDown, ArrowLeft, ArrowUp, Copy, Download, FileText, Loader2, Plus, RefreshCw, Sparkles, Trash2, Upload, Volume2 } from '@lucide/svelte';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import { getLocale } from '$lib/i18n/core';
	import { t } from '$lib/i18n/index.svelte';
	import { apiFetch, apiWebSocketUrl, audioUrl, languages } from '$lib/studio/api';
	import { storyGenerationSegments, storyResultIsStale } from '$lib/studio/story-production';
	import type { StudioPreferences } from '$lib/studio/preferences';
	import ProgressPanel from '$lib/components/app/ProgressPanel.svelte';
	import StoryInspector from '$lib/components/story/StoryInspector.svelte';
	import StoryPlayer from '$lib/components/story/StoryPlayer.svelte';
	import StoryProjectList from '$lib/components/story/StoryProjectList.svelte';
	import type {
		DialogueDraftResponse,
		RuntimeModelStatus,
		StoryDialogueFormat,
		StoryProject,
		StorySegment,
		StorySpeakerProfile,
		StoryStudioResult,
		VoiceProfile
	} from '$lib/studio/types';

	let {
		voices,
		models,
		defaultTtsModelId = 'voxcpm',
		defaultSttProvider = 'apple-speech',
		defaultVoiceId = '',
		startWithVoice = false,
		onNotice
	}: {
		voices: VoiceProfile[];
		models: RuntimeModelStatus[];
		defaultTtsModelId?: string;
		defaultSttProvider?: StudioPreferences['stt_provider'];
		defaultVoiceId?: string;
		startWithVoice?: boolean;
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
	} = $props();

	const STORAGE_KEY = 'clonevoice.storyStudio.projects.v1';
	const PENDING_KEY = 'clonevoice.storyStudio.pending.v1';
	const pendingProjects = new Map<string, StoryProject>();
	const savedRevisions = new Map<string, number>();
	const fingerprints = new Map<string, string>();
	let storageReady = $state(false);
	let savePromise: Promise<void> | null = null;
	let saveState = $state<'loading' | 'saving' | 'saved' | 'error'>('loading');
	let saveError = $state('');
	const toneSuggestions = $derived([
		t('story.tone.calm'), t('story.tone.bright'), t('story.tone.exciting'), t('story.tone.tense'),
		t('story.tone.serious'), t('story.tone.soft'), t('story.tone.whisper'), t('story.tone.surprised')
	]);
	const dialogueFormatOptions = $derived<Array<{ value: StoryDialogueFormat; label: string; description: string }>>([
		{ value: 'deep-dive', label: t('story.format.deep-dive'), description: t('story.format.deep-dive.desc') },
		{ value: 'interview', label: t('story.format.interview'), description: t('story.format.interview.desc') },
		{ value: 'debate', label: t('story.format.debate'), description: t('story.format.debate.desc') },
		{ value: 'briefing', label: t('story.format.briefing'), description: t('story.format.briefing.desc') }
	]);
	const dialogueLanguages = ['ko', 'en', 'ja', 'zh'] as const;
	type DialogueLanguage = (typeof dialogueLanguages)[number];
	const dialogueLengthOptions = $derived([
		{ value: 'short', label: t('story.len.short') },
		{ value: 'medium', label: t('story.len.medium') },
		{ value: 'long', label: t('story.len.long') }
	] as const);
	type ImportSpeakerSetting = { voice_id: string; tone_prompt: string };
	type DialogueDraftForm = {
		draft_mode: 'source' | 'topic';
		source_text: string;
		format: StoryDialogueFormat;
		speaker_one: string;
		speaker_two: string;
		speaker_three: string;
		speaker_four: string;
		speaker_count: number;
		voice_one: string;
		voice_two: string;
		voice_three: string;
		voice_four: string;
		language: DialogueLanguage;
		length: (typeof dialogueLengthOptions)[number]['value'];
		turns: number;
		focus: string;
		include_sfx: boolean;
	};
	const draftSpeakerFields = $derived([
		{ name: 'speaker_one', voice: 'voice_one', label: t('story.speakerN', { n: 1 }), role: 'A' },
		{ name: 'speaker_two', voice: 'voice_two', label: t('story.speakerN', { n: 2 }), role: 'B' },
		{ name: 'speaker_three', voice: 'voice_three', label: t('story.speakerN', { n: 3 }), role: 'C' },
		{ name: 'speaker_four', voice: 'voice_four', label: t('story.speakerN', { n: 4 }), role: 'D' }
	] as const);

	function currentDefaultTtsModelId() {
		return models.find((model) => model.id === defaultTtsModelId && model.capabilities.tts)?.id ?? models.find((model) => model.capabilities.tts)?.id ?? defaultTtsModelId;
	}

	function defaultSegments(): StorySegment[] {
		const modelId = currentDefaultTtsModelId();
		return [
			{
				id: crypto.randomUUID(),
				text: t('story.default.q'),
				language: getLocale(),
				voice_id: voices.some((voice) => voice.id === defaultVoiceId) ? defaultVoiceId : '',
				model_id: modelId,
				tone_prompt: t('story.tone.calm'),
				accent: '',
				speed: 1,
				pause_after_ms: 450,
				segment_type: 'speech',
				speaker_name: t('story.host')
			},
			{
				id: crypto.randomUUID(),
				text: t('story.default.a'),
				language: getLocale(),
				voice_id: '',
				model_id: modelId,
				tone_prompt: t('story.tone.clear'),
				accent: '',
				speed: 0.96,
				pause_after_ms: 650,
				segment_type: 'speech',
				speaker_name: t('story.guest')
			}
		];
	}

	function createProject(name = t('story.newProject')): StoryProject {
		const now = new Date().toISOString();
		return {
			id: crypto.randomUUID(),
			title: name,
			segments: defaultSegments(),
			result: null,
			created_at: now,
			updated_at: now
		};
	}

	let projects = $state<StoryProject[]>([]);
	let mode = $state<'list' | 'detail'>('list');
	let selectedProjectId = $state('');
	let title = $state(t('story.newProject'));
	let selectedSegmentId = $state('seg-1');
	let selectedSegmentIds = $state<string[]>([]);
	let draggedSegmentId = $state<string | null>(null);
	let translatingSegmentId = $state('');
	let busy = $state(false);
	let showGenerationConfirm = $state(false);
	let showScriptImport = $state(false);
	let showDialogueDraft = $state(false);
	let draftingDialogue = $state(false);
	let scriptDraft = $state(t('story.sampleScript'));
	let mediaUrl = $state('');
	let importingMedia = $state(false);
	let importSpeakerSettings = $state<Record<string, ImportSpeakerSetting>>({});
	let dialogueDraftForm = $state<DialogueDraftForm>({
		draft_mode: 'topic',
		source_text: '',
		format: 'deep-dive',
		speaker_one: t('story.host'),
		speaker_two: t('story.guest'),
		speaker_three: t('story.analyst'),
		speaker_four: t('story.narrator'),
		speaker_count: 2,
		voice_one: '', voice_two: '', voice_three: '', voice_four: '',
		language: 'ko',
		length: 'medium',
		turns: 10,
		focus: '',
		include_sfx: true
	});
	let generationProgress = $state({ percent: 0, message: '', elapsed: 0, active: false });
	let result = $state<StoryStudioResult | null>(null);
	let segments = $state<StorySegment[]>(defaultSegments());
	let storyTitleElement = $state<HTMLInputElement | null>(null);
	let dialogueSourceElement = $state<HTMLTextAreaElement | null>(null);
	let scriptDraftElement = $state<HTMLTextAreaElement | null>(null);
	let generationCancelElement = $state<HTMLButtonElement | null>(null);
	let dialogReturnTarget: HTMLElement | null = null;

	let ttsModels = $derived(models.filter((model) => model.capabilities.tts));
	let sfxModel = $derived(models.find((model) => model.capabilities.sound_effect_generation));
	let selectedProject = $derived(projects.find((project) => project.id === selectedProjectId));
	let selectedSegment = $derived(segments.find((segment) => segment.id === selectedSegmentId) ?? segments[0]);
	let selectedSegmentIndex = $derived(Math.max(0, segments.findIndex((segment) => segment.id === selectedSegment?.id)));
	let selectedSegmentCount = $derived(selectedSegmentIds.length);
	let allSegmentsSelected = $derived(segments.length > 0 && selectedSegmentIds.length === segments.length);
	let totalWords = $derived(segments.reduce((sum, segment) => sum + segment.text.trim().split(/\s+/).filter(Boolean).length, 0));
	let estimatedPause = $derived(segments.reduce((sum, segment) => sum + segment.pause_after_ms, 0) / 1000);
	let usedVoices = $derived(
		segments
			.filter((segment) => segment.segment_type !== 'sfx')
			.map((segment) => voices.find((voice) => voice.id === segment.voice_id)?.name)
			.filter((name, index, names): name is string => Boolean(name) && names.indexOf(name) === index)
	);
	let speakerNames = $derived(
		segments
			.filter((segment) => segment.segment_type !== 'sfx')
			.map((segment) => segment.speaker_name?.trim() || t('story.speaker'))
			.filter((name, index, names) => names.indexOf(name) === index)
	);
	let speakerProfiles = $derived(
		speakerNames.map((name): StorySpeakerProfile => {
			const speakerSegments = segments.filter(
				(segment) => segment.segment_type !== 'sfx' && (segment.speaker_name?.trim() || t('story.speaker')) === name
			);
			const voiceIds = [...new Set(speakerSegments.map((segment) => segment.voice_id ?? ''))];
			const tonePrompts = [...new Set(speakerSegments.map((segment) => segment.tone_prompt?.trim() ?? ''))];
			return {
				name,
				voice_id: voiceIds.length === 1 ? voiceIds[0] : '',
				tone_prompt: tonePrompts.length === 1 ? tonePrompts[0] : '',
				segment_count: speakerSegments.length,
				has_mixed_voices: voiceIds.length > 1,
				has_mixed_tones: tonePrompts.length > 1
			};
		})
	);
	let importSpeakerNames = $derived(extractSpeakerNames(scriptDraft));
	let usableSegmentCount = $derived(segments.filter((segment) => (segment.translated_text || segment.text).trim()).length);
	let translationNeededCount = $derived(segments.filter((segment) => segment.segment_type !== 'sfx' && needsTranslationBeforeGeneration(segment)).length);
	let unavailableSegmentCount = $derived(
		segments.filter((segment) => {
			if (segment.segment_type === 'sfx') return sfxModel?.status !== 'available';
			const model = ttsModels.find((item) => item.id === (segment.model_id || currentDefaultTtsModelId()));
			return !model || model.status === 'unavailable';
		}).length
	);
	let missingVoiceCount = $derived(segments.filter((segment) => segment.segment_type !== 'sfx' && segment.voice_id && !voices.some((voice) => voice.id === segment.voice_id)).length);
	let unassignedSpeakerCount = $derived(speakerProfiles.filter((speaker) => !speaker.voice_id && !speaker.has_mixed_voices).length);
	let resultStale = $derived(storyResultIsStale(result, segments, currentDefaultTtsModelId()));
	let canGenerateStory = $derived(usableSegmentCount > 0 && unavailableSegmentCount === 0 && translationNeededCount === 0 && missingVoiceCount === 0 && !busy && storageReady);
	let sfxDraftAvailable = $derived(sfxModel?.status === 'available');
	let sourceExcerpt = $derived(selectedProject?.source_excerpt?.trim() ?? '');
	let dialogueFormat = $derived(selectedProject?.dialogue_format ?? null);

	function excerpt(text: string, limit = 160) {
		const normalized = text.replace(/\s+/g, ' ').trim();
		if (!normalized) return '';
		return normalized.length > limit ? `${normalized.slice(0, limit).trimEnd()}…` : normalized;
	}

	function voiceForSpeakerName(speakerName: string) {
		return (
			segments.find(
				(segment) => segment.segment_type !== 'sfx' && (segment.speaker_name?.trim() || t('story.speaker')) === speakerName && segment.voice_id
			)?.voice_id ?? ''
		);
	}

	function toneForSpeakerName(speakerName: string) {
		return (
			segments.find(
				(segment) => segment.segment_type !== 'sfx' && (segment.speaker_name?.trim() || t('story.speaker')) === speakerName && segment.tone_prompt?.trim()
			)?.tone_prompt ?? ''
		);
	}

	function getUsableSegments() {
		return segments
			.map((segment) => ({ ...segment, text: spokenTextForSegment(segment) }))
			.filter((segment) => segment.text);
	}

	function spokenTextForSegment(segment: StorySegment) {
		if (segment.segment_type === 'sfx') return segment.text.trim();
		const translatedText = segment.translated_text?.trim();
		if (translatedText && segment.language !== 'ko') return translatedText;
		return segment.text.trim();
	}

	function textSourceLabel(segment: StorySegment) {
		if (segment.segment_type === 'sfx') return t('story.sfxSeconds', { seconds: segment.sfx_duration_seconds ?? 3 });
		if (segment.translated_text?.trim() && segment.language !== 'ko') return t('story.gen.translated');
		if (needsTranslationBeforeGeneration(segment)) return t('story.gen.needTranslation');
		return t('story.gen.original');
	}

	function needsTranslationBeforeGeneration(segment: StorySegment) {
		if (segment.segment_type === 'sfx') return false;
		return segment.language !== 'ko' && !segment.translated_text?.trim() && /[가-힣]/.test(segment.text);
	}

	onMount(() => {
		void initializeProjects();
	});

	function loadProjects(key = STORAGE_KEY): StoryProject[] {
		if (!browser) return [];
		try {
			const parsed = JSON.parse(window.localStorage.getItem(key) || '[]');
			return Array.isArray(parsed) ? (parsed as StoryProject[]) : [];
		} catch {
			return [];
		}
	}

	function projectFingerprint(project: StoryProject) {
		return JSON.stringify({ title: project.title, segments: project.segments, result: project.result ?? null, source_text: project.source_text ?? null, source_excerpt: project.source_excerpt ?? null, dialogue_format: project.dialogue_format ?? null });
	}

	async function initializeProjects() {
		const localProjects = loadProjects();
		const pending = loadProjects(PENDING_KEY);
		try {
			const response = await apiFetch('/api/story-studio/projects');
			const remote = (await response.json()) as StoryProject[];
			for (const project of remote) {
				savedRevisions.set(project.id, project.revision ?? 0);
				fingerprints.set(project.id, projectFingerprint(project));
			}
			projects = remote;
			for (const project of localProjects) {
				if (!remote.some((item) => item.id === project.id) && !project.revision) {
					const migrated = { ...project, revision: 0 };
					projects = [...projects, migrated];
					pendingProjects.set(migrated.id, migrated);
				}
			}
			for (const project of pending) {
				const current = remote.find((item) => item.id === project.id);
				if (current && projectFingerprint(current) === projectFingerprint(project)) continue;
				if (current && (current.revision ?? 0) !== (project.revision ?? 0)) {
					const recovered = { ...project, id: crypto.randomUUID(), title: t('story.recovered', { title: project.title.slice(0, 240) }), revision: 0 };
					projects = [recovered, ...projects];
					pendingProjects.set(recovered.id, recovered);
					onNotice('info', t('story.recoveredNotice'));
				} else {
					const recovered = !current && project.revision ? { ...project, id: crypto.randomUUID(), title: t('story.recovered', { title: project.title.slice(0, 240) }), revision: 0 } : project;
					projects = [recovered, ...projects.filter((item) => item.id !== recovered.id)];
					pendingProjects.set(recovered.id, recovered);
				}
			}
			storageReady = true;
			persistProjects(projects, false);
			await flushProjects();
			if (startWithVoice) newProject();
		} catch (error) {
			projects = localProjects;
			saveState = 'error';
			saveError = error instanceof Error ? error.message : String(error);
		}
	}

	function persistProjects(nextProjects = projects, enqueue = true) {
		if (!browser) return;
		if (enqueue) {
			for (const project of nextProjects) {
				const fingerprint = projectFingerprint(project);
				if (fingerprint === fingerprints.get(project.id)) continue;
				fingerprints.set(project.id, fingerprint);
				pendingProjects.set(project.id, JSON.parse(JSON.stringify(project)) as StoryProject);
			}
		}
		try {
			window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextProjects));
			window.localStorage.setItem(PENDING_KEY, JSON.stringify([...pendingProjects.values()]));
		} catch {
			onNotice('error', t('story.storageFull'));
		}
		if (enqueue && storageReady && !saveError) void flushProjects();
	}

	async function flushProjects() {
		if (savePromise) return savePromise;
		if (!storageReady) return;
		saveError = '';
		savePromise = (async () => {
			while (pendingProjects.size) {
				saveState = 'saving';
				const [id, snapshot] = pendingProjects.entries().next().value!;
				try {
					const response = await apiFetch(`/api/story-studio/projects/${encodeURIComponent(id)}`, {
						method: 'PUT', headers: { 'Content-Type': 'application/json' },
						body: JSON.stringify({ ...snapshot, revision: savedRevisions.get(id) ?? snapshot.revision ?? 0 })
					});
					const saved = (await response.json()) as StoryProject;
					savedRevisions.set(id, saved.revision ?? 0);
					if (pendingProjects.get(id) === snapshot) pendingProjects.delete(id);
					else {
						const next = pendingProjects.get(id)!;
						pendingProjects.set(id, { ...next, revision: saved.revision });
					}
					projects = projects.map((project) => project.id === id ? { ...project, revision: saved.revision } : project);
					persistProjects(projects, false);
				} catch (error) {
					saveState = 'error';
					saveError = error instanceof Error ? error.message : String(error);
					return;
				}
			}
			saveState = 'saved';
		})();
		await savePromise;
		savePromise = null;
	}

	async function retrySaving() {
		if (!storageReady) await initializeProjects();
		else await flushProjects();
	}

	function saveCurrentProject(patch: Partial<StoryProject> = {}) {
		if (!selectedProjectId) return;
		const updated: StoryProject = {
			...(selectedProject ?? createProject(title)),
			id: selectedProjectId,
			title,
			segments,
			result,
			...patch,
			updated_at: new Date().toISOString()
		};
		const nextProjects = [updated, ...projects.filter((project) => project.id !== selectedProjectId)];
		projects = nextProjects;
		persistProjects(nextProjects);
	}

	function openProject(projectId: string, sourceProjects = projects) {
		const project = sourceProjects.find((item) => item.id === projectId);
		if (!project) return;
		selectedProjectId = project.id;
		title = project.title;
		segments = (project.segments.length ? project.segments : defaultSegments()).map((segment, index) => ({
			...segment,
			segment_type: segment.segment_type ?? 'speech',
			speaker_name: segment.speaker_name ?? t('story.speakerN', { n: index % 2 + 1 }),
			sfx_duration_seconds: segment.sfx_duration_seconds ?? 3
		}));
		result = project.result ?? null;
		selectedSegmentId = segments[0]?.id ?? '';
		selectedSegmentIds = [];
		mode = 'detail';
	}

	function newProject() {
		if (!storageReady) return;
		const project = createProject(t('story.newAudio'));
		const nextProjects = [project, ...projects];
		projects = nextProjects;
		persistProjects(nextProjects);
		openProject(project.id, nextProjects);
	}

	function downloadProjectBackup() {
		const project = selectedProject;
		if (!project) return;
		const href = URL.createObjectURL(new Blob([JSON.stringify(project, null, 2)], { type: 'application/json' }));
		const anchor = document.createElement('a');
		anchor.href = href;
		anchor.download = `${project.title.replace(/[\\/:*?"<>|]/g, '_') || 'dialogue'}.json`;
		anchor.click();
		window.setTimeout(() => URL.revokeObjectURL(href), 1000);
	}

	async function importProjectBackup(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file || !storageReady) return;
		if (file.size > 10 * 1024 * 1024) { onNotice('error', t('story.backupMax')); return; }
		try {
			const parsed = JSON.parse(await file.text()) as StoryProject;
			const restored = { ...parsed, id: crypto.randomUUID(), revision: 0, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
			const response = await apiFetch(`/api/story-studio/projects/${restored.id}`, {
				method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(restored)
			});
			const saved = (await response.json()) as StoryProject;
			projects = [saved, ...projects];
			savedRevisions.set(saved.id, saved.revision ?? 0);
			fingerprints.set(saved.id, projectFingerprint(saved));
			persistProjects(projects, false);
			openProject(saved.id);
			onNotice('success', t('story.restored'));
		} catch (error) { onNotice('error', error instanceof Error ? error.message : String(error)); }
	}

	function duplicateProject() {
		if (!selectedProject || busy) return;
		const now = new Date().toISOString();
		const duplicate = { ...selectedProject, id: crypto.randomUUID(), title: t('story.copy', { title: title.slice(0, 240) }), segments: segments.map((segment) => ({ ...segment, id: crypto.randomUUID() })), result: null, revision: 0, created_at: now, updated_at: now };
		projects = [duplicate, ...projects];
		persistProjects();
		openProject(duplicate.id);
	}

	function openDialogueDraft() {
		if (!storageReady || busy) return;
		rememberDialogTrigger();
		const currentSpeakers = mode === 'detail' ? speakerNames.filter(Boolean) : [];
		const currentLanguage =
			mode === 'detail' ? segments.find((segment) => segment.segment_type !== 'sfx' && segment.language)?.language : null;
		dialogueDraftForm = {
			...dialogueDraftForm,
			draft_mode: selectedProject?.source_text?.trim() ? 'source' : dialogueDraftForm.draft_mode,
			source_text: selectedProject?.source_text?.trim() || selectedProject?.source_excerpt?.trim() || dialogueDraftForm.source_text,
			format: selectedProject?.dialogue_format ?? dialogueDraftForm.format,
			speaker_one: currentSpeakers[0] ?? dialogueDraftForm.speaker_one,
			speaker_two: currentSpeakers[1] ?? dialogueDraftForm.speaker_two,
			speaker_three: currentSpeakers[2] ?? dialogueDraftForm.speaker_three,
			speaker_four: currentSpeakers[3] ?? dialogueDraftForm.speaker_four,
			speaker_count: currentSpeakers.length ? Math.min(4, Math.max(2, currentSpeakers.length)) : dialogueDraftForm.speaker_count,
			language: dialogueLanguages.includes(currentLanguage as DialogueLanguage)
				? (currentLanguage as DialogueLanguage)
				: dialogueDraftForm.language,
			include_sfx: sfxDraftAvailable ? dialogueDraftForm.include_sfx : false
		};
		for (const field of draftSpeakerFields) {
			dialogueDraftForm[field.voice] = voiceForSpeakerName(dialogueDraftForm[field.name]) || dialogueDraftForm[field.voice];
		}
		if (mode === 'list' && voices.some((voice) => voice.id === defaultVoiceId)) dialogueDraftForm.voice_one = defaultVoiceId;
		showDialogueDraft = true;
		void focusDialogueSource();
	}

	function rememberDialogTrigger() {
		dialogReturnTarget = document.activeElement instanceof HTMLElement ? document.activeElement : null;
	}

	async function focusDialogueSource() {
		await tick();
		dialogueSourceElement?.focus();
	}

	async function focusScriptDraft() {
		await tick();
		scriptDraftElement?.focus();
	}

	async function focusGenerationCancel() {
		await tick();
		generationCancelElement?.focus();
	}

	async function focusEditorTitle() {
		await tick();
		storyTitleElement?.focus();
	}

	async function restoreDialogTrigger() {
		const target = dialogReturnTarget;
		dialogReturnTarget = null;
		await tick();
		target?.focus();
	}

	function closeDialogueDraft() {
		if (draftingDialogue || importingMedia) return;
		showDialogueDraft = false;
		void restoreDialogTrigger();
	}

	function closeScriptImport() {
		if (importingMedia) return;
		showScriptImport = false;
		void restoreDialogTrigger();
	}

	function closeGenerationConfirm() {
		showGenerationConfirm = false;
		void restoreDialogTrigger();
	}

	function trapDialogFocus(event: KeyboardEvent, closeDialog: () => void) {
		if (event.key === 'Escape') {
			event.preventDefault();
			closeDialog();
			return;
		}
		if (event.key !== 'Tab') return;
		const dialog = event.currentTarget as HTMLElement;
		const focusable = Array.from(
			dialog.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])')
		).filter((element) => element.getClientRects().length > 0);
		if (!focusable.length) return;
		const first = focusable[0];
		const last = focusable[focusable.length - 1];
		if (event.shiftKey && document.activeElement === first) {
			event.preventDefault();
			last.focus();
		} else if (!event.shiftKey && document.activeElement === last) {
			event.preventDefault();
			first.focus();
		}
	}

	function updateDialogueLength(length: DialogueDraftForm['length']) {
		const turnCounts: Record<DialogueDraftForm['length'], number> = { short: 6, medium: 10, long: 14 };
		dialogueDraftForm = { ...dialogueDraftForm, length, turns: turnCounts[length] };
	}

	function normalizedDialogueTurns() {
		const value = Number(dialogueDraftForm.turns);
		return Math.min(18, Math.max(4, Number.isFinite(value) ? Math.round(value) : 10));
	}

	function backToList() {
		mode = 'list';
		generationProgress = { percent: 0, message: '', elapsed: 0, active: false };
	}

	async function deleteProject(projectId: string) {
		const project = projects.find((item) => item.id === projectId);
		if (!project || !window.confirm(t('story.confirmDelete', { title: project.title }))) return;
		await flushProjects();
		if (!storageReady || pendingProjects.has(projectId)) {
			onNotice('error', t('story.deleteSaveFirst'));
			return;
		}
		try {
			await apiFetch(`/api/story-studio/projects/${encodeURIComponent(projectId)}?revision=${savedRevisions.get(projectId)}`, { method: 'DELETE' });
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
			return;
		}
		const nextProjects = projects.filter((item) => item.id !== projectId);
		projects = nextProjects;
		persistProjects(nextProjects, false);
		if (selectedProjectId === projectId) {
			selectedProjectId = '';
			result = null;
			segments = defaultSegments();
			selectedSegmentIds = [];
			mode = 'list';
		}
		onNotice('success', t('story.deleted'));
	}

	function updateTitle(value: string) {
		title = value;
		saveCurrentProject({ title: value });
	}

	function watchProgress(progressId: string) {
		let elapsed = 0;
		generationProgress = { percent: 1, message: t('story.preparing'), elapsed, active: true };
		const timer = window.setInterval(() => {
			elapsed += 1;
			generationProgress = { ...generationProgress, elapsed };
		}, 1000);
		const socket = new WebSocket(apiWebSocketUrl(`/api/ws/progress/${progressId}`));
		const finish = (message: string) => {
			window.clearInterval(timer);
			generationProgress = { percent: 100, message, elapsed, active: false };
			window.setTimeout(() => {
				generationProgress = { percent: 0, message: '', elapsed: 0, active: false };
			}, 1600);
			socket.close();
		};
		socket.onmessage = (event) => {
			const payload = JSON.parse(event.data);
			generationProgress = {
				percent: Number(payload.percent ?? generationProgress.percent),
				message: payload.message ?? generationProgress.message,
				elapsed,
				active: !payload.done
			};
			if (payload.done) {
				finish(payload.message ?? t('story.done'));
			}
		};
		socket.onerror = () => {
			generationProgress = { ...generationProgress, message: t('story.progressConn') };
		};
		return (doneMessage?: string) => {
			window.clearInterval(timer);
			socket.close();
			if (doneMessage) {
				generationProgress = { percent: 100, message: doneMessage, elapsed, active: false };
				window.setTimeout(() => {
					generationProgress = { percent: 0, message: '', elapsed: 0, active: false };
				}, 1600);
			}
		};
	}

	function addSegment(afterId?: string) {
		if (segments.length >= 80) { onNotice('error', t('story.max80')); return; }
		const newSegment: StorySegment = {
			id: crypto.randomUUID(),
			text: t('story.newSegment'),
			language: selectedSegment?.language ?? 'ko',
			voice_id: selectedSegment?.voice_id ?? '',
			model_id: selectedSegment?.model_id ?? currentDefaultTtsModelId(),
			tone_prompt: selectedSegment?.tone_prompt ?? '',
			accent: selectedSegment?.accent ?? '',
			speed: selectedSegment?.speed ?? 1,
			pause_after_ms: 450,
			segment_type: 'speech',
			speaker_name: selectedSegment?.speaker_name ?? speakerNames[0] ?? t('story.speakerN', { n: 1 }),
			sfx_duration_seconds: 3
		};
		const index = afterId ? segments.findIndex((segment) => segment.id === afterId) : segments.length - 1;
		segments = [...segments.slice(0, index + 1), newSegment, ...segments.slice(index + 1)];
		selectedSegmentId = newSegment.id;
		saveCurrentProject({ segments });
	}

	function addSoundEffect(afterId?: string) {
		if (segments.length >= 80) { onNotice('error', t('story.max80')); return; }
		const newSegment: StorySegment = {
			id: crypto.randomUUID(),
			text: t('story.defaultSfx'),
			language: 'sfx',
			voice_id: '',
			model_id: 'stable-audio-sfx',
			tone_prompt: '',
			accent: '',
			speed: 1,
			pause_after_ms: 300,
			segment_type: 'sfx',
			speaker_name: t('story.sfx'),
			sfx_duration_seconds: 3
		};
		const index = afterId ? segments.findIndex((segment) => segment.id === afterId) : segments.length - 1;
		segments = [...segments.slice(0, index + 1), newSegment, ...segments.slice(index + 1)];
		selectedSegmentId = newSegment.id;
		saveCurrentProject({ segments });
	}

	function assignVoiceToSpeaker(speakerName: string, voiceId: string) {
		segments = segments.map((segment) =>
			segment.segment_type !== 'sfx' && (segment.speaker_name?.trim() || t('story.speaker')) === speakerName
				? { ...segment, voice_id: voiceId }
				: segment
		);
		saveCurrentProject({ segments });
	}

	function assignToneToSpeaker(speakerName: string, tonePrompt: string) {
		segments = segments.map((segment) =>
			segment.segment_type !== 'sfx' && (segment.speaker_name?.trim() || t('story.speaker')) === speakerName
				? { ...segment, tone_prompt: tonePrompt }
				: segment
		);
		saveCurrentProject({ segments });
	}

	function extractSpeakerNames(script: string) {
		const names: string[] = [];
		for (const rawLine of script.split(/\r?\n/)) {
			const line = rawLine.trim();
			if (!line || /^\[(?:효과음|sfx|톤|tone)\s*:/i.test(line)) continue;
			const match = line.match(/^(.{1,30}?)(?:\s*\[\s*(?:톤|tone)\s*:\s*[^\]]+\])?\s*:\s*.+$/);
			const name = match?.[1]?.trim();
			if (name && !names.includes(name)) names.push(name);
		}
		return names;
	}

	function importSettingFor(speakerName: string): ImportSpeakerSetting {
		const configured = importSpeakerSettings[speakerName];
		if (configured) return configured;
		const existing = segments.find(
			(segment) => segment.segment_type !== 'sfx' && (segment.speaker_name?.trim() || t('story.speaker')) === speakerName
		);
		return { voice_id: existing?.voice_id ?? '', tone_prompt: existing?.tone_prompt ?? '' };
	}

	function updateImportSpeakerSetting(speakerName: string, patch: Partial<ImportSpeakerSetting>) {
		importSpeakerSettings = {
			...importSpeakerSettings,
			[speakerName]: { ...importSettingFor(speakerName), ...patch }
		};
	}

	function openScriptImport() {
		rememberDialogTrigger();
		const nextSettings = { ...importSpeakerSettings };
		for (const speakerName of extractSpeakerNames(scriptDraft)) {
			if (!nextSettings[speakerName]) nextSettings[speakerName] = importSettingFor(speakerName);
		}
		importSpeakerSettings = nextSettings;
		showScriptImport = true;
		void focusScriptDraft();
	}

	function normalizeImportedProjectTitle(sourceTitle?: string | null) {
		const trimmed = sourceTitle?.trim();
		if (trimmed) return trimmed;
		const excerptText = excerpt(dialogueDraftForm.source_text, 36);
		return excerptText ? t('story.titleFromExcerpt', { excerpt: excerptText }) : t('story.newAudio');
	}

	function parseDialogueScriptToSegments(
		dialogueScript: string,
		options: {
			language: string;
			speakerSettings?: Record<string, ImportSpeakerSetting>;
			fallbackSpeakers?: string[];
			allowSfx?: boolean;
		}
	) {
		const lines = dialogueScript.split(/\r?\n/);
		const imported: StorySegment[] = [];
		let activeSpeaker = options.fallbackSpeakers?.[0] ?? speakerNames[0] ?? t('story.host');
		let pendingTone = '';
		const voiceBySpeaker = new Map(
			segments
				.filter((segment) => segment.segment_type !== 'sfx' && segment.speaker_name)
				.map((segment) => [segment.speaker_name as string, segment.voice_id ?? ''])
		);
		const toneBySpeaker = new Map(
			segments
				.filter((segment) => segment.segment_type !== 'sfx' && segment.speaker_name)
				.map((segment) => [segment.speaker_name as string, segment.tone_prompt ?? ''])
		);

		for (const rawLine of lines) {
			const line = rawLine.trim();
			if (!line) {
				const previous = imported.at(-1);
				if (previous) previous.pause_after_ms = Math.max(previous.pause_after_ms, 900);
				continue;
			}
			const sfxMatch = line.match(/^\[(?:효과음|sfx)\s*:\s*(.+)]$/i);
			if (sfxMatch) {
				if (options.allowSfx === false) continue;
				imported.push({
					id: crypto.randomUUID(),
					text: sfxMatch[1].trim(),
					language: 'sfx',
					voice_id: '',
					model_id: 'stable-audio-sfx',
					tone_prompt: '',
					accent: '',
					speed: 1,
					pause_after_ms: 300,
					segment_type: 'sfx',
					speaker_name: t('story.sfx'),
					sfx_duration_seconds: 3
				});
				continue;
			}
			const toneCueMatch = line.match(/^\[\s*(?:톤|tone)\s*:\s*(.+)]$/i);
			if (toneCueMatch) {
				pendingTone = toneCueMatch[1].trim();
				continue;
			}
			const dialogueMatch = line.match(/^(.{1,30}?)(?:\s*\[\s*(?:톤|tone)\s*:\s*([^\]]+)\])?\s*:\s*(.+)$/);
			if (dialogueMatch) activeSpeaker = dialogueMatch[1].trim();
			let text = (dialogueMatch?.[3] ?? line).trim();
			let explicitTone = dialogueMatch?.[2]?.trim() ?? '';
			const leadingToneMatch = text.match(/^\[\s*(?:톤|tone)\s*:\s*([^\]]+)]\s*(.*)$/i);
			if (leadingToneMatch) {
				explicitTone = leadingToneMatch[1].trim();
				text = leadingToneMatch[2].trim();
			}
			if (!text) continue;
			const speakerSetting = options.speakerSettings?.[activeSpeaker];
			imported.push({
				id: crypto.randomUUID(),
				text,
				language: options.language,
				voice_id: speakerSetting?.voice_id ?? voiceBySpeaker.get(activeSpeaker) ?? '',
				model_id: currentDefaultTtsModelId(),
				tone_prompt: explicitTone || pendingTone || speakerSetting?.tone_prompt || toneBySpeaker.get(activeSpeaker) || '',
				accent: '',
				speed: 1,
				pause_after_ms: 500,
				segment_type: 'speech',
				speaker_name: activeSpeaker,
				sfx_duration_seconds: 3
			});
			pendingTone = '';
		}
		return imported;
	}

	function applyImportedSegments(
		imported: StorySegment[],
		projectPatch: Partial<StoryProject> = {},
		noticeText: string
	) {
		if (!imported.length) {
			onNotice('error', t('story.noLines'));
			return false;
		}
		if (imported.length > 80) { onNotice('error', t('story.import80')); return false; }
		segments = imported;
		selectedSegmentId = imported[0].id;
		selectedSegmentIds = [];
		result = null;
		saveCurrentProject({ segments, result: null, ...projectPatch });
		onNotice('success', noticeText);
		return true;
	}

	function importDialogueScript() {
		const imported = parseDialogueScriptToSegments(scriptDraft, {
			language: 'ko',
			speakerSettings: importSpeakerSettings,
			allowSfx: true
		});
		const applied = applyImportedSegments(
			imported,
			{},
			t('story.imported', { count: new Set(imported.filter((item) => item.segment_type !== 'sfx').map((item) => item.speaker_name)).size })
		);
		if (applied) {
			showScriptImport = false;
			dialogReturnTarget = null;
			void focusEditorTitle();
		}
	}

	async function importMediaTranscript(target: 'script' | 'source' = 'script') {
		if (!mediaUrl.trim()) {
			onNotice('error', t('voice.ed.needUrl'));
			return;
		}
		importingMedia = true;
		try {
			const importedResponse = await apiFetch('/api/audio/media-import', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ url: mediaUrl.trim(), isolate_voice: true })
			});
			const imported = await importedResponse.json();
			const audioResponse = await fetch(audioUrl(imported.audio_url));
			if (!audioResponse.ok) throw new Error(t('story.mediaRead'));
			const form = new FormData();
			form.append('audio', new File([await audioResponse.blob()], imported.filename || 'media.wav', { type: 'audio/wav' }));
			form.append('provider', defaultSttProvider);
			form.append('language', target === 'source' ? dialogueDraftForm.language : 'ko');
			const transcriptResponse = await apiFetch('/api/stt', { method: 'POST', body: form });
			const transcript = await transcriptResponse.json();
			const lines = String(transcript.text || '')
				.split(/(?<=[.!?。！？])\s+/)
				.map((line) => line.trim())
				.filter(Boolean);
			if (!lines.length) throw new Error(t('story.noTranscript'));
			if (target === 'source') {
				dialogueDraftForm.source_text = lines.join('\n');
			} else {
				scriptDraft = lines.map((line) => `${t('story.speakerN', { n: 1 })}: ${line}`).join('\n');
			}
			onNotice('success', t('story.mediaDone'));
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			importingMedia = false;
		}
	}

	function segmentsFromDraftPayload(payload: DialogueDraftResponse) {
		const allowSfx = sfxDraftAvailable && dialogueDraftForm.include_sfx;
		const imported: StorySegment[] = [];
		const speakerNamesByRole: Record<string, string | undefined> = {
			A: payload.speakers.speaker_a,
			B: payload.speakers.speaker_b,
			...payload.additional_speakers
		};
		for (const turn of payload.turns) {
			const text = turn.text.trim();
			if (!text) continue;
			if (allowSfx && turn.sfx_cue?.trim()) {
				imported.push({
					id: crypto.randomUUID(),
					text: turn.sfx_cue.trim(),
					language: 'sfx',
					voice_id: '',
					model_id: 'stable-audio-sfx',
					tone_prompt: '',
					accent: '',
					speed: 1,
					pause_after_ms: 250,
					segment_type: 'sfx',
					speaker_name: t('story.sfx'),
					sfx_duration_seconds: 3
				});
			}
			const speakerName = speakerNamesByRole[turn.speaker];
			if (!speakerName) throw new Error(t('story.undefinedSpeaker'));
			const speakerField = draftSpeakerFields.find((field) => field.role === turn.speaker)!;
			imported.push({
				id: crypto.randomUUID(),
				text,
				language: payload.language,
				translated_text: null,
				voice_id: dialogueDraftForm[speakerField.voice] || voiceForSpeakerName(speakerName),
				model_id: currentDefaultTtsModelId(),
				tone_prompt: toneForSpeakerName(speakerName),
				accent: '',
				speed: 1,
				pause_after_ms: 500,
				segment_type: 'speech',
				speaker_name: speakerName,
				sfx_duration_seconds: 3
			});
		}
		return imported;
	}

	async function createDialogueDraft() {
		const sourceText = dialogueDraftForm.source_text.trim();
		const speakerOne = dialogueDraftForm.speaker_one.trim();
		const speakerTwo = dialogueDraftForm.speaker_two.trim();
		const topicMode = dialogueDraftForm.draft_mode === 'topic';
		if (topicMode ? sourceText.length < 4 : sourceText.length < 20) {
			onNotice('error', topicMode ? t('story.needTopic') : t('story.needSource'));
			return;
		}
		const names = draftSpeakerFields.slice(0, dialogueDraftForm.speaker_count).map((field) => dialogueDraftForm[field.name].trim());
		if (names.some((name) => !name)) {
			onNotice('error', t('story.needSpeakerNames'));
			return;
		}
		const canonicalNames = names.map((name) => name.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, ''));
		if (canonicalNames.some((name) => !name) || new Set(canonicalNames).size !== names.length) {
			onNotice('error', t('story.uniqueNames'));
			return;
		}
		const speechTurns = normalizedDialogueTurns();
		dialogueDraftForm.turns = speechTurns;
		draftingDialogue = true;
		try {
			const response = await apiFetch('/api/story-studio/dialogue-draft', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					mode: dialogueDraftForm.draft_mode,
					source_text: sourceText,
					format: dialogueDraftForm.format,
					speaker_a_name: speakerOne,
					speaker_b_name: speakerTwo,
					...(dialogueDraftForm.speaker_count >= 3 ? { speaker_c_name: dialogueDraftForm.speaker_three.trim() } : {}),
					...(dialogueDraftForm.speaker_count >= 4 ? { speaker_d_name: dialogueDraftForm.speaker_four.trim() } : {}),
					language: dialogueDraftForm.language,
					speech_turns: speechTurns,
					focus: dialogueDraftForm.focus.trim() || null,
					include_sfx_cues: sfxDraftAvailable && dialogueDraftForm.include_sfx
				})
			});
			const payload = (await response.json()) as DialogueDraftResponse;
			const importedSegments = segmentsFromDraftPayload(payload);
			if (!importedSegments.length) {
				throw new Error(t('story.noDraftLines'));
			}
			const draftTitle = payload.title.trim() || normalizeImportedProjectTitle();
			const project =
				mode === 'detail' && selectedProjectId
					? selectedProject
					: createProject(draftTitle);
			if (!project) throw new Error(t('story.noProject'));
			if (mode !== 'detail' || !selectedProjectId) {
				const nextProjects = [project, ...projects];
				projects = nextProjects;
				persistProjects(nextProjects);
				openProject(project.id, nextProjects);
			}
			title = draftTitle;
			showDialogueDraft = false;
			dialogReturnTarget = null;
			applyImportedSegments(
				importedSegments,
				{
					title: draftTitle,
					dialogue_format: dialogueDraftForm.format,
					source_text: topicMode ? '' : sourceText,
					source_excerpt: topicMode ? t('story.topicPrefix', { topic: excerpt(sourceText, 200) }) : excerpt(sourceText, 220)
				},
				topicMode
					? t('story.draftTopicDone')
					: t('story.draftSourceDone')
			);
			await focusEditorTitle();
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			draftingDialogue = false;
		}
	}

	function duplicateSegment(id: string) {
		if (segments.length >= 80) { onNotice('error', t('story.max80')); return; }
		const source = segments.find((segment) => segment.id === id);
		if (!source) return;
		const clone = { ...source, id: crypto.randomUUID(), text: source.text };
		const index = segments.findIndex((segment) => segment.id === id);
		segments = [...segments.slice(0, index + 1), clone, ...segments.slice(index + 1)];
		selectedSegmentId = clone.id;
		saveCurrentProject({ segments });
	}

	function deleteSegment(id: string) {
		if (segments.length <= 1) {
			onNotice('info', t('story.needOne'));
			return;
		}
		const index = segments.findIndex((segment) => segment.id === id);
		segments = segments.filter((segment) => segment.id !== id);
		selectedSegmentIds = selectedSegmentIds.filter((segmentId) => segmentId !== id);
		if (selectedSegmentId === id) selectedSegmentId = segments[Math.max(0, index - 1)]?.id ?? segments[0].id;
		saveCurrentProject({ segments });
	}

	function updateSegment(id: string, patch: Partial<StorySegment>) {
		segments = segments.map((segment) => (segment.id === id ? { ...segment, ...patch } : segment));
		saveCurrentProject({ segments });
	}

	function isSegmentSelected(id: string) {
		return selectedSegmentIds.includes(id);
	}

	function toggleSegmentSelection(id: string, checked: boolean) {
		selectedSegmentId = id;
		selectedSegmentIds = checked ? Array.from(new Set([...selectedSegmentIds, id])) : selectedSegmentIds.filter((segmentId) => segmentId !== id);
	}

	function toggleAllSegments(checked: boolean) {
		selectedSegmentIds = checked ? segments.map((segment) => segment.id) : [];
	}

	function applyPatchToSelectedSegments(patch: Partial<StorySegment>, notice = t('story.appliedSelected')) {
		const validIds = selectedSegmentIds.filter((id) => segments.some((segment) => segment.id === id));
		if (!validIds.length) {
			onNotice('info', t('story.pickSegments'));
			return;
		}
		const targetIds = new Set(validIds);
		segments = segments.map((segment) => (targetIds.has(segment.id) ? { ...segment, ...patch } : segment));
		saveCurrentProject({ segments });
		onNotice('success', t('story.appliedCount', { count: validIds.length, notice }));
	}

	function applyCurrentSettingsToSelectedSegments() {
		if (!selectedSegment) return;
		applyPatchToSelectedSegments(
			{
				model_id: selectedSegment.model_id ?? currentDefaultTtsModelId(),
				voice_id: selectedSegment.voice_id ?? '',
				language: selectedSegment.language,
				accent: selectedSegment.accent ?? '',
				tone_prompt: selectedSegment.tone_prompt ?? '',
				speed: selectedSegment.speed,
				pause_after_ms: selectedSegment.pause_after_ms
			},
			t('story.appliedCurrent')
		);
	}

	async function translateSegment(id: string) {
		const segment = segments.find((item) => item.id === id);
		if (!segment) return;
		const targetLanguage = segment.language || 'en';
		if (!segment.text.trim()) {
			onNotice('error', t('story.needText'));
			return;
		}
		if (targetLanguage === 'ko') {
			onNotice('info', t('story.pickLanguage'));
			return;
		}
		translatingSegmentId = id;
		try {
			const response = await apiFetch('/api/translate', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ text: segment.text, languages: [targetLanguage] })
			});
			const payload = await response.json();
			const translated = payload.translations?.[targetLanguage];
			if (!translated) {
				onNotice('error', t('story.emptyTranslation'));
				return;
			}
			updateSegment(id, { translated_text: translated });
			onNotice('success', t('story.translated'));
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			translatingSegmentId = '';
		}
	}

	function insertTag(tag: string) {
		if (!selectedSegment) return;
		updateSegment(selectedSegment.id, { text: `${selectedSegment.text.trim()} ${tag}`.trim() });
	}

	function reorderSegment(sourceId: string, targetId: string) {
		if (sourceId === targetId) return;
		const sourceIndex = segments.findIndex((segment) => segment.id === sourceId);
		const targetIndex = segments.findIndex((segment) => segment.id === targetId);
		if (sourceIndex < 0 || targetIndex < 0) return;
		const next = [...segments];
		const [moved] = next.splice(sourceIndex, 1);
		next.splice(targetIndex, 0, moved);
		segments = next;
		selectedSegmentId = sourceId;
		saveCurrentProject({ segments });
	}

	function moveSegment(id: string, direction: -1 | 1) {
		const sourceIndex = segments.findIndex((segment) => segment.id === id);
		const targetIndex = sourceIndex + direction;
		if (sourceIndex < 0 || targetIndex < 0 || targetIndex >= segments.length) return;
		const next = [...segments];
		const [moved] = next.splice(sourceIndex, 1);
		next.splice(targetIndex, 0, moved);
		segments = next;
		selectedSegmentId = id;
		saveCurrentProject({ segments });
		onNotice('info', t('story.moved', { n: targetIndex + 1 }));
	}

	function requestGenerateStory() {
		const usableSegments = getUsableSegments();
		if (!usableSegments.length) {
			onNotice('error', t('story.needSegments'));
			return;
		}
		if (unavailableSegmentCount) {
			onNotice('error', t('story.modelsNeeded', { count: unavailableSegmentCount }));
			return;
		}
		if (translationNeededCount) {
			onNotice('error', t('story.translationsNeeded', { count: translationNeededCount }));
			return;
		}
		if (missingVoiceCount) { onNotice('error', t('story.voiceDeleted')); return; }
		rememberDialogTrigger();
		showGenerationConfirm = true;
		void focusGenerationCancel();
	}

	async function generateStory() {
		const usableSegments = getUsableSegments();
		if (!usableSegments.length || unavailableSegmentCount || translationNeededCount || missingVoiceCount || busy) return;
		busy = true;
		await flushProjects();
		if (!storageReady || pendingProjects.size || saveError) {
			busy = false;
			onNotice('error', t('story.saveFirst'));
			return;
		}
		showGenerationConfirm = false;
		dialogReturnTarget = null;
		void focusEditorTitle();
		const progressId = crypto.randomUUID();
		const stopProgress = watchProgress(progressId);
		const generatingProjectId = selectedProjectId;
		try {
			const response = await apiFetch('/api/story-studio/generate', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					title,
					project_id: generatingProjectId,
					progress_id: progressId,
					default_model_id: currentDefaultTtsModelId(),
					normalize_output: true,
					segments: storyGenerationSegments(segments, currentDefaultTtsModelId())
				})
			});
			const generatedResult = (await response.json()) as StoryStudioResult;
			const savedResponse = await apiFetch(`/api/story-studio/projects/${encodeURIComponent(generatingProjectId)}`);
			const saved = (await savedResponse.json()) as StoryProject;
			savedRevisions.set(saved.id, saved.revision ?? 0);
			projects = projects.map((project) => project.id === saved.id ? saved : project);
			fingerprints.set(saved.id, projectFingerprint(saved));
			if (selectedProjectId === generatingProjectId) result = generatedResult;
			persistProjects(projects, false);
			onNotice('success', t('story.finished'));
			stopProgress(t('story.done'));
		} catch (error) {
			stopProgress();
			generationProgress = { percent: 0, message: '', elapsed: 0, active: false };
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			busy = false;
		}
	}
</script>

<div class="story-storage-status" class:warning={saveState === 'error'} role="status">
	<span>{saveState === 'loading' ? t('story.save.loading') : saveState === 'saving' ? t('story.save.saving') : saveState === 'error' ? t('story.save.error') : t('story.save.saved')}</span>
	{#if saveError}<p>{saveError}</p><button class="secondary-action compact" onclick={retrySaving}><RefreshCw size={15} />{t('story.save.retry')}</button>{/if}
</div>

{#if mode === 'list'}
	<div class="story-backup-toolbar">
		<label class="secondary-action"><Upload size={16} />{t('story.restore')}<input class="hidden" type="file" accept=".json,application/json" onchange={importProjectBackup} disabled={!storageReady} /></label>
	</div>
	<fieldset class="story-project-controls" disabled={!storageReady} aria-label={t('story.projectList')}>
	<StoryProjectList {projects} onCreate={newProject} onCreateAi={openDialogueDraft} onOpen={openProject} onDelete={deleteProject} />
	</fieldset>
{:else}
	<section class="story-studio">

	<fieldset class="story-editor surface" disabled={busy} aria-label={t('story.editScript')}>
		<div class="story-title-row">
			<input bind:this={storyTitleElement} class="story-title-input" value={title} maxlength="255" oninput={(event) => updateTitle(event.currentTarget.value)} aria-label={t('story.titleLabel')} />
			<div class="button-row wrap">
				<button class="secondary-action" onclick={backToList}><ArrowLeft size={17} />{t('voice.ed.list')}</button>
				<button class="secondary-action" onclick={openDialogueDraft}><Sparkles size={17} />{t('story.list.ai')}</button>
				<button class="secondary-action" onclick={openScriptImport}><FileText size={17} />{t('story.importScript')}</button>
				<button class="icon-button" onclick={downloadProjectBackup} aria-label={t('story.backup')} title={t('story.backupTitle')}><Download size={17} /></button>
				<button class="icon-button" onclick={duplicateProject} aria-label={t('story.duplicate')} title={t('tts.list.duplicateTitle')}><Copy size={17} /></button>
				<button class="icon-button story-add-button" onclick={() => addSegment()} aria-label={t('story.addLine')} title={t('story.addLine')}><Plus size={18} /></button>
				<button class="icon-button story-add-button" onclick={() => addSoundEffect()} aria-label={t('story.addSfx')} title={t('story.addSfx')}><Volume2 size={18} /></button>
				<button class="primary-action" disabled={!canGenerateStory} aria-describedby="story-generation-status" onclick={requestGenerateStory}>
					{#if busy}<Loader2 class="spin" size={18} />{t('tts.status.running')}{:else}<Sparkles size={18} />{t('story.generate')}{/if}
				</button>
			</div>
		</div>
		<div class="story-stage-strip" aria-label={t('story.steps')}>
			<span class:active={segments.length > 0}>{t('story.step.script')}</span>
			<span class:active={segments.some((segment) => segment.segment_type !== 'sfx' && ((segment.voice_id ?? '').trim() || (segment.tone_prompt ?? '').trim()))}>{t('story.step.voices')}</span>
			<span class:active={segments.some((segment) => segment.segment_type === 'sfx')}>{t('story.sfx')}</span>
			<span class:active={Boolean(result)}>{t('story.step.audio')}</span>
		</div>
		{#if dialogueFormat || sourceExcerpt}
			<div class="story-origin-band" aria-label={t('story.draftMeta')}>
				{#if dialogueFormat}<span>{t('story.draftFormat', { format: dialogueFormatOptions.find((option) => option.value === dialogueFormat)?.label ?? dialogueFormat })}</span>{/if}
				{#if sourceExcerpt}<p>{sourceExcerpt}</p>{/if}
			</div>
		{/if}
		<div class="story-meta-row">
			<div class="story-detail-stats" aria-label={t('story.statsLabel')}>
				<span>{t('story.stat.segments', { n: segments.length })}</span>
				<span>{t('story.stat.words', { n: totalWords })}</span>
				<span>{t('story.stat.pause', { n: estimatedPause.toFixed(1) })}</span>
				<span>{t('story.stat.speakers', { n: speakerNames.length })}</span>
			</div>
			<p
				id="story-generation-status"
				class:warning={unavailableSegmentCount > 0 || translationNeededCount > 0}
				class="story-generation-summary"
				aria-live="polite"
			>
				{#if unavailableSegmentCount > 0}
					{t('story.sum.models', { count: unavailableSegmentCount })}
					{#if translationNeededCount > 0} · {t('story.sum.translation', { count: translationNeededCount })}{/if}
				{:else if missingVoiceCount > 0}
					{t('story.sum.voices', { count: missingVoiceCount })}
				{:else if translationNeededCount > 0}
					{t('story.sum.translation', { count: translationNeededCount })}
				{:else}
					{t('story.sum.ready', { ready: usableSegmentCount, total: segments.length })} · {result ? t('story.sum.replace') : t('story.sum.new')}
				{/if}
			</p>
		</div>
		{#if unassignedSpeakerCount > 0}<p class="story-casting-note">{t('story.casting', { count: unassignedSpeakerCount })}</p>{/if}
		{#if sourceExcerpt}<details class="story-source-review"><summary>{t('story.sourceReview')}</summary><p>{selectedProject?.source_text || sourceExcerpt}</p></details>{/if}

		<ProgressPanel progress={generationProgress} fallbackMessage={t('story.progress')} />

		<div class="story-batch-toolbar" aria-label={t('story.batch')}>
			<label class="story-select-all">
				<input type="checkbox" checked={allSegmentsSelected} onchange={(event) => toggleAllSegments(event.currentTarget.checked)} />
				<span>{allSegmentsSelected ? t('story.deselectAll') : t('cover.selectAll')}</span>
			</label>
			<div class="story-batch-copy">
				<strong>{selectedSegmentCount ? t('story.nSelected', { count: selectedSegmentCount }) : t('story.bulk')}</strong>
			</div>
			<div class="story-batch-actions">
				<button class="secondary-action compact" disabled={!selectedSegmentCount} onclick={applyCurrentSettingsToSelectedSegments}>{t('story.insp.applyCurrent')}</button>
			</div>
		</div>

		<div class="story-segment-list">
			{#each segments as segment, index (segment.id)}
				<article
					class:active={segment.id === selectedSegmentId}
					class:batch-selected={isSegmentSelected(segment.id)}
					class:dragging={segment.id === draggedSegmentId}
					class="story-segment-row"
					ondragover={(event) => event.preventDefault()}
					ondrop={(event) => {
						event.preventDefault();
						if (draggedSegmentId) reorderSegment(draggedSegmentId, segment.id);
						draggedSegmentId = null;
					}}
				>
					<div class="segment-leading">
						<label class="segment-select" title={t('story.segSelect', { n: index + 1 })}>
							<input type="checkbox" checked={isSegmentSelected(segment.id)} onchange={(event) => toggleSegmentSelection(segment.id, event.currentTarget.checked)} aria-label={t('story.segSelect', { n: index + 1 })} />
						</label>
						<button
							class="segment-grip"
							draggable="true"
							onclick={() => (selectedSegmentId = segment.id)}
							ondragstart={(event) => {
								draggedSegmentId = segment.id;
								event.dataTransfer?.setData('text/plain', segment.id);
							}}
							ondragend={() => (draggedSegmentId = null)}
							aria-label={t('story.segGrip', { n: index + 1 })}
							title={t('story.segGripTitle')}
						>
							<span>{index + 1}</span>
						</button>
					</div>
					<div class="segment-body">
						<div class="segment-meta">
							<button class:sfx={segment.segment_type === 'sfx'} onclick={() => (selectedSegmentId = segment.id)}>
								{segment.segment_type === 'sfx' ? t('story.sfx') : segment.speaker_name || t('story.speaker')}
							</button>
							{#if segment.segment_type !== 'sfx'}
								<span>{voices.find((voice) => voice.id === segment.voice_id)?.name ?? t('ttsws.defaultVoice')}</span>
								<span>{languages.find((item) => item.code === segment.language)?.label ?? segment.language}</span>
							{/if}
							<span>{textSourceLabel(segment)}</span>
							{#if segment.tone_prompt}<em>({segment.tone_prompt})</em>{/if}
						</div>
						<textarea
							value={segment.text}
							oninput={(event) => updateSegment(segment.id, { text: event.currentTarget.value, translated_text: null })}
							onfocus={() => (selectedSegmentId = segment.id)}
							aria-label={segment.segment_type === 'sfx' ? t('story.sfxN', { n: index + 1 }) : t('story.lineN', { n: index + 1 })}
						></textarea>
						{#if segment.translated_text}
							<div class="segment-translation">
								<strong>{t('story.translationOf', { language: languages.find((item) => item.code === segment.language)?.label ?? segment.language })}</strong>
								<textarea
									value={segment.translated_text}
									oninput={(event) => updateSegment(segment.id, { translated_text: event.currentTarget.value })}
									onfocus={() => (selectedSegmentId = segment.id)}
									aria-label={t('story.segTranslation', { n: index + 1 })}
								></textarea>
							</div>
						{/if}
					</div>
					<div class="segment-actions">
						<button class="icon-button" disabled={index === 0} onclick={() => moveSegment(segment.id, -1)} aria-label={t('story.segUp', { n: index + 1 })}><ArrowUp size={17} /></button>
						<button class="icon-button" disabled={index === segments.length - 1} onclick={() => moveSegment(segment.id, 1)} aria-label={t('story.segDown', { n: index + 1 })}><ArrowDown size={17} /></button>
						<button class="icon-button" onclick={() => duplicateSegment(segment.id)} aria-label={t('story.segCopy', { n: index + 1 })}><Copy size={17} /></button>
						<button class="icon-button danger" onclick={() => deleteSegment(segment.id)} aria-label={t('story.segDelete', { n: index + 1 })}><Trash2 size={17} /></button>
					</div>
				</article>
			{/each}
		</div>
	</fieldset>

	<fieldset class="story-inspector-lock" disabled={busy} aria-label={t('story.inspectorLabel')}>
	<StoryInspector
		{selectedSegment}
		selectedIndex={selectedSegmentIndex}
		totalSegments={segments.length}
		{voices}
		{ttsModels}
		{defaultTtsModelId}
		{translatingSegmentId}
		{speakerProfiles}
		batchSelectionCount={selectedSegmentCount}
		onUpdateSegment={updateSegment}
		onTranslateSegment={translateSegment}
		onInsertTag={insertTag}
		onApplyCurrentToSelected={applyCurrentSettingsToSelectedSegments}
		onAssignVoiceToSpeaker={assignVoiceToSpeaker}
		onAssignToneToSpeaker={assignToneToSpeaker}
	/>
	</fieldset>

	<StoryPlayer {result} projectId={selectedProjectId} stale={resultStale} {onNotice} />
	</section>
{/if}

{#if showGenerationConfirm}
	<div class="dialog-backdrop">
		<div class="confirm-dialog surface" role="dialog" aria-modal="true" aria-labelledby="story-generate-confirm-title" tabindex="-1" onkeydown={(event) => trapDialogFocus(event, closeGenerationConfirm)}>
			<div class="confirm-dialog-heading">
				<h2 id="story-generate-confirm-title">{t('story.confirm.title')}</h2>
			</div>
			<div class="confirm-summary">
				<div>
					<span>{t('story.confirm.segments')}</span>
					<strong>{t('home.count', { count: usableSegmentCount })}</strong>
				</div>
				<div>
					<span>{t('story.confirm.words')}</span>
					<strong>{totalWords}</strong>
				</div>
				<div>
					<span>{t('story.confirm.pause')}</span>
					<strong>{t('story.insp.seconds', { value: estimatedPause.toFixed(1) })}</strong>
				</div>
				<div>
					<span>{t('tts.set.voice')}</span>
					<strong>{usedVoices.length ? usedVoices.join(', ') : t('story.confirm.auto')}</strong>
				</div>
				{#each speakerProfiles as speaker (speaker.name)}
					<div><span>{speaker.name}</span><strong>{speaker.has_mixed_voices ? t('story.insp.mixedVoices') : voices.find((voice) => voice.id === speaker.voice_id)?.name ?? t('ttsws.defaultVoice')}</strong></div>
				{/each}
				<div>
					<span>{t('story.confirm.how')}</span>
					<strong>{result ? t('story.confirm.replace') : t('story.sum.new')}</strong>
				</div>
			</div>
			<div class="dialog-actions">
				<button bind:this={generationCancelElement} class="secondary-action" onclick={closeGenerationConfirm}>{t('common.cancel')}</button>
				<button class="primary-action" onclick={generateStory}><Sparkles size={18} />{t('story.make')}</button>
			</div>
		</div>
	</div>
{/if}

{#if showDialogueDraft}
	<div class="dialog-backdrop">
		<div class="script-import-dialog dialogue-draft-dialog surface" role="dialog" aria-modal="true" aria-labelledby="dialogue-draft-title" tabindex="-1" onkeydown={(event) => trapDialogFocus(event, closeDialogueDraft)}>
			<div class="confirm-dialog-heading">
				<div class="inline-flex items-center gap-1"><h2 id="dialogue-draft-title" class="inline-flex items-center gap-1">{t('story.list.ai')}</h2><HelpPopover label={t('story.list.ai')} text={dialogueDraftForm.draft_mode === 'topic' ? t('story.draft.helpTopic') : t('story.draft.helpSource')} /></div>
				<div class="draft-mode-toggle" role="radiogroup" aria-label={t('story.draft.how')}>
					<button type="button" role="radio" aria-checked={dialogueDraftForm.draft_mode === 'topic'} class:active={dialogueDraftForm.draft_mode === 'topic'} disabled={draftingDialogue || importingMedia} onclick={() => (dialogueDraftForm.draft_mode = 'topic')}>{t('story.draft.topicMode')}</button>
					<button type="button" role="radio" aria-checked={dialogueDraftForm.draft_mode === 'source'} class:active={dialogueDraftForm.draft_mode === 'source'} disabled={draftingDialogue || importingMedia} onclick={() => (dialogueDraftForm.draft_mode = 'source')}>{t('story.draft.sourceMode')}</button>
				</div>
			</div>
			<fieldset class="story-editor-lock dialogue-draft-grid" disabled={draftingDialogue || importingMedia}>
				<label class="dialogue-draft-source">
					<span>{dialogueDraftForm.draft_mode === 'topic' ? t('story.draft.topic') : t('story.draft.source')}</span>
					<textarea bind:this={dialogueSourceElement} bind:value={dialogueDraftForm.source_text} maxlength="60000" aria-label={dialogueDraftForm.draft_mode === 'topic' ? t('story.draft.topic') : t('story.draft.source')} placeholder={dialogueDraftForm.draft_mode === 'topic' ? t('story.draft.topicPlaceholder') : ''}></textarea>
					<small>{dialogueDraftForm.draft_mode === 'topic' ? t('story.draft.topicNote') : t('story.draft.sourceNote')}</small>
				</label>
				<div class="dialogue-draft-fields">
					<label><span>{t('story.draft.count')}</span><select bind:value={dialogueDraftForm.speaker_count} aria-label={t('story.draft.count')} disabled={draftingDialogue}>
						<option value={2}>{t('story.insp.speakerCount', { count: 2 })}</option><option value={3}>{t('story.insp.speakerCount', { count: 3 })}</option><option value={4}>{t('story.insp.speakerCount', { count: 4 })}</option>
					</select></label>
					<label>
						<span>{t('story.draft.format')}</span>
						<select bind:value={dialogueDraftForm.format} aria-label={t('story.draft.format')}>
							{#each dialogueFormatOptions as option (option.value)}
								<option value={option.value}>{option.label}</option>
							{/each}
						</select>
						<small>{dialogueFormatOptions.find((option) => option.value === dialogueDraftForm.format)?.description}</small>
					</label>
					<div class="dialogue-draft-speakers">
						{#each draftSpeakerFields.slice(0, dialogueDraftForm.speaker_count) as field (field.role)}
							<label><span>{field.label}</span><input bind:value={dialogueDraftForm[field.name]} maxlength="30" aria-label={t('story.draft.speakerName', { label: field.label })} disabled={draftingDialogue} />
								<select bind:value={dialogueDraftForm[field.voice]} aria-label={t('story.draft.speakerVoice', { label: field.label })} disabled={draftingDialogue}>
									<option value="">{t('ttsws.defaultVoice')}</option>{#each voices as voice (voice.id)}<option value={voice.id}>{voice.name}</option>{/each}
								</select>
							</label>
						{/each}
					</div>
					<div class="dialogue-draft-row">
						<label>
							<span>{t('language.label')}</span>
							<select bind:value={dialogueDraftForm.language} aria-label={t('story.draft.language')}>
								{#each languages.filter((item) => dialogueLanguages.includes(item.code as DialogueLanguage)) as language (language.code)}
									<option value={language.code}>{language.label}</option>
								{/each}
							</select>
						</label>
						<label>
							<span>{t('sound.duration')}</span>
							<select value={dialogueDraftForm.length} onchange={(event) => updateDialogueLength(event.currentTarget.value as DialogueDraftForm['length'])} aria-label={t('story.draft.length')}>
								{#each dialogueLengthOptions as option (option.value)}
									<option value={option.value}>{option.label}</option>
								{/each}
							</select>
						</label>
						<label>
							<span>{t('story.draft.turns')}</span>
							<input bind:value={dialogueDraftForm.turns} type="number" min="4" max="18" step="1" aria-label={t('story.draft.turnsLabel')} />
						</label>
					</div>
					<label>
						<span>{t('story.draft.focus')}</span>
						<input bind:value={dialogueDraftForm.focus} placeholder={t('story.draft.focusPlaceholder')} aria-label={t('story.draft.focus')} />
					</label>
					<label class="dialogue-draft-toggle">
						<input bind:checked={dialogueDraftForm.include_sfx} type="checkbox" aria-label={t('story.draft.sfxCues')} aria-describedby="dialogue-sfx-status" disabled={!sfxDraftAvailable} />
						<span>{t('story.draft.sfxCues')}</span>
					</label>
					<small id="dialogue-sfx-status">{sfxDraftAvailable ? t('story.draft.sfxOk') : t('story.draft.sfxOff')}</small>
				</div>
			</fieldset>
			{#if dialogueDraftForm.draft_mode === 'source'}
			<div class="media-script-import">
				<input bind:value={mediaUrl} placeholder={t('story.media.placeholder')} aria-label={t('story.media.sourceLabel')} disabled={importingMedia || draftingDialogue} />
				<button class="secondary-action" disabled={importingMedia || draftingDialogue || !mediaUrl.trim()} onclick={() => importMediaTranscript('source')}>
					{#if importingMedia}<Loader2 class="spin" size={17} />{t('story.media.busy')}{:else}<FileText size={17} />{t('story.media.fetch')}{/if}
				</button>
			</div>
			<p class="field-helper">{t('story.media.note')}</p>
			{/if}
			<div class="dialog-actions">
				<button class="secondary-action" disabled={draftingDialogue || importingMedia} onclick={closeDialogueDraft}>{t('common.cancel')}</button>
				<button class="primary-action" disabled={draftingDialogue || importingMedia || dialogueDraftForm.source_text.trim().length < (dialogueDraftForm.draft_mode === 'topic' ? 4 : 20)} onclick={createDialogueDraft}>
					{#if draftingDialogue}<Loader2 class="spin" size={18} />{t('story.draft.busy')}{:else}<Sparkles size={18} />{t('story.draft.go')}{/if}
				</button>
			</div>
		</div>
	</div>
{/if}

{#if showScriptImport}
	<div class="dialog-backdrop">
		<div class="script-import-dialog script-import-sheet surface" role="dialog" aria-modal="true" aria-labelledby="script-import-title" tabindex="-1" onkeydown={(event) => trapDialogFocus(event, closeScriptImport)}>
			<div class="confirm-dialog-heading">
				<h2 id="script-import-title">{t('story.importScript')}</h2>
			</div>
			<div class="media-script-import">
				<input bind:value={mediaUrl} placeholder={t('story.media.placeholder')} aria-label={t('voice.link.aria')} />
				<button class="secondary-action" disabled={importingMedia} onclick={() => importMediaTranscript()}>
					{#if importingMedia}<Loader2 class="spin" size={17} />{t('story.media.busy')}{:else}<FileText size={17} />{t('story.media.transcribe')}{/if}
				</button>
			</div>
			<div class="script-import-workspace">
				<div class="script-draft-column">
					<textarea bind:this={scriptDraftElement} bind:value={scriptDraft} aria-label={t('story.import.script')}></textarea>
					<div class="script-format-preview">
						<code>{t('story.import.ex1')}</code>
						<code>{t('story.import.ex2')}</code>
						<code>{t('story.import.ex3')}</code>
						<code>{t('story.import.ex4')}</code>
					</div>
				</div>
				<aside class="script-speaker-map" aria-label={t('story.import.speakers')}>
					<div class="script-speaker-map-heading">
						<strong>{t('story.insp.speakers')}</strong>
						<span>{t('story.insp.speakerCount', { count: importSpeakerNames.length })}</span>
					</div>
					{#if importSpeakerNames.length}
						<div class="script-speaker-map-list">
							{#each importSpeakerNames as speakerName (speakerName)}
								<div class="script-speaker-map-row">
									<strong>{speakerName}</strong>
									<select
										value={importSettingFor(speakerName).voice_id}
										onchange={(event) => updateImportSpeakerSetting(speakerName, { voice_id: event.currentTarget.value })}
										aria-label={t('story.import.voice', { name: speakerName })}
									>
										<option value="">{t('ttsws.defaultVoice')}</option>
										{#each voices as voice (voice.id)}<option value={voice.id}>{voice.name}</option>{/each}
									</select>
									<input
										list="story-tone-options"
										value={importSettingFor(speakerName).tone_prompt}
										oninput={(event) => updateImportSpeakerSetting(speakerName, { tone_prompt: event.currentTarget.value })}
										placeholder={t('story.insp.tone')}
										aria-label={t('story.import.tone', { name: speakerName })}
									/>
								</div>
							{/each}
						</div>
					{:else}
						<p>{t('story.import.hint')}</p>
					{/if}
				</aside>
			</div>
			<datalist id="story-tone-options">
				{#each toneSuggestions as tone (tone)}<option value={tone}></option>{/each}
			</datalist>
			<div class="dialog-actions">
				<button class="secondary-action" disabled={importingMedia} onclick={closeScriptImport}>{t('common.cancel')}</button>
				<button class="primary-action" disabled={importingMedia} onclick={importDialogueScript}><FileText size={18} />{t('story.import.make')}</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.draft-mode-toggle { display: inline-flex; margin-top: 12px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	.draft-mode-toggle button { min-height: 34px; border: 0; border-right: 1px solid var(--border); background: var(--card-elevated); padding: 0 16px; color: var(--muted-foreground); font-size: 13px; cursor: pointer; }
	.draft-mode-toggle button:last-child { border-right: 0; }
	.draft-mode-toggle button.active { background: var(--primary); color: var(--primary-foreground); font-weight: 650; }
</style>
