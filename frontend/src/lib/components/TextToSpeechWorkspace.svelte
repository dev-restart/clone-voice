<script lang="ts">
	import { i18n, t } from '$lib/i18n/index.svelte';
	import { onMount, onDestroy } from 'svelte';
	import { History, RotateCcw } from '@lucide/svelte';
	import { apiFetch, apiWebSocketUrl } from '$lib/studio/api';
	import { downloadResponse } from '$lib/studio/download';
	import { generationState, rememberGenerationJobs, requestGenerationSync, type GenerationJob } from '$lib/studio/generation';
	import TtsContentList from '$lib/components/tts/TtsContentList.svelte';
	import TtsEditorForm from '$lib/components/tts/TtsEditorForm.svelte';
	import TtsResultsPanel from '$lib/components/tts/TtsResultsPanel.svelte';
	import TtsSettingsPanel from '$lib/components/tts/TtsSettingsPanel.svelte';
	import { defaultProductionSettings, getProductionTemplates, pronunciationError, readRecoveryDraft, ttsRecoveryKey, type ProductionTemplate, type TtsEntry, type TtsRecoveryDraft } from '$lib/studio/production';
	import type { ContentItem, ContentResult, ContentProductionSettings, PronunciationRule, RuntimeModelStatus, VoiceProfile } from '$lib/studio/types';

	let {
		voices,
		models,
		defaultTtsModelId = 'voxcpm',
		defaultVoiceId = '',
		defaultSourceLanguage = 'ko',
		onCreateVoice,
		contents,
		entry = null,
		onContentSaved,
		onContentDeleted,
		onNotice
	}: {
		voices: VoiceProfile[];
		models: RuntimeModelStatus[];
		defaultTtsModelId?: string;
		defaultVoiceId?: string;
		defaultSourceLanguage?: string;
		onCreateVoice?: () => void;
		contents: ContentItem[];
		entry?: TtsEntry | null;
		onContentSaved: (content: ContentItem) => void;
		onContentDeleted: (id: string) => void;
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
	} = $props();

	let queue = $state<GenerationJob[]>([]);
	let generationTargets = $state<string[]>(['ko']);
	let queueError = $state('');
	let disposed = false;
	let resultRefreshEpoch = 0;
	let resultRequest: AbortController | null = null;
	let queueFingerprint = '';
	let pendingEnqueue: { fingerprint: string; batchId: string } | null = null;
	const pendingRetryBatches = new Map<string, string>();
	const progressStops = new Set<() => void>();
	let mode = $state<'list' | 'editor'>('list');
	let selectedContentId = $state('');
	let title = $state('');
	let text = $state('');
	let selectedVoiceId = $state('');
	let modelId = $state('');
	let lastDefaultTtsModelId = $state('');
	let language = $state('ko');
	let accent = $state('');
	let tonePrompt = $state('');
	let stylePrompt = $state('');
	let speed = $state(1);
	let normalizeOutput = $state(true);
	let quality = $state<'fast' | 'balanced' | 'high'>('balanced');
	let busy = $state(false);
	let deletingResultId = $state('');
	let exportingResultId = $state('');
	let generationProgress = $state({ percent: 0, message: '', elapsed: 0, active: false });
	let translations = $state<Record<string, string>>({});
	let selectedTargets = $state<string[]>(['en', 'ja']);
	let currentResults = $state<ContentItem['results']>([]);
	let pronunciationRules = $state<PronunciationRule[]>([]);
	let savedFingerprint = $state('');
	let initialized = $state(false);
	let recoveryDraft = $state<TtsRecoveryDraft | null>(null);
	let backupFailed = $state(false);
	let busyAction = $state('');
	let previewResult = $state<{ text: string; spoken_text?: string; audio_url: string; duration_seconds: number; fingerprint: string } | null>(null);
	let dictionaryError = $derived(pronunciationError(pronunciationRules));
	let currentFingerprint = $derived(JSON.stringify(draftPayload()));
	let isDirty = $derived(currentFingerprint !== savedFingerprint);
	let previewStale = $derived(Boolean(previewResult && previewResult.fingerprint !== currentFingerprint));

	let ttsModels = $derived(models.filter((model) => model.capabilities.tts));
	let selectedModel = $derived(ttsModels.find((model) => model.id === modelId));
	let canUseVoice = $derived(selectedModel?.capabilities.voice_clone_tts ?? false);
	let hasMissingVoice = $derived(Boolean(selectedVoiceId && !voices.some((voice) => voice.id === selectedVoiceId)));
	let hasText = $derived(Boolean(text.trim()));
	let hasAvailableTtsModel = $derived(Boolean(selectedModel && selectedModel.status === 'available'));
	let canSave = $derived(hasText && !dictionaryError && !busy);
	let canGenerate = $derived(hasText && !dictionaryError && !hasMissingVoice && hasAvailableTtsModel && !busy);
	let canTranslate = $derived(hasText && selectedTargets.some((code) => code !== language) && !busy);

	$effect(() => {
		const fallback = ttsModels.find((model) => model.id === defaultTtsModelId && model.status === 'available') ?? ttsModels.find((model) => model.status === 'available') ?? ttsModels[0];
		if (fallback && !modelId) {
			modelId = fallback.id;
		}
	});

	$effect(() => {
		if (defaultTtsModelId !== lastDefaultTtsModelId) {
			const preferred = ttsModels.find((model) => model.id === defaultTtsModelId && model.status === 'available') ?? ttsModels.find((model) => model.id === defaultTtsModelId);
			if (preferred && !modelId) modelId = preferred.id;
			lastDefaultTtsModelId = defaultTtsModelId;
		}
	});

	$effect(() => {
		if (selectedModel && !canUseVoice && selectedVoiceId) selectedVoiceId = '';
	});

	onMount(() => {
		try { recoveryDraft = readRecoveryDraft(localStorage.getItem(ttsRecoveryKey)); } catch { backupFailed = true; }
		if (entry?.contentId) {
			const content = contents.find((item) => item.id === entry.contentId);
			if (content) openContent(content);
		} else if (entry?.templateId) {
			startNew(getProductionTemplates().find((template) => template.id === entry.templateId));
		} else if (entry?.newDraft) startNew();
		initialized = true;
		// The shared store observes server events even after this editor is closed.
	});

	$effect(() => {
		if (!initialized || mode !== 'editor' || !isDirty || !text.trim() || busy) return;
		const draft: TtsRecoveryDraft = {
			version: 1, contentId: selectedContentId, ...draftPayload(), updatedAt: new Date().toISOString()
		};
		try {
			localStorage.setItem(ttsRecoveryKey, JSON.stringify(draft));
			recoveryDraft = draft;
		} catch { backupFailed = true; }
	});

	onDestroy(() => {
		disposed = true;
		resultRequest?.abort();
		resultRefreshEpoch++;
		progressStops.forEach((stop) => stop());
	});

	$effect(() => {
		if (!initialized) return;
		const state = $generationState;
		const contentId = mode === 'editor' ? selectedContentId : '';
		queue = contentId ? state.jobs.filter(job => job.content_id === contentId) : [];
		queueError = state.error;
		if (!state.loaded) return;
		const finished = state.jobs.filter(job => (!contentId || job.content_id === contentId) && (job.status === 'completed' || job.status === 'failed'));
		const fingerprint = JSON.stringify([contentId, finished.map(job => [job.id, job.status, job.result_ids, job.updated_at])]);
		if (fingerprint === queueFingerprint) return;
		queueFingerprint = fingerprint;
		if (contentId || finished.length) void refreshResults(contentId);
	});

	async function refreshResults(contentId: string) {
		const epoch = ++resultRefreshEpoch;
		resultRequest?.abort();
		const controller = new AbortController(); resultRequest = controller;
		try {
			const response = await apiFetch(contentId ? `/api/contents/${contentId}` : '/api/contents', { signal: controller.signal });
			const current = await response.json();
			if (disposed || epoch !== resultRefreshEpoch || controller.signal.aborted) return;
			if (contentId) {
				if (mode !== 'editor' || contentId !== selectedContentId) return;
				currentResults = [...(current as ContentItem).results];
				onContentSaved(current as ContentItem);
			} else (current as ContentItem[]).forEach(onContentSaved);
		} catch (error) {
			if (!disposed && !controller.signal.aborted && epoch === resultRefreshEpoch) queueError = error instanceof Error ? error.message : String(error);
		}
	}

	function refreshQueue() { requestGenerationSync(); }

	function changeLanguage(value: string) {
		const previous = language;
		language = value;
		generationTargets = [...new Set([...generationTargets.filter((code) => code !== previous), value])];
	}

	function addLanguages(codes: string[]) {
		translations = { ...translations, ...Object.fromEntries(codes.filter((code) => code !== language && !(code in translations)).map((code) => [code, ''])) };
		generationTargets = [...new Set([...generationTargets, ...codes])];
	}

	async function cancelQueued(id: string) {
		if (busy) return;
		busy = true;
		try {
			const response = await apiFetch(`/api/generation-jobs/${id}/cancel`, { method: 'POST' });
			rememberGenerationJobs([await response.json()]);
		}
		catch (error) { onNotice('error', error instanceof Error ? error.message : String(error)); }
		finally { busy = false; }
	}

	async function retryJob(id: string) {
		if (busy || queue.some((job) => job.parent_job_id === id && ['queued', 'running', 'completed'].includes(job.status))) return;
		busy = true;
		const batchId = pendingRetryBatches.get(id) ?? crypto.randomUUID();
		pendingRetryBatches.set(id, batchId);
		try {
			const response = await apiFetch(`/api/generation-jobs/${id}/retry`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ batch_id: batchId }) });
			const job: GenerationJob = await response.json();
			pendingRetryBatches.delete(id);
			rememberGenerationJobs([job]);
			onNotice(job.id === id ? 'info' : 'success', job.id === id ? job.message : t('ttsws.retryQueued'));
		} catch (error) { onNotice('error', error instanceof Error ? error.message : String(error)); }
		finally { busy = false; }
	}

	function productionSettings(): ContentProductionSettings {
		return {
			model_id: modelId || null, voice_id: selectedVoiceId || null,
			language: language as ContentProductionSettings['language'], accent, tone_prompt: tonePrompt,
			style_prompt: stylePrompt, speed, normalize_output: normalizeOutput, quality,
			pronunciation_rules: pronunciationRules.map((rule) => ({ ...rule, source: rule.source.trim().normalize('NFC'), replacement: rule.replacement.trim().normalize('NFC') }))
		};
	}

	function draftPayload() {
		return { title, source_language: language, source_text: text, translations, production_settings: productionSettings() };
	}

	function applySettings(settings: ContentProductionSettings) {
		modelId = settings.model_id || defaultTtsModelId;
		selectedVoiceId = settings.voice_id || '';
		language = settings.language;
		accent = settings.accent || '';
		// The old default tone made VoxCPM2 skip precise cloning, so it is treated as not user-chosen and cleared.
		tonePrompt = settings.model_id === 'voxcpm' && settings.tone_prompt === '차분하게' && !settings.style_prompt ? '' : settings.tone_prompt || '';
		stylePrompt = settings.style_prompt || '';
		speed = settings.speed;
		normalizeOutput = settings.normalize_output;
		quality = settings.quality;
		pronunciationRules = settings.pronunciation_rules.map((rule) => ({ ...rule }));
	}

	function restoreDraft() {
		if (!recoveryDraft) return;
		const saved = contents.find((item) => item.id === recoveryDraft?.contentId);
		selectedContentId = saved?.id ?? '';
		title = recoveryDraft.title;
		text = recoveryDraft.source_text;
		translations = { ...recoveryDraft.translations };
		applySettings(recoveryDraft.production_settings);
		generationTargets = [language, ...Object.keys(translations).filter((code) => code !== language)];
		currentResults = saved?.results ?? [];
		savedFingerprint = '';
		previewResult = null;
		mode = 'editor';
	}

	function defaultTitle() {
		return t('ttsws.newTitle', { time: new Date().toLocaleString(i18n.intl, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) });
	}

	function startNew(template?: ProductionTemplate) {
		applySettings(defaultProductionSettings(defaultTtsModelId));
		selectedVoiceId = voices.some((voice) => voice.id === defaultVoiceId) ? defaultVoiceId : '';
		selectedContentId = '';
		language = template ? template.language : defaultSourceLanguage;
		generationTargets = [language];
		queue = [];
		queueFingerprint = '';
		title = template ? t('ttsws.templateTitle', { title: template.title }) : defaultTitle();
		text = template?.text ?? '';
		speed = template?.speed ?? 1;
		translations = {};
		currentResults = [];
		previewResult = null;
		savedFingerprint = template ? '' : JSON.stringify(draftPayload());
		mode = 'editor';
	}

	function openContent(content: ContentItem) {
		applySettings(content.production_settings ?? defaultProductionSettings(defaultTtsModelId));
		selectedContentId = content.id;
		language = content.source_language ?? content.production_settings?.language ?? 'ko';
		generationTargets = [language, ...Object.keys(content.translations).filter((code) => code !== language)];
		queue = [];
		queueFingerprint = '';
		void refreshQueue();
		title = content.title;
		text = content.source_text;
		translations = { ...content.translations };
		currentResults = [...content.results];
		previewResult = null;
		savedFingerprint = JSON.stringify(draftPayload());
		mode = 'editor';
	}

	function duplicateContent(content: ContentItem) {
		openContent(content);
		selectedContentId = '';
		title = t('ttsws.copyTitle', { title: content.title });
		currentResults = [];
		savedFingerprint = '';
	}

	function backToList() {
		selectedContentId = '';
		queue = [];
		resultRequest?.abort(); resultRefreshEpoch++;
		mode = 'list';
		generationProgress = { percent: 0, message: '', elapsed: 0, active: false };
	}

	let progressEpoch = 0;
	function trackProgress(message: string, progressId?: string) {
		const epoch = ++progressEpoch;
		let elapsed = 0;
		let resetTimer: ReturnType<typeof setTimeout> | undefined;
		generationProgress = { percent: 1, message, elapsed, active: true };
		const socket = progressId ? new WebSocket(apiWebSocketUrl(`/api/ws/progress/${progressId}`)) : null;
		const timer = window.setInterval(() => {
			elapsed += 1;
			if (!disposed && epoch === progressEpoch) generationProgress = { ...generationProgress, elapsed };
		}, 1000);
		const stop = (doneMessage?: string) => {
			window.clearInterval(timer);
			if (resetTimer) clearTimeout(resetTimer);
			if (socket) { socket.onmessage = null; socket.onerror = null; socket.close(); }
			if (disposed || epoch !== progressEpoch) { progressStops.delete(stop); return; }
			generationProgress = { percent: doneMessage ? 100 : 0, message: doneMessage ?? '', elapsed, active: false };
			if (doneMessage) resetTimer = setTimeout(() => {
				if (!disposed && epoch === progressEpoch) generationProgress = { percent: 0, message: '', elapsed: 0, active: false };
				progressStops.delete(stop);
			}, 1600);
			else progressStops.delete(stop);
		};
		progressStops.add(stop);
		if (socket) {
			socket.onmessage = (event) => {
				if (disposed || epoch !== progressEpoch) return;
				try {
					const payload = JSON.parse(event.data);
					generationProgress = { percent: Number(payload.percent ?? generationProgress.percent), message: payload.message ?? message, elapsed, active: !payload.done };
					if (payload.done) stop(payload.message ?? t('ttsws.jobDone'));
				} catch { /* Keep the HTTP result authoritative if a progress event is malformed. */ }
			};
			socket.onerror = () => { if (!disposed && epoch === progressEpoch) generationProgress = { ...generationProgress, message: t('ttsws.progressReconnect') }; };
		}
		return stop;
	}
	function watchProgress(progressId: string) { return trackProgress(t('ttsws.preparing'), progressId); }
	function startLocalProgress(message: string) { return trackProgress(message); }

	async function saveDraft(showSuccess = true) {
		const cleanedText = text.trim();
		if (!cleanedText || dictionaryError) {
			onNotice('error', dictionaryError || t('ttsws.needText'));
			return null;
		}
		const payload = {
			title: title.trim() || defaultTitle(),
			source_text: cleanedText,
			translations,
			production_settings: productionSettings(),
			source_language: language
		};
		const response = selectedContentId
			? await apiFetch(`/api/contents/${selectedContentId}`, {
					method: 'PATCH',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(payload)
				})
			: await apiFetch('/api/contents', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(payload)
				});
		const saved: ContentItem = await response.json();
		selectedContentId = saved.id;
		title = saved.title;
		text = saved.source_text;
		translations = { ...saved.translations };
		currentResults = [...saved.results];
		savedFingerprint = JSON.stringify(draftPayload());
		try {
			const draft = readRecoveryDraft(localStorage.getItem(ttsRecoveryKey));
			if (draft && (draft.contentId === saved.id || (!draft.contentId && draft.title === saved.title))) {
				localStorage.removeItem(ttsRecoveryKey);
				recoveryDraft = null;
			}
		} catch { backupFailed = true; }
		onContentSaved(saved);
		if (showSuccess) onNotice('success', t('ttsws.saved'));
		return saved;
	}

	async function save() {
		if (busy) return;
		busy = true;
		busyAction = 'saving';
		try { await saveDraft(); }
		catch (error) { onNotice('error', error instanceof Error ? error.message : String(error)); }
		finally { busy = false; busyAction = ''; }
	}

	async function preview() {
		if (!canGenerate) return;
		const progressId = crypto.randomUUID();
		const fingerprint = currentFingerprint;
		const stopProgress = watchProgress(progressId);
		busy = true;
		busyAction = 'preview';
		try {
			const response = await apiFetch('/api/tts/preview', {
				method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ ...productionSettings(), text, progress_id: progressId, num_step: modelId === 'voxcpm' ? (quality === 'fast' ? 4 : quality === 'high' ? 32 : 16) : 32 })
			});
			const payload = await response.json();
			if (disposed) return;
			previewResult = { ...payload, fingerprint };
			stopProgress(t('ttsws.previewReady'));
		} catch (error) {
			stopProgress();
			generationProgress = { percent: 0, message: '', elapsed: 0, active: false };
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally { busy = false; busyAction = ''; }
	}

	async function enqueueLanguages(codes: string[], overrides: Record<string, string> = {}, resultSettings?: ContentProductionSettings | null) {
		if (!canGenerate) return;
		const targets = [...new Set(codes)].filter((code) => (overrides[code] ?? (code === language ? text : translations[code]) ?? '').trim());
		if (!targets.length) { onNotice('info', t('ttsws.needTargets')); return; }
		busy = true;
		busyAction = 'enqueue';
		try {
			const saved = await saveDraft(false);
			if (!saved) return;
			const settings = resultSettings ?? productionSettings();
			const payload = {
				model_id: settings.model_id || modelId, voice_id: settings.voice_id || null,
				languages: targets, text_overrides: overrides, production_settings: settings, accent: settings.accent || null,
				tone_prompt: settings.tone_prompt || null, style_prompt: settings.style_prompt || null,
				speed: settings.speed, normalize_output: settings.normalize_output,
				num_step: (settings.model_id || modelId) === 'voxcpm' ? (settings.quality === 'fast' ? 4 : settings.quality === 'high' ? 32 : 16) : 32
			};
			const fingerprint = JSON.stringify([saved.id, payload, saved.source_text, saved.translations, saved.production_settings]);
			if (!pendingEnqueue || pendingEnqueue.fingerprint !== fingerprint) pendingEnqueue = { fingerprint, batchId: crypto.randomUUID() };
			const response = await apiFetch(`/api/contents/${saved.id}/jobs`, {
				method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ ...payload, batch_id: pendingEnqueue.batchId })
			});
			const accepted = await response.json();
			pendingEnqueue = null;
			rememberGenerationJobs(accepted.jobs ?? []);
			onNotice('success', t('ttsws.queued', { count: targets.length }));
			void refreshQueue();
		} catch (error) { onNotice('error', error instanceof Error ? error.message : String(error)); }
		finally { busy = false; busyAction = ''; }
	}

	async function generate(targetLanguage = language, targetText?: string) {
		const currentText = targetLanguage === language ? text : translations[targetLanguage];
		const overrides = targetText !== undefined && targetText !== currentText ? { [targetLanguage]: targetText } : {};
		await enqueueLanguages([targetLanguage], overrides);
	}

	async function translate(overwrite = false) {
		if (busy) return;
		const targets = selectedTargets.filter((code) => code !== language && (overwrite || !translations[code]?.trim()));
		if (!text.trim()) {
			onNotice('error', t('ttsws.needScriptTranslate'));
			return;
		}
		if (!targets.length) {
			onNotice('info', t('ttsws.needLangTranslate'));
			return;
		}
		busy = true;
		busyAction = 'translate';
		const stopProgress = startLocalProgress(t('ttsws.translating'));
		try {
			const response = await apiFetch('/api/translate', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ text, languages: targets })
			});
			const payload = await response.json();
			if (disposed) return;
			translations = { ...translations, ...(payload.translations ?? {}) };
			generationTargets = [...new Set([...generationTargets, ...Object.keys(payload.translations ?? {})])];
			stopProgress(t('ttsws.translated'));
			onNotice('success', t('ttsws.translatedNotice'));
		} catch (error) {
			stopProgress();
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			busy = false;
			busyAction = '';
		}
	}

	async function deleteContent(content: ContentItem) {
		if (!window.confirm(t('ttsws.confirmDelete', { title: content.title }))) return;
		try {
			await apiFetch(`/api/contents/${content.id}`, { method: 'DELETE' });
			onContentDeleted(content.id);
			if (selectedContentId === content.id) backToList();
			onNotice('success', t('ttsws.deleted'));
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		}
	}

	async function deleteResult(result: ContentResult) {
		if (!selectedContentId) {
			currentResults = currentResults.filter((item) => item.id !== result.id);
			return;
		}
		const resultLabel = `${result.voice_name ?? t('ttsws.defaultVoice')} · ${result.model_id ?? 'TTS'}`;
		if (!window.confirm(t('ttsws.confirmDeleteResult', { label: resultLabel }))) return;
		deletingResultId = result.id;
		try {
			const response = await apiFetch(`/api/contents/${selectedContentId}/results/${result.id}`, { method: 'DELETE' });
			const updated: ContentItem = await response.json();
			currentResults = [...updated.results];
			onContentSaved(updated);
			onNotice('success', t('ttsws.resultDeleted'));
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			deletingResultId = '';
		}
	}

	function toggleTarget(code: string) {
		selectedTargets = selectedTargets.includes(code) ? selectedTargets.filter((item) => item !== code) : [...selectedTargets, code];
	}

	async function exportResult(result: ContentResult, format: 'wav' | 'mp3' | 'zip' | 'txt') {
		if (!selectedContentId || exportingResultId) return;
		exportingResultId = result.id;
		try {
			const response = await apiFetch(`/api/contents/${selectedContentId}/results/${result.id}/export?format=${format}`);
			await downloadResponse(response, `${title.replace(/[\\/:*?"<>|]/g, '_')}-${result.language}.${format}`);
		} catch (error) { onNotice('error', error instanceof Error ? error.message : String(error)); }
		finally { exportingResultId = ''; }
	}
</script>

{#if mode === 'list'}
	{#if recoveryDraft}
		<div class="draft-recovery" role="status"><History size={20} /><div><strong>{t('ttsws.draft.title')}</strong><p>{recoveryDraft.title}</p></div><button class="secondary-action" onclick={restoreDraft}><RotateCcw size={16} />{t('ttsws.draft.restore')}</button></div>
	{/if}
	<TtsContentList {contents} onCreate={() => startNew()} onUseTemplate={startNew} onOpen={openContent} onDuplicate={duplicateContent} onDelete={deleteContent} />
{:else}
	<div class="workspace-grid tts-workspace">
		<TtsEditorForm
			{selectedContentId}
			{title}
			{text}
			{translations}
			{selectedTargets}
			{busy}
			{canSave}
			{canGenerate}
			{canTranslate}
			{modelId}
			{speed}
			{generationProgress}
			{isDirty}
			{busyAction}
			{backupFailed}
			{previewResult}
			{previewStale}
			{pronunciationRules}
			{dictionaryError}
			{language}
			{queue}
			{generationTargets}
			onLanguageChange={changeLanguage}
			onAddLanguages={addLanguages}
			onGenerateBatch={enqueueLanguages}
			onToggleGenerationTarget={(code) => (generationTargets = generationTargets.includes(code) ? generationTargets.filter((item) => item !== code) : [...generationTargets, code])}
			onCancelQueued={cancelQueued}
			onRetryJob={retryJob}
			onPreview={preview}
			onPronunciationChange={(value) => (pronunciationRules = value)}
			onBack={backToList}
			onSave={save}
			onGenerate={generate}
			onTranslate={translate}
			onTitleChange={(value) => (title = value)}
			onTextChange={(value) => (text = value)}
			onTranslationChange={(code, value) => (translations = { ...translations, [code]: value })}
			onToggleTarget={toggleTarget}
			{onNotice}
		/>

		<TtsSettingsPanel
			{busy}
			{voices}
			{ttsModels}
			{selectedModel}
			{canUseVoice}
			{selectedVoiceId}
			{modelId}
			{language}
			{accent}
			{tonePrompt}
			{stylePrompt}
			{speed}
			{normalizeOutput}
			{quality}
			onSelectedVoiceChange={(value) => (selectedVoiceId = value)}
			onModelChange={(value) => (modelId = value)}
			onLanguageChange={changeLanguage}
			{onCreateVoice}
			onAccentChange={(value) => (accent = value)}
			onTonePromptChange={(value) => (tonePrompt = value)}
			onStylePromptChange={(value) => (stylePrompt = value)}
			onSpeedChange={(value) => (speed = value)}
			onNormalizeOutputChange={(value) => (normalizeOutput = value)}
			onQualityChange={(value) => (quality = value)}
		/>
	</div>

	{#if queueError}<p class="warning-note" role="status">{t('ttsws.queueError', { error: queueError })}</p>{/if}
	<TtsResultsPanel scripts={{ ...translations, [language]: text }} results={currentResults} {deletingResultId} {exportingResultId} onExport={exportResult} onDeleteResult={deleteResult} onGenerateAgain={(result) => enqueueLanguages([result.language], { [result.language]: result.text }, result.production_settings)} {busy} />
{/if}