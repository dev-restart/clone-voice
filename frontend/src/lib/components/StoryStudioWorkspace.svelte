<script lang="ts">
	import { browser } from '$app/environment';
	import { onMount } from 'svelte';
	import { ArrowLeft, Copy, Loader2, Plus, Sparkles, Trash2 } from 'lucide-svelte';
	import { apiFetch, apiWebSocketUrl, languages } from '$lib/studio/api';
	import ProgressPanel from '$lib/components/app/ProgressPanel.svelte';
	import StoryInspector from '$lib/components/story/StoryInspector.svelte';
	import StoryPlayer from '$lib/components/story/StoryPlayer.svelte';
	import StoryProjectList from '$lib/components/story/StoryProjectList.svelte';
	import type { RuntimeModelStatus, StoryProject, StorySegment, StoryStudioResult, VoiceProfile } from '$lib/studio/types';

	let {
		voices,
		models,
		defaultTtsModelId = 'omnivoice',
		onNotice
	}: {
		voices: VoiceProfile[];
		models: RuntimeModelStatus[];
		defaultTtsModelId?: string;
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
	} = $props();

	const STORAGE_KEY = 'clonevoice.storyStudio.projects.v1';

	function currentDefaultTtsModelId() {
		return models.find((model) => model.id === defaultTtsModelId && model.capabilities.tts)?.id ?? models.find((model) => model.capabilities.tts)?.id ?? defaultTtsModelId;
	}

	function defaultSegments(): StorySegment[] {
		const modelId = currentDefaultTtsModelId();
		return [
			{
				id: crypto.randomUUID(),
				text: 'There was a boy who dreamed of flying.',
				language: 'en',
				voice_id: '',
				model_id: modelId,
				tone_prompt: 'calm, reflective',
				accent: 'american accent',
				speed: 1,
				pause_after_ms: 450
			},
			{
				id: crypto.randomUUID(),
				text: '그는 직접 만든 날개로 하늘을 나는 꿈을 꾸었습니다.',
				language: 'ko',
				voice_id: '',
				model_id: modelId,
				tone_prompt: '차분하게',
				accent: '',
				speed: 0.96,
				pause_after_ms: 650
			}
		];
	}

	function createProject(name = 'Flying with self-made wings'): StoryProject {
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
	let title = $state('Flying with self-made wings');
	let selectedSegmentId = $state('seg-1');
	let selectedSegmentIds = $state<string[]>([]);
	let draggedSegmentId = $state<string | null>(null);
	let translatingSegmentId = $state('');
	let busy = $state(false);
	let showGenerationConfirm = $state(false);
	let generationProgress = $state({ percent: 0, message: '', elapsed: 0, active: false });
	let result = $state<StoryStudioResult | null>(null);
	let segments = $state<StorySegment[]>(defaultSegments());

	let ttsModels = $derived(models.filter((model) => model.capabilities.tts));
	let selectedProject = $derived(projects.find((project) => project.id === selectedProjectId));
	let selectedSegment = $derived(segments.find((segment) => segment.id === selectedSegmentId) ?? segments[0]);
	let selectedSegmentIndex = $derived(Math.max(0, segments.findIndex((segment) => segment.id === selectedSegment?.id)));
	let selectedSegmentCount = $derived(selectedSegmentIds.length);
	let allSegmentsSelected = $derived(segments.length > 0 && selectedSegmentIds.length === segments.length);
	let totalWords = $derived(segments.reduce((sum, segment) => sum + segment.text.trim().split(/\s+/).filter(Boolean).length, 0));
	let estimatedPause = $derived(segments.reduce((sum, segment) => sum + segment.pause_after_ms, 0) / 1000);
	let usedVoices = $derived(
		segments
			.map((segment) => voices.find((voice) => voice.id === segment.voice_id)?.name)
			.filter((name, index, names): name is string => Boolean(name) && names.indexOf(name) === index)
	);
	let usableSegmentCount = $derived(segments.filter((segment) => (segment.translated_text || segment.text).trim()).length);
	let translationNeededCount = $derived(segments.filter((segment) => needsTranslationBeforeGeneration(segment)).length);
	let unavailableSegmentCount = $derived(
		segments.filter((segment) => {
			const model = ttsModels.find((item) => item.id === (segment.model_id || currentDefaultTtsModelId()));
			return !model || model.status === 'unavailable';
		}).length
	);
	let canGenerateStory = $derived(usableSegmentCount > 0 && unavailableSegmentCount === 0 && translationNeededCount === 0 && !busy);

	function getUsableSegments() {
		return segments
			.map((segment) => ({ ...segment, text: spokenTextForSegment(segment) }))
			.filter((segment) => segment.text);
	}

	function spokenTextForSegment(segment: StorySegment) {
		const translatedText = segment.translated_text?.trim();
		if (translatedText && segment.language !== 'ko') return translatedText;
		return segment.text.trim();
	}

	function textSourceLabel(segment: StorySegment) {
		if (segment.translated_text?.trim() && segment.language !== 'ko') return '생성: 번역문';
		if (needsTranslationBeforeGeneration(segment)) return '번역 필요';
		if (segment.translated_text?.trim()) return '생성: 원문';
		return '생성: 원문';
	}

	function needsTranslationBeforeGeneration(segment: StorySegment) {
		return segment.language !== 'ko' && !segment.translated_text?.trim() && /[가-힣]/.test(segment.text);
	}

	onMount(() => {
		const loaded = loadProjects();
		projects = loaded.length ? loaded : [createProject()];
	});

	function loadProjects() {
		if (!browser) return [];
		try {
			const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '[]');
			return Array.isArray(parsed) ? (parsed as StoryProject[]) : [];
		} catch {
			return [];
		}
	}

	function persistProjects(nextProjects = projects) {
		if (!browser) return;
		window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextProjects));
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
		segments = project.segments.length ? project.segments : defaultSegments();
		result = project.result ?? null;
		selectedSegmentId = segments[0]?.id ?? '';
		selectedSegmentIds = [];
		mode = 'detail';
	}

	function newProject() {
		const project = createProject('새 스토리북');
		const nextProjects = [project, ...projects];
		projects = nextProjects;
		persistProjects(nextProjects);
		openProject(project.id, nextProjects);
	}

	function backToList() {
		mode = 'list';
		generationProgress = { percent: 0, message: '', elapsed: 0, active: false };
	}

	function deleteProject(projectId: string) {
		const project = projects.find((item) => item.id === projectId);
		if (!project || !window.confirm(`'${project.title}' 스토리북을 삭제할까요?`)) return;
		const nextProjects = projects.filter((item) => item.id !== projectId);
		projects = nextProjects;
		persistProjects(nextProjects);
		if (selectedProjectId === projectId) {
			selectedProjectId = '';
			result = null;
			segments = defaultSegments();
			selectedSegmentIds = [];
			mode = 'list';
		}
		onNotice('success', '스토리북을 삭제했습니다.');
	}

	function updateTitle(value: string) {
		title = value;
		saveCurrentProject({ title: value });
	}

	function watchProgress(progressId: string) {
		let elapsed = 0;
		generationProgress = { percent: 1, message: '스토리북 생성을 준비하고 있습니다.', elapsed, active: true };
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
				finish(payload.message ?? '스토리북 오디오 생성이 완료되었습니다.');
			}
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

	function addSegment(afterId?: string) {
		const newSegment: StorySegment = {
			id: crypto.randomUUID(),
			text: '새 단락을 입력하세요.',
			language: selectedSegment?.language ?? 'ko',
			voice_id: selectedSegment?.voice_id ?? '',
			model_id: selectedSegment?.model_id ?? currentDefaultTtsModelId(),
			tone_prompt: selectedSegment?.tone_prompt ?? '',
			accent: selectedSegment?.accent ?? '',
			speed: selectedSegment?.speed ?? 1,
			pause_after_ms: 450
		};
		const index = afterId ? segments.findIndex((segment) => segment.id === afterId) : segments.length - 1;
		segments = [...segments.slice(0, index + 1), newSegment, ...segments.slice(index + 1)];
		selectedSegmentId = newSegment.id;
		saveCurrentProject({ segments });
	}

	function duplicateSegment(id: string) {
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
			onNotice('info', '스토리에는 최소 한 개의 단락이 필요합니다.');
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

	function applyPatchToSelectedSegments(patch: Partial<StorySegment>, notice = '선택한 단락에 설정을 적용했습니다.') {
		const validIds = selectedSegmentIds.filter((id) => segments.some((segment) => segment.id === id));
		if (!validIds.length) {
			onNotice('info', '일괄 적용할 단락을 먼저 선택해 주세요.');
			return;
		}
		const targetIds = new Set(validIds);
		segments = segments.map((segment) => (targetIds.has(segment.id) ? { ...segment, ...patch } : segment));
		saveCurrentProject({ segments });
		onNotice('success', `${validIds.length}개 단락에 ${notice}`);
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
			'현재 단락의 전체 설정을 적용했습니다.'
		);
	}

	function applySelectedVoiceToSelectedSegments() {
		if (!selectedSegment) return;
		applyPatchToSelectedSegments({ voice_id: selectedSegment.voice_id ?? '' }, '목소리를 적용했습니다.');
	}

	function applySelectedTimingToSelectedSegments() {
		if (!selectedSegment) return;
		applyPatchToSelectedSegments(
			{
				tone_prompt: selectedSegment.tone_prompt ?? '',
				speed: selectedSegment.speed,
				pause_after_ms: selectedSegment.pause_after_ms
			},
			'연출과 쉼을 적용했습니다.'
		);
	}

	async function translateSegment(id: string) {
		const segment = segments.find((item) => item.id === id);
		if (!segment) return;
		const targetLanguage = segment.language || 'en';
		if (!segment.text.trim()) {
			onNotice('error', '번역할 원문이 필요합니다.');
			return;
		}
		if (targetLanguage === 'ko') {
			onNotice('info', '한국어가 아닌 번역 언어를 선택해 주세요.');
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
				onNotice('error', '번역 결과가 비어 있습니다.');
				return;
			}
			updateSegment(id, { translated_text: translated });
			onNotice('success', '단락 번역을 완료했습니다.');
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

	function requestGenerateStory() {
		const usableSegments = getUsableSegments();
		if (!usableSegments.length) {
			onNotice('error', '생성할 스토리 단락이 필요합니다.');
			return;
		}
		if (unavailableSegmentCount) {
			onNotice('error', `설정이 필요한 모델을 사용하는 단락이 ${unavailableSegmentCount}개 있습니다.`);
			return;
		}
		if (translationNeededCount) {
			onNotice('error', `번역이 필요한 단락이 ${translationNeededCount}개 있습니다. 선택 언어로 번역한 뒤 생성해 주세요.`);
			return;
		}
		showGenerationConfirm = true;
	}

	async function generateStory() {
		const usableSegments = getUsableSegments();
		if (!usableSegments.length || unavailableSegmentCount || translationNeededCount) return;
		showGenerationConfirm = false;
		const progressId = crypto.randomUUID();
		const stopProgress = watchProgress(progressId);
		busy = true;
		try {
			const response = await apiFetch('/api/story-studio/generate', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					title,
					progress_id: progressId,
					default_model_id: currentDefaultTtsModelId(),
					normalize_output: true,
					segments: usableSegments.map((segment) => ({
						id: segment.id,
						text: segment.text,
						language: segment.language,
						voice_id: segment.voice_id || null,
						model_id: segment.model_id || null,
						tone_prompt: segment.tone_prompt || null,
						accent: segment.accent || null,
						speed: segment.speed,
						pause_after_ms: segment.pause_after_ms
					}))
				})
			});
			result = await response.json();
			saveCurrentProject({ result });
			onNotice('success', '스토리북 오디오 생성을 완료했습니다.');
			stopProgress('스토리북 오디오 생성이 완료되었습니다.');
		} catch (error) {
			stopProgress();
			generationProgress = { percent: 0, message: '', elapsed: 0, active: false };
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			busy = false;
		}
	}
</script>

{#if mode === 'list'}
	<StoryProjectList {projects} onCreate={newProject} onOpen={openProject} onDelete={deleteProject} />
{:else}
	<section class="story-studio">

	<div class="story-editor surface">
		<div class="story-title-row">
			<input class="story-title-input" value={title} oninput={(event) => updateTitle(event.currentTarget.value)} aria-label="스토리 제목" />
			<div class="button-row wrap">
				<button class="secondary-action" onclick={backToList}><ArrowLeft size={17} />목록</button>
				<button class="secondary-action" onclick={() => addSegment()}><Plus size={18} />단락 추가</button>
				<button class="primary-action" disabled={!canGenerateStory} onclick={requestGenerateStory}>
					{#if busy}<Loader2 class="spin" size={18} />생성 중{:else}<Sparkles size={18} />스토리북 생성{/if}
				</button>
			</div>
		</div>
		<div class="story-detail-stats">
			<span>단락 {segments.length}</span>
			<span>단어 {totalWords}</span>
			<span>쉼 {estimatedPause.toFixed(1)}s</span>
			<span>목소리 {usedVoices.length || 0}</span>
		</div>

		<div class="story-preflight" aria-label="스토리북 생성 전 확인">
			<div>
				<strong>{usableSegmentCount}/{segments.length}</strong>
				<span>생성 가능한 단락</span>
			</div>
			<div class:warning={unavailableSegmentCount > 0}>
				<strong>{unavailableSegmentCount ? `${unavailableSegmentCount}개 확인 필요` : '모델 준비됨'}</strong>
				<span>모델 상태</span>
			</div>
			<div class:warning={translationNeededCount > 0}>
				<strong>{translationNeededCount ? `${translationNeededCount}개 번역 필요` : '번역 준비됨'}</strong>
				<span>선택 언어 본문</span>
			</div>
			<div>
				<strong>{result ? '기존 결과 덮어쓰기' : '새 결과 저장'}</strong>
				<span>생성 후 저장 방식</span>
			</div>
		</div>

		<ProgressPanel progress={generationProgress} fallbackMessage="스토리북 생성 중입니다." />

		<div class="story-batch-toolbar" aria-label="스토리 단락 일괄 설정">
			<label class="story-select-all">
				<input type="checkbox" checked={allSegmentsSelected} onchange={(event) => toggleAllSegments(event.currentTarget.checked)} />
				<span>{allSegmentsSelected ? '전체 해제' : '전체 선택'}</span>
			</label>
			<div class="story-batch-copy">
				<strong>{selectedSegmentCount ? `${selectedSegmentCount}개 단락 선택됨` : '단락을 선택하면 일괄 설정할 수 있습니다.'}</strong>
				<p>오른쪽에서 기준 단락을 조정한 뒤 목소리, 모델, 톤과 쉼을 선택 단락에 한 번에 적용합니다.</p>
			</div>
			<div class="story-batch-actions">
				<button class="secondary-action compact" disabled={!selectedSegmentCount} onclick={applyCurrentSettingsToSelectedSegments}>현재 설정 적용</button>
				<button class="secondary-action compact" disabled={!selectedSegmentCount} onclick={applySelectedVoiceToSelectedSegments}>목소리만</button>
				<button class="secondary-action compact" disabled={!selectedSegmentCount} onclick={applySelectedTimingToSelectedSegments}>연출/쉼</button>
			</div>
		</div>

		<div class="story-segment-list">
			{#each segments as segment, index}
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
						<label class="segment-select" title={`단락 ${index + 1} 일괄 설정 선택`}>
							<input type="checkbox" checked={isSegmentSelected(segment.id)} onchange={(event) => toggleSegmentSelection(segment.id, event.currentTarget.checked)} aria-label={`단락 ${index + 1} 일괄 설정 선택`} />
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
							aria-label={`단락 ${index + 1} 선택 및 드래그 이동`}
							title="숫자를 드래그해서 단락 순서를 바꿉니다"
						>
							<span>{index + 1}</span>
						</button>
					</div>
					<div class="segment-body">
						<div class="segment-meta">
							<button onclick={() => (selectedSegmentId = segment.id)}>{voices.find((voice) => voice.id === segment.voice_id)?.name ?? 'Auto Voice'}</button>
							<span>{languages.find((item) => item.code === segment.language)?.label ?? segment.language}</span>
							<span>{ttsModels.find((model) => model.id === (segment.model_id || currentDefaultTtsModelId()))?.label ?? 'TTS 모델'}</span>
							<span>{textSourceLabel(segment)}</span>
							{#if segment.tone_prompt}<em>({segment.tone_prompt})</em>{/if}
						</div>
						<textarea
							value={segment.text}
							oninput={(event) => updateSegment(segment.id, { text: event.currentTarget.value, translated_text: null })}
							onfocus={() => (selectedSegmentId = segment.id)}
							aria-label={`스토리 단락 ${index + 1}`}
						></textarea>
						{#if segment.translated_text}
							<div class="segment-translation">
								<strong>{languages.find((item) => item.code === segment.language)?.label ?? segment.language} 번역</strong>
								<textarea
									value={segment.translated_text}
									oninput={(event) => updateSegment(segment.id, { translated_text: event.currentTarget.value })}
									onfocus={() => (selectedSegmentId = segment.id)}
									aria-label={`스토리 단락 ${index + 1} 번역문`}
								></textarea>
							</div>
						{/if}
					</div>
					<div class="segment-actions">
						<button class="icon-button" onclick={() => duplicateSegment(segment.id)} aria-label="단락 복제"><Copy size={17} /></button>
						<button class="icon-button danger" onclick={() => deleteSegment(segment.id)} aria-label="단락 삭제"><Trash2 size={17} /></button>
					</div>
				</article>
			{/each}
		</div>
	</div>

	<StoryInspector
		{selectedSegment}
		selectedIndex={selectedSegmentIndex}
		totalSegments={segments.length}
		{voices}
		{ttsModels}
		{defaultTtsModelId}
		{translatingSegmentId}
		batchSelectionCount={selectedSegmentCount}
		onUpdateSegment={updateSegment}
		onTranslateSegment={translateSegment}
		onInsertTag={insertTag}
		onApplyToSelected={applyPatchToSelectedSegments}
		onApplyCurrentToSelected={applyCurrentSettingsToSelectedSegments}
	/>

	<StoryPlayer {result} />
	</section>
{/if}

{#if showGenerationConfirm}
	<div class="dialog-backdrop">
		<div class="confirm-dialog surface" role="dialog" aria-modal="true" aria-labelledby="story-generate-confirm-title">
			<div class="confirm-dialog-heading">
				<h2 id="story-generate-confirm-title">스토리북을 생성할까요?</h2>
				<p>아래 설정으로 단락별 음성을 생성하고 현재 스토리북에 결과를 저장합니다.</p>
			</div>
			<div class="confirm-summary">
				<div>
					<span>생성 단락</span>
					<strong>{usableSegmentCount}개</strong>
				</div>
				<div>
					<span>전체 단어</span>
					<strong>{totalWords}개</strong>
				</div>
				<div>
					<span>단락 간 쉼</span>
					<strong>{estimatedPause.toFixed(1)}초</strong>
				</div>
				<div>
					<span>목소리</span>
					<strong>{usedVoices.length ? usedVoices.join(', ') : 'Auto Voice'}</strong>
				</div>
				<div>
					<span>저장 방식</span>
					<strong>{result ? '기존 결과 덮어쓰기' : '새 결과 저장'}</strong>
				</div>
			</div>
			<p class="confirm-note">생성 중에는 진행률이 표시되며, 완료된 오디오는 하단 플레이어에서 바로 확인할 수 있습니다.</p>
			<div class="dialog-actions">
				<button class="secondary-action" onclick={() => (showGenerationConfirm = false)}>취소</button>
				<button class="primary-action" onclick={generateStory}><Sparkles size={18} />생성 시작</button>
			</div>
		</div>
	</div>
{/if}
