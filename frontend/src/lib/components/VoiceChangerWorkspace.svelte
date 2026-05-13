<script lang="ts">
	import { browser } from '$app/environment';
	import { onDestroy, onMount, tick } from 'svelte';
	import { ArrowLeft, FileAudio, Loader2, Mic, Pause, Play, RotateCcw, Wand2 } from 'lucide-svelte';
	import WaveSurfer from 'wavesurfer.js';
	import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js';
	import { apiFetch, apiWebSocketUrl, audioUrl, formatTime } from '$lib/studio/api';
	import ProgressPanel from '$lib/components/app/ProgressPanel.svelte';
	import VoiceChangerProjectList from '$lib/components/conversion/VoiceChangerProjectList.svelte';
	import VoiceChangerResultsPanel from '$lib/components/conversion/VoiceChangerResultsPanel.svelte';
	import VoiceChangerSettingsPanel from '$lib/components/conversion/VoiceChangerSettingsPanel.svelte';
	import type { RuntimeModelStatus, VoiceConversionJob, VoiceProfile } from '$lib/studio/types';

	let {
		voices,
		models,
		onNotice
	}: {
		voices: VoiceProfile[];
		models: RuntimeModelStatus[];
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
	} = $props();

	type VoiceChangerProject = {
		id: string;
		title: string;
		voice_id: string;
		model_id: string;
		conversion_mode?: 'voice' | 'singing' | 'v2';
		diffusion_steps?: number;
		length_adjust?: number;
		inference_cfg_rate?: number;
		f0_condition?: boolean;
		auto_f0_adjust?: boolean;
		semi_tone_shift?: number;
		fp16?: boolean;
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
	let modelId = $state('seed-vc');
	let conversionMode = $state<'voice' | 'singing' | 'v2'>('singing');
	let diffusionSteps = $state(40);
	let lengthAdjust = $state(1.0);
	let inferenceCfgRate = $state(0.7);
	let f0Condition = $state(true);
	let autoF0Adjust = $state(true);
	let semiToneShift = $state(0);
	let fp16 = $state(true);
	let sttProvider = $state<'whisper' | 'apple-speech'>('whisper');
	let sttLanguage = $state('ko');
	let busy = $state(false);
	let realtimeLaunching = $state(false);
	let realtimeStatus = $state<{ state: 'idle' | 'launching' | 'running' | 'error'; message: string; pid?: number | null }>({
		state: 'idle',
		message: ''
	});
	let transcribing = $state(false);
	let savingSource = $state(false);
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
	let recording = $state(false);
	let recordingSeconds = $state(0);
	let recordingTimer: ReturnType<typeof setInterval> | null = null;
	let recordingStream: MediaStream | null = null;
	let progress = $state({ percent: 0, message: '', elapsed: 0, active: false });
	let recorder: MediaRecorder | null = null;
	let chunks: Blob[] = [];
	let vcModels = $derived(models.filter((model) => model.capabilities.voice_conversion));
	let selectedModel = $derived(vcModels.find((model) => model.id === modelId));
	let selectedDuration = $derived(Math.max(0, trimEnd - trimStart));
	let selectionTooShort = $derived(previewUrl && selectedDuration < 1);
	let canConvert = $derived(Boolean(file && voiceId && selectedModel?.status === 'available' && !selectionTooShort));
	let timelineTicks = $derived.by(() => {
		if (!duration) return [];
		const segments = Math.min(8, Math.max(2, Math.ceil(duration)));
		return Array.from({ length: segments + 1 }, (_, index) => (duration / segments) * index);
	});

	onMount(() => {
		projects = loadProjects();
		void loadHistory();
	});

	onDestroy(() => {
		wave?.destroy();
		if (previewUrl) URL.revokeObjectURL(previewUrl);
		clearRecordingTimer();
		recordingStream?.getTracks().forEach((track) => track.stop());
	});

	$effect(() => {
		if (!voiceId && voices.length) voiceId = voices[0].id;
	});

	$effect(() => {
		if (vcModels.length && !vcModels.some((model) => model.id === modelId)) {
			modelId = vcModels[0].id;
		}
	});

	function clearRecordingTimer() {
		if (!recordingTimer) return;
		clearInterval(recordingTimer);
		recordingTimer = null;
	}

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
			title: `새 보이스 체인저 ${new Date().toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`,
			voice_id: voiceId,
			model_id: modelId,
			conversion_mode: conversionMode,
			diffusion_steps: diffusionSteps,
			length_adjust: lengthAdjust,
			inference_cfg_rate: inferenceCfgRate,
			f0_condition: f0Condition,
			auto_f0_adjust: autoF0Adjust,
			semi_tone_shift: semiToneShift,
			fp16,
			source_audio_url: null,
			source_audio_name: null,
			transcript: '',
			versions: [],
			created_at: now,
			updated_at: now
		};
	}

	function startNew() {
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
		modelId = project.model_id || modelId;
		conversionMode = project.conversion_mode || 'singing';
		diffusionSteps = project.diffusion_steps ?? (conversionMode === 'singing' ? 40 : 25);
		lengthAdjust = project.length_adjust ?? 1.0;
		inferenceCfgRate = project.inference_cfg_rate ?? 0.7;
		f0Condition = project.f0_condition ?? conversionMode === 'singing';
		autoF0Adjust = project.auto_f0_adjust ?? conversionMode === 'singing';
		semiToneShift = project.semi_tone_shift ?? 0;
		fp16 = project.fp16 ?? true;
		transcript = project.transcript ?? '';
		projectVersions = project.versions ?? [];
		outputUrl = projectVersions[0]?.output_audio_url ?? '';
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
			voice_id: voiceId,
			model_id: modelId,
			conversion_mode: conversionMode,
			diffusion_steps: diffusionSteps,
			length_adjust: lengthAdjust,
			inference_cfg_rate: inferenceCfgRate,
			f0_condition: f0Condition,
			auto_f0_adjust: autoF0Adjust,
			semi_tone_shift: semiToneShift,
			fp16,
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
		if (!project || !window.confirm(`'${project.title}' 작업을 삭제할까요?`)) return;
		const nextProjects = projects.filter((item) => item.id !== id);
		projects = nextProjects;
		persistProjects(nextProjects);
		if (selectedProjectId === id) {
			selectedProjectId = '';
			projectVersions = [];
			outputUrl = '';
			mode = 'list';
		}
		onNotice('success', '보이스 체인저 작업을 삭제했습니다.');
	}

	function sourceUrlFromJob(job?: VoiceConversionJob) {
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
			file = new File([blob], project.source_audio_name || sourceUrl.split('/').pop() || 'voice-change-source.wav', { type: blob.type || 'audio/wav' });
			if (previewUrl) URL.revokeObjectURL(previewUrl);
			previewUrl = URL.createObjectURL(file);
			await setupWaveform(previewUrl);
		} catch {
			// Existing conversion result can still be played even if the source file cannot be restored.
		}
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
			onNotice('success', '원본 음성을 작업에 저장했습니다.');
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

	function onFileChange(event: Event) {
		file = (event.target as HTMLInputElement).files?.[0] ?? null;
		if (!file) return;
		if (previewUrl) URL.revokeObjectURL(previewUrl);
		previewUrl = URL.createObjectURL(file);
		void setupWaveform(previewUrl);
		if (!title.trim()) title = file.name.replace(/\.[^.]+$/, '');
		transcript = '';
		outputUrl = '';
		projectVersions = [];
		saveCurrentProject({ source_audio_url: null, source_audio_name: file.name, transcript, versions: [] });
		void persistSourceFile(file);
	}

	async function toggleRecord() {
		if (recording) {
			recorder?.stop();
			return;
		}
		try {
			const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			recordingStream = stream;
			chunks = [];
			recorder = new MediaRecorder(stream, { mimeType: MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : undefined });
			recorder.ondataavailable = (event) => {
				if (event.data.size) chunks.push(event.data);
			};
			recorder.onstop = () => {
				clearRecordingTimer();
				stream.getTracks().forEach((track) => track.stop());
				recordingStream = null;
				file = new File([new Blob(chunks, { type: 'audio/webm' })], `voice-change-${Date.now()}.webm`, { type: 'audio/webm' });
				if (previewUrl) URL.revokeObjectURL(previewUrl);
				previewUrl = URL.createObjectURL(file);
				recording = false;
				void setupWaveform(previewUrl);
				if (!title.trim()) title = '녹음 보이스 체인저';
				transcript = '';
				outputUrl = '';
				projectVersions = [];
				saveCurrentProject({ source_audio_url: null, source_audio_name: file.name, transcript, versions: [] });
				void persistSourceFile(file);
			};
			recorder.start(250);
			recordingSeconds = 0;
			recordingTimer = setInterval(() => {
				recordingSeconds += 1;
			}, 1000);
			recording = true;
		} catch (error) {
			clearRecordingTimer();
			recordingStream?.getTracks().forEach((track) => track.stop());
			recordingStream = null;
			onNotice('error', error instanceof Error ? error.message : String(error));
		}
	}

	function watchProgress(progressId: string) {
		let elapsed = 0;
		progress = { percent: 1, message: '변환 작업을 준비하고 있습니다.', elapsed, active: true };
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
				finish(payload.message ?? '보이스 체인저 변환이 완료되었습니다.');
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
			onNotice('error', '대본을 읽을 원본 음성이 필요합니다.');
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
			onNotice('success', `${sttProvider === 'apple-speech' ? 'Apple Speech' : 'Whisper'}로 원본 음성 대본을 읽었습니다.`);
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			transcribing = false;
		}
	}

	async function convert() {
		if (!file) {
			onNotice('error', '변환할 원본 음성이 필요합니다.');
			return;
		}
		if (!voiceId) {
			onNotice('error', '대상 목소리를 선택해 주세요.');
			return;
		}
		if (selectionTooShort) {
			onNotice('error', '선택 구간이 너무 짧습니다. 말소리가 있는 구간을 선택해 주세요.');
			return;
		}
		if (selectedModel?.status !== 'available') {
			onNotice('error', selectedModel?.message || 'Seed-VC 모델을 사용할 수 없습니다.');
			return;
		}
		const progressId = crypto.randomUUID();
		const stopProgress = watchProgress(progressId);
		busy = true;
		try {
			const form = new FormData();
			form.append('audio', file);
			form.append('voice_id', voiceId);
			form.append('model_id', modelId);
			form.append('progress_id', progressId);
			form.append('trim_start', String(trimStart));
			form.append('trim_end', String(trimEnd));
			form.append('conversion_mode', conversionMode);
			form.append('diffusion_steps', String(diffusionSteps));
			form.append('length_adjust', String(lengthAdjust));
			form.append('inference_cfg_rate', String(inferenceCfgRate));
			form.append('f0_condition', String(f0Condition || conversionMode === 'singing'));
			form.append('auto_f0_adjust', String(autoF0Adjust));
			form.append('semi_tone_shift', String(semiToneShift));
			form.append('fp16', String(fp16));
			const response = await apiFetch('/api/voice-conversion', { method: 'POST', body: form });
			const payload = await response.json();
			outputUrl = payload.audio_url;
			await loadHistory();
			const latest = history[0];
			if (latest) {
				projectVersions = [latest, ...projectVersions.filter((item) => item.id !== latest.id)];
			}
			transcript = payload.transcript || transcript;
			saveCurrentProject({ versions: projectVersions, transcript });
			onNotice('success', '보이스 체인저 변환을 완료했습니다.');
			stopProgress('보이스 체인저 변환이 완료되었습니다.');
		} catch (error) {
			stopProgress();
			progress = { percent: 0, message: '', elapsed: 0, active: false };
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			busy = false;
		}
	}

	async function launchRealtime() {
		realtimeLaunching = true;
		realtimeStatus = { state: 'launching', message: 'Seed-VC 실시간 GUI 실행을 요청했습니다. 잠시만 기다려 주세요.' };
		try {
			const form = new FormData();
			form.append('fp16', String(fp16));
			const response = await apiFetch('/api/voice-conversion/realtime/launch', { method: 'POST', body: form });
			const payload = await response.json();
			realtimeStatus = {
				state: 'running',
				message: payload.message || 'Seed-VC 실시간 GUI를 실행했습니다. 실행된 창을 확인하세요.',
				pid: payload.pid ?? null
			};
			onNotice('success', payload.message || 'Seed-VC 실시간 GUI를 실행했습니다.');
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			realtimeStatus = { state: 'error', message };
			onNotice('error', message);
		} finally {
			realtimeLaunching = false;
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
					<span class="hidden">보이스 체인저 제목</span>
					<input class="inline-title-input" value={title} oninput={(event) => { title = event.currentTarget.value; saveCurrentProject(); }} aria-label="보이스 체인저 제목" />
				</label>
				<p>{conversionMode === 'singing' ? 'Seed-VC 보컬/SVC 모드로 노래의 피치 흐름을 유지하면서 대상 목소리로 변환합니다.' : '원본 음성의 말 내용과 타이밍을 유지하면서 대상 목소리로 직접 변환합니다.'}</p>
			</div>
			<div class="button-row wrap">
				<button class="secondary-action" onclick={backToList}><ArrowLeft size={17} />목록</button>
				<button class="primary-action" disabled={busy || !canConvert} onclick={convert}>
					{#if busy}<Loader2 class="spin" size={18} />변환 중{:else}<Wand2 size={18} />변환 시작{/if}
				</button>
			</div>
		</div>
		<div class="upload-zone compact">
			<FileAudio size={40} />
			<h3>{file?.name ?? '이 문서의 원본 음성 등록'}</h3>
			<p>한 작업 문서에는 하나의 원본 녹음/파일을 둡니다. 이 원본을 여러 대상 목소리로 변환해 비교합니다.</p>
			<p class="field-helper">대본 읽기는 원본 음성을 텍스트로 표시하는 STT 작업이고, 변환 시작은 같은 원본을 대상 목소리로 바꾸는 보이스 체인저 작업입니다.</p>
			{#if savingSource}
				<p class="field-helper">원본 음성을 작업에 저장하는 중입니다.</p>
			{/if}
			{#if recording}
				<div class="recording-panel" aria-live="polite">
					<span class="recording-dot"></span>
					<strong>녹음 중 {formatTime(recordingSeconds)}</strong>
					<small>말을 마친 뒤 녹음 종료를 누르세요.</small>
				</div>
			{/if}
			<div class="button-row center">
				<label class="secondary-action">{file ? '원본 파일 교체' : '원본 파일 선택'}<input class="hidden" type="file" accept="audio/*" onchange={onFileChange} /></label>
				<button class="secondary-action" class:recording onclick={toggleRecord}><Mic size={17} />{recording ? '녹음 종료' : '녹음'}</button>
				<button class="secondary-action" disabled={!file || transcribing || savingSource} onclick={transcribeSource}>
					{#if transcribing}<Loader2 class="spin" size={17} />대본 읽는 중{:else}<FileAudio size={17} />{sttProvider === 'apple-speech' ? 'Apple Speech STT' : 'Whisper STT'} 대본 읽기{/if}
				</button>
			</div>
		</div>
		{#if previewUrl}
			<div class="result-preview">
				<h3>원본 음성</h3>
				<audio controls src={previewUrl}></audio>
			</div>
		{/if}
		{#if transcript}
			<div class="result-preview">
				<h3>원본 음성 대본</h3>
				<textarea class="studio-input compact-textarea" value={transcript} oninput={(event) => { transcript = event.currentTarget.value; saveCurrentProject({ transcript }); }}></textarea>
			</div>
		{/if}
		<div class="wave-editor">
			<div bind:this={waveformEl}></div>
			{#if previewUrl && timelineTicks.length}
				<div class="wave-timeline" aria-label="파형 시간 눈금">
					{#each timelineTicks as tick}
						<span>{formatTime(tick)}</span>
					{/each}
				</div>
			{/if}
			{#if !previewUrl}
				<div class="wave-placeholder">원본 음성을 추가하면 파형과 선택 구간이 표시됩니다.</div>
			{/if}
		</div>
		{#if previewUrl}
			<div class="transport-row">
				<button class="icon-button" onclick={() => activeRegion?.play()} aria-label="선택 구간 재생"><Play size={18} /></button>
				<button class="icon-button" onclick={() => wave?.pause()} aria-label="일시 정지"><Pause size={18} /></button>
				<button class="icon-button" onclick={() => wave?.seekTo(0)} aria-label="처음으로"><RotateCcw size={18} /></button>
				<button class="secondary-action compact" onclick={() => {
					trimStart = 0;
					trimEnd = duration;
					activeRegion?.setOptions?.({ start: 0, end: duration });
				}}>전체 선택</button>
				<span>선택 {formatTime(trimStart)} - {formatTime(trimEnd)} · {selectedDuration.toFixed(1)}초</span>
			</div>
			{#if selectionTooShort}
				<p class="warning-note">선택 구간이 너무 짧습니다. 말소리가 또렷한 3~8초 구간을 선택해 주세요.</p>
			{:else if conversionMode === 'singing'}
				<p class="field-helper">보컬/SVC 모드는 노래 구간 전체를 사용할 수 있습니다. 피치가 흔들리면 반음 이동과 자동 F0 보정을 조정해 다시 비교하세요.</p>
			{:else}
				<p class="field-helper">긴 구간도 변환할 수 있습니다. 다만 1분 이상은 처리 시간이 오래 걸릴 수 있어 문장 단위 선택을 권장합니다.</p>
			{/if}
		{/if}
		<ProgressPanel {progress} fallbackMessage="변환 중입니다." />
		<VoiceChangerResultsPanel {projectVersions} {voices} />
	</section>
	<VoiceChangerSettingsPanel
		{voices}
		{vcModels}
		{selectedModel}
		{sttProvider}
		{sttLanguage}
		{modelId}
		{voiceId}
		{conversionMode}
		{diffusionSteps}
		{lengthAdjust}
		{inferenceCfgRate}
		{f0Condition}
		{autoF0Adjust}
		{semiToneShift}
		{fp16}
		{realtimeLaunching}
		{realtimeStatus}
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
		onConversionModeChange={(value) => {
			conversionMode = value;
			if (value === 'singing') {
				f0Condition = true;
				autoF0Adjust = true;
				diffusionSteps = Math.max(diffusionSteps, 40);
			}
			saveCurrentProject();
		}}
		onDiffusionStepsChange={(value) => {
			diffusionSteps = value;
			saveCurrentProject();
		}}
		onLengthAdjustChange={(value) => {
			lengthAdjust = value;
			saveCurrentProject();
		}}
		onInferenceCfgRateChange={(value) => {
			inferenceCfgRate = value;
			saveCurrentProject();
		}}
		onF0ConditionChange={(value) => {
			f0Condition = value;
			saveCurrentProject();
		}}
		onAutoF0AdjustChange={(value) => {
			autoF0Adjust = value;
			saveCurrentProject();
		}}
		onSemiToneShiftChange={(value) => {
			semiToneShift = value;
			saveCurrentProject();
		}}
		onFp16Change={(value) => {
			fp16 = value;
			saveCurrentProject();
		}}
		onLaunchRealtime={launchRealtime}
	/>
</div>
{/if}
