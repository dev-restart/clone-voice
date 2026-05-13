<script lang="ts">
	import { apiFetch, apiWebSocketUrl } from '$lib/studio/api';
	import TtsContentList from '$lib/components/tts/TtsContentList.svelte';
	import TtsEditorForm from '$lib/components/tts/TtsEditorForm.svelte';
	import TtsResultsPanel from '$lib/components/tts/TtsResultsPanel.svelte';
	import TtsSettingsPanel from '$lib/components/tts/TtsSettingsPanel.svelte';
	import type { ContentItem, ContentResult, RuntimeModelStatus, VoiceProfile } from '$lib/studio/types';

	let {
		voices,
		models,
		defaultTtsModelId = 'omnivoice',
		contents,
		onContentSaved,
		onContentDeleted,
		onNotice
	}: {
		voices: VoiceProfile[];
		models: RuntimeModelStatus[];
		defaultTtsModelId?: string;
		contents: ContentItem[];
		onContentSaved: (content: ContentItem) => void;
		onContentDeleted: (id: string) => void;
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
	} = $props();

	let mode = $state<'list' | 'editor'>('list');
	let selectedContentId = $state('');
	let title = $state('');
	let text = $state('');
	let selectedVoiceId = $state('');
	let modelId = $state('');
	let lastDefaultTtsModelId = $state('');
	let language = $state('ko');
	let accent = $state('');
	let tonePrompt = $state('차분하게');
	let stylePrompt = $state('');
	let speed = $state(1);
	let normalizeOutput = $state(true);
	let busy = $state(false);
	let deletingResultId = $state('');
	let generationProgress = $state({ percent: 0, message: '', elapsed: 0, active: false });
	let translations = $state<Record<string, string>>({});
	let selectedTargets = $state<string[]>(['en', 'ja']);
	let currentResults = $state<ContentItem['results']>([]);

	let ttsModels = $derived(models.filter((model) => model.capabilities.tts));
	let selectedModel = $derived(ttsModels.find((model) => model.id === modelId));
	let canUseVoice = $derived(selectedModel?.capabilities.voice_clone_tts ?? false);
	let hasText = $derived(Boolean(text.trim()));
	let hasAvailableTtsModel = $derived(Boolean(selectedModel && selectedModel.status === 'available'));
	let canSave = $derived(hasText && !busy);
	let canGenerate = $derived(hasText && hasAvailableTtsModel && !busy);
	let canTranslate = $derived(hasText && selectedTargets.some((code) => code !== 'ko') && !busy);

	$effect(() => {
		const fallback = ttsModels.find((model) => model.id === defaultTtsModelId && model.status === 'available') ?? ttsModels.find((model) => model.status === 'available') ?? ttsModels[0];
		if (fallback && (!ttsModels.some((model) => model.id === modelId) || selectedModel?.status === 'unavailable')) {
			modelId = fallback.id;
		}
	});

	$effect(() => {
		if (defaultTtsModelId !== lastDefaultTtsModelId) {
			const preferred = ttsModels.find((model) => model.id === defaultTtsModelId && model.status === 'available') ?? ttsModels.find((model) => model.id === defaultTtsModelId);
			if (preferred) modelId = preferred.id;
			lastDefaultTtsModelId = defaultTtsModelId;
		}
	});

	$effect(() => {
		if (!canUseVoice && selectedVoiceId) selectedVoiceId = '';
	});

	function defaultTitle() {
		return `새 음성 콘텐츠 ${new Date().toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`;
	}

	function startNew() {
		selectedContentId = '';
		title = defaultTitle();
		text = '';
		translations = {};
		currentResults = [];
		mode = 'editor';
	}

	function openContent(content: ContentItem) {
		selectedContentId = content.id;
		title = content.title;
		text = content.source_text;
		translations = { ...content.translations };
		currentResults = [...content.results];
		mode = 'editor';
	}

	function backToList() {
		mode = 'list';
		generationProgress = { percent: 0, message: '', elapsed: 0, active: false };
	}

	function watchProgress(progressId: string) {
		let elapsed = 0;
		generationProgress = { percent: 1, message: '작업을 준비하고 있습니다.', elapsed, active: true };
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
			if (payload.done) finish(payload.message ?? '음성 생성이 완료되었습니다.');
		};
		socket.onerror = () => {
			generationProgress = { ...generationProgress, message: '진행 상태 연결을 확인하고 있습니다.' };
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

	function startLocalProgress(message: string) {
		let elapsed = 0;
		generationProgress = { percent: 10, message, elapsed, active: true };
		const timer = window.setInterval(() => {
			elapsed += 1;
			generationProgress = {
				...generationProgress,
				percent: Math.min(88, generationProgress.percent + 6),
				elapsed
			};
		}, 1000);
		return (doneMessage?: string) => {
			window.clearInterval(timer);
			generationProgress = { percent: 100, message: doneMessage ?? message, elapsed, active: false };
			window.setTimeout(() => {
				generationProgress = { percent: 0, message: '', elapsed: 0, active: false };
			}, 1400);
		};
	}

	async function saveDraft(showSuccess = true) {
		const cleanedText = text.trim();
		if (!cleanedText) {
			onNotice('error', '음성으로 만들 텍스트가 필요합니다.');
			return null;
		}
		const payload = {
			title: title.trim() || defaultTitle(),
			source_text: cleanedText,
			translations
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
		onContentSaved(saved);
		if (showSuccess) onNotice('success', '콘텐츠를 저장했습니다.');
		return saved;
	}

	async function generate(targetLanguage = language, targetText = text) {
		if (!targetText.trim()) {
			onNotice('error', '음성으로 만들 텍스트가 필요합니다.');
			return;
		}
		if (!selectedModel || selectedModel.status !== 'available') {
			onNotice('error', '사용 가능한 TTS 모델을 먼저 선택하세요.');
			return;
		}
		if (targetLanguage === 'ko') {
			text = targetText;
		} else {
			translations = { ...translations, [targetLanguage]: targetText };
		}

		const progressId = crypto.randomUUID();
		const stopProgress = watchProgress(progressId);
		busy = true;
		try {
			const saved = await saveDraft(false);
			if (!saved) return;
			const response = await apiFetch(`/api/contents/${saved.id}/generate`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					progress_id: progressId,
					model_id: modelId,
					voice_id: canUseVoice ? selectedVoiceId || null : null,
					languages: [targetLanguage],
					accent: accent || null,
					tone_prompt: tonePrompt || null,
					style_prompt: stylePrompt || null,
					speed,
					normalize_output: normalizeOutput
				})
			});
			const updated: ContentItem = await response.json();
			title = updated.title;
			text = updated.source_text;
			translations = { ...updated.translations };
			currentResults = [...updated.results];
			onContentSaved(updated);
			onNotice('success', '음성 생성과 저장을 완료했습니다.');
			stopProgress('음성 생성과 저장이 완료되었습니다.');
		} catch (error) {
			stopProgress();
			generationProgress = { percent: 0, message: '', elapsed: 0, active: false };
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			busy = false;
		}
	}

	async function translate() {
		const targets = selectedTargets.filter((code) => code !== 'ko');
		if (!text.trim()) {
			onNotice('error', '번역할 대본을 먼저 입력하세요.');
			return;
		}
		if (!targets.length) {
			onNotice('info', '번역할 언어를 하나 이상 선택하세요.');
			return;
		}
		busy = true;
		const stopProgress = startLocalProgress('선택한 언어로 번역본을 생성하고 있습니다.');
		try {
			const response = await apiFetch('/api/translate', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ text, languages: targets })
			});
			const payload = await response.json();
			translations = { ...translations, ...(payload.translations ?? {}) };
			stopProgress('번역본 생성이 완료되었습니다.');
			onNotice('success', '번역본을 생성했습니다.');
		} catch (error) {
			stopProgress();
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			busy = false;
		}
	}

	async function deleteContent(content: ContentItem) {
		if (!window.confirm(`'${content.title}' 콘텐츠를 삭제할까요?`)) return;
		try {
			await apiFetch(`/api/contents/${content.id}`, { method: 'DELETE' });
			onContentDeleted(content.id);
			if (selectedContentId === content.id) backToList();
			onNotice('success', '콘텐츠를 삭제했습니다.');
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		}
	}

	async function deleteResult(result: ContentResult) {
		if (!selectedContentId) {
			currentResults = currentResults.filter((item) => item.id !== result.id);
			return;
		}
		const resultLabel = `${result.voice_name ?? '기본 목소리'} · ${result.model_id ?? 'TTS'}`;
		if (!window.confirm(`'${resultLabel}' 생성 결과를 삭제할까요?`)) return;
		deletingResultId = result.id;
		try {
			const response = await apiFetch(`/api/contents/${selectedContentId}/results/${result.id}`, { method: 'DELETE' });
			const updated: ContentItem = await response.json();
			title = updated.title;
			text = updated.source_text;
			translations = { ...updated.translations };
			currentResults = [...updated.results];
			onContentSaved(updated);
			onNotice('success', '생성 결과를 삭제했습니다.');
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			deletingResultId = '';
		}
	}

	function toggleTarget(code: string) {
		selectedTargets = selectedTargets.includes(code) ? selectedTargets.filter((item) => item !== code) : [...selectedTargets, code];
	}
</script>

{#if mode === 'list'}
	<TtsContentList {contents} onCreate={startNew} onOpen={openContent} onDelete={deleteContent} />
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
			onBack={backToList}
			onSave={() => saveDraft()}
			onGenerate={generate}
			onTranslate={translate}
			onTitleChange={(value) => (title = value)}
			onTextChange={(value) => (text = value)}
			onTranslationChange={(code, value) => (translations = { ...translations, [code]: value })}
			onToggleTarget={toggleTarget}
		/>

		<TtsSettingsPanel
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
			onSelectedVoiceChange={(value) => (selectedVoiceId = value)}
			onModelChange={(value) => (modelId = value)}
			onLanguageChange={(value) => (language = value)}
			onAccentChange={(value) => (accent = value)}
			onTonePromptChange={(value) => (tonePrompt = value)}
			onStylePromptChange={(value) => (stylePrompt = value)}
			onSpeedChange={(value) => (speed = value)}
			onNormalizeOutputChange={(value) => (normalizeOutput = value)}
		/>
	</div>

	<TtsResultsPanel results={currentResults} {deletingResultId} onDeleteResult={deleteResult} onGenerateAgain={(result) => generate(result.language, result.text)} {busy} />
{/if}
