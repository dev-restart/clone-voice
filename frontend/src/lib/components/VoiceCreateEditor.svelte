<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { onDestroy, onMount, tick } from 'svelte';
	import { ArrowLeft, Save } from '@lucide/svelte';
	import WaveSurfer from 'wavesurfer.js';
	import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js';
	import VoiceCreateScriptPanel from '$lib/components/voice/VoiceCreateScriptPanel.svelte';
	import VoiceSampleInputPanel, { type MediaInfo } from '$lib/components/voice/VoiceSampleInputPanel.svelte';
	import VoiceWaveformPanel from '$lib/components/voice/VoiceWaveformPanel.svelte';
	import VoiceSampleAnalysisPanel from '$lib/components/voice/VoiceSampleAnalysisPanel.svelte';
	import { apiFetch, audioUrl } from '$lib/studio/api';
	import { parseClockTime } from '$lib/studio/voice-sample';
	import { clampSampleRange, groupSampleTranscript, sampleRangeKey, sampleTranscriptWindow,
		type SampleAnalysis, type SampleCandidate, type TimedTranscript } from '$lib/studio/voice-sample';
	import type { VoiceProfile } from '$lib/studio/types';

	let { defaultSttProvider = 'apple-speech', onSaved, onCancel, onNotice }: {
		defaultSttProvider?: 'apple-speech' | 'whisper';
		onSaved: (voice: VoiceProfile) => void | Promise<void>;
		onCancel: () => void;
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
	} = $props();

	const sampleText = $derived(t('voice.sampleText'));
	let name = $state('');
	let transcript = $state('');
	let transcriptBinding = $state('');
	let transcriptRevision = 0;
	let sttProvider = $state<'whisper' | 'apple-speech'>('apple-speech');
	onMount(() => { sttProvider = defaultSttProvider; });
	let sttLanguage = $state('ko');
	let file = $state<File | null>(null);
	let sourceRevision = $state(0);
	let uploadedUrl = $state('');
	let uploadPending: { revision: number; promise: Promise<string> } | null = null;
	let mediaUrl = $state('');
	let mediaTitle = $state('');
	let mediaInfo = $state<MediaInfo | null>(null);
	let inspectingMedia = $state(false);
	let clipStart = $state('');
	let clipEnd = $state('');
	let isolateMediaVoice = $state(true);
	let importingMedia = $state(false);
	let previewUrl = $state('');
	let duration = $state(0);
	let trimStart = $state(0);
	let trimEnd = $state(0);
	let currentTime = $state(0);
	let overviewPeaks = $state<number[]>([]);
	let viewStart = $state(0);
	let viewEnd = $state(0);
	let visibleSeconds = 30;
	let waveformEl: HTMLDivElement | null = null;
	let wave: WaveSurfer | null = null;
	let activeRegion: ReturnType<ReturnType<typeof RegionsPlugin.create>['addRegion']> | null = null;
	let busy = $state(false);
	let transcribing = $state(false);
	let analysis = $state<SampleAnalysis | null>(null);
	let analyzing = $state(false);
	let analysisError = $state('');
	let windowBusy = $state(false);
	let windowError = $state('');
	let transcriptRows = $state<TimedTranscript[]>([]);
	let transcriptWindow = $state<{ start: number; end: number } | null>(null);
	let windowProviderLabel = $state('');
	let recording = $state(false);
	let recordingPending = $state(false);
	let recordingSeconds = $state(0);
	let recorder: MediaRecorder | null = null;
	let recordingStream: MediaStream | null = null;
	let recordingTimer: ReturnType<typeof setInterval> | null = null;
	let disposed = false;
	let recordRequest = 0;
	let analysisRequest = 0;
	let windowRequest = 0;
	let selectionRequest = 0;
	const controllers = new Set<AbortController>();

	const rangeKey = $derived(sampleRangeKey(sourceRevision, trimStart, trimEnd));
	const transcriptStale = $derived(Boolean(transcript.trim()) && duration > 0 && transcriptBinding !== rangeKey);
	const sourceBusy = $derived(busy || importingMedia || recordingPending);
	const controlsDisabled = $derived(sourceBusy || recording || !duration);
	const sttLabel = $derived(sttProvider === 'apple-speech' ? 'Apple Speech' : 'Whisper');
	const timelineTicks = $derived.by(() => {
		if (!duration) return [];
		const width = viewEnd - viewStart;
		const count = Math.min(8, Math.max(2, Math.ceil(width)));
		return Array.from({ length: count + 1 }, (_, index) => viewStart + width * index / count);
	});

	function abortSourceRequests() {
		controllers.forEach((controller) => controller.abort());
		controllers.clear();
		analysisRequest++;
		windowRequest++;
		selectionRequest++;
		uploadPending = null;
		analyzing = false;
		windowBusy = false;
		transcribing = false;
	}

	onDestroy(() => {
		disposed = true;
		recordRequest++;
		abortSourceRequests();
		wave?.destroy();
		if (previewUrl) URL.revokeObjectURL(previewUrl);
		clearRecordingTimer();
		if (recorder?.state === 'recording') recorder.stop();
		recordingStream?.getTracks().forEach((track) => track.stop());
	});

	function clearRecordingTimer() {
		if (recordingTimer) clearInterval(recordingTimer);
		recordingTimer = null;
	}

	function newController() {
		const controller = new AbortController();
		controllers.add(controller);
		return controller;
	}

	function changeRange(start: number, end: number, focus = true) {
		if (controlsDisabled) return;
		const range = clampSampleRange(start, end, duration);
		if (!range) return;
		wave?.pause();
		trimStart = range.start;
		trimEnd = range.end;
		activeRegion?.setOptions(range);
		if (focus) focusSelection();
	}

	function zoomTo(seconds: number, center = (viewStart + viewEnd) / 2) {
		if (!wave || !duration) return;
		visibleSeconds = Math.min(duration, Math.max(Math.min(5, duration), seconds));
		const left = Math.max(0, Math.min(duration - visibleSeconds, center - visibleSeconds / 2));
		wave.zoom(Math.max(1, wave.getWidth()) / visibleSeconds);
		wave.setScrollTime(left);
		viewStart = left;
		viewEnd = Math.min(duration, left + visibleSeconds);
	}

	function focusSelection() {
		zoomTo(Math.max(10, Math.min(30, (trimEnd - trimStart) * 2)), (trimStart + trimEnd) / 2);
	}

	function seekTime(time: number) {
		if (controlsDisabled || !Number.isFinite(time)) return;
		wave?.pause();
		const bounded = Math.max(0, Math.min(duration, time));
		wave?.setTime(bounded);
		zoomTo(visibleSeconds, bounded);
	}

	async function previewRange(start: number, end: number) {
		if (controlsDisabled || !wave) return;
		const range = clampSampleRange(start, end, duration);
		if (!range) return;
		const currentWave = wave;
		try {
			zoomTo(visibleSeconds, (range.start + range.end) / 2);
			await currentWave.play(range.start, range.end);
		} catch (error) {
			if (!disposed && wave === currentWave) onNotice('error', t('voice.ed.playFail'));
		}
	}

	async function setupWaveform(url: string, revision: number) {
		await tick();
		if (!waveformEl || disposed || revision !== sourceRevision) return;
		const theme = getComputedStyle(document.documentElement);
		const regions = RegionsPlugin.create();
		const instance = WaveSurfer.create({
			container: waveformEl, height: 132,
			waveColor: theme.getPropertyValue('--muted-strong').trim() || '#e1d4c0',
			progressColor: theme.getPropertyValue('--accent').trim() || '#b96d32',
			cursorColor: theme.getPropertyValue('--foreground').trim() || '#1e1a14',
			barWidth: 2, barGap: 2, barRadius: 3, plugins: [regions]
		});
		wave = instance;
		const current = () => !disposed && sourceRevision === revision && wave === instance;
		instance.on('decode', (decodedDuration) => {
			if (!current()) return;
			duration = decodedDuration;
			trimStart = 0;
			trimEnd = Math.min(10, decodedDuration);
			viewStart = 0;
			viewEnd = decodedDuration;
			overviewPeaks = (instance.exportPeaks({ channels: 1, maxLength: 400 })[0] || []).map(Math.abs);
			activeRegion = regions.addRegion({
				start: trimStart, end: trimEnd, color: 'rgba(22, 101, 52, 0.2)', drag: true, resize: true,
				minLength: Math.min(.05, decodedDuration)
			});
		});
		instance.on('ready', () => {
			if (current()) zoomTo(Math.min(30, duration), 0);
		});
		instance.on('timeupdate', (time) => { if (current()) currentTime = time; });
		instance.on('scroll', (start, end) => {
			if (!current()) return;
			viewStart = Math.max(0, start);
			viewEnd = Math.min(duration, end);
		});
		regions.on('region-updated', (region) => {
			if (!current()) return;
			if (controlsDisabled) {
				region.setOptions({ start: trimStart, end: trimEnd });
				return;
			}
			const range = clampSampleRange(region.start, region.end, duration);
			if (!range) return;
			instance.pause();
			trimStart = range.start;
			trimEnd = range.end;
		});
		regions.on('region-clicked', (region, event) => {
			event.stopPropagation();
			if (current()) void previewRange(region.start, region.end);
		});
		try { await instance.load(url); }
		catch (error) {
			if (current()) {
				duration = 0;
				onNotice('error', t('voice.ed.waveFail'));
			}
		}
	}

	function useAudio(nextFile: File, serverUrl = '', title = '') {
		sourceRevision++;
		abortSourceRequests();
		wave?.destroy();
		wave = null;
		activeRegion = null;
		if (previewUrl) URL.revokeObjectURL(previewUrl);
		file = nextFile;
		uploadedUrl = serverUrl;
		mediaTitle = title;
		duration = 0;
		trimStart = 0;
		trimEnd = 0;
		currentTime = 0;
		viewStart = 0;
		viewEnd = 0;
		overviewPeaks = [];
		analysis = null;
		analysisError = '';
		windowError = '';
		transcriptRows = [];
		transcriptWindow = null;
		previewUrl = URL.createObjectURL(nextFile);
		if (!name.trim()) name = nextFile.name.replace(/\.[^.]+$/, '');
		void setupWaveform(previewUrl, sourceRevision);
	}

	function onFileChange(event: Event) {
		if (sourceBusy || recording) return;
		const input = event.target as HTMLInputElement;
		const selected = input.files?.[0];
		if (selected) useAudio(selected);
		input.value = '';
	}

	async function ensureUploadedSource(revision: number): Promise<string> {
		if (disposed || revision !== sourceRevision || !file) throw new DOMException('Source changed', 'AbortError');
		if (uploadedUrl) return uploadedUrl;
		if (uploadPending?.revision === revision) return uploadPending.promise;
		const sourceFile = file;
		const controller = newController();
		const promise = (async () => {
			try {
				const form = new FormData();
				form.append('audio', sourceFile);
				const response = await apiFetch('/api/audio/uploads', { method: 'POST', body: form, signal: controller.signal });
				const payload = await response.json();
				if (disposed || revision !== sourceRevision || controller.signal.aborted) throw new DOMException('Source changed', 'AbortError');
				if (typeof payload.audio_url !== 'string') throw new Error(t('voice.ed.uploadFail'));
				uploadedUrl = payload.audio_url;
				return uploadedUrl;
			} finally {
				controllers.delete(controller);
				if (uploadPending?.revision === revision) uploadPending = null;
			}
		})();
		uploadPending = { revision, promise };
		return promise;
	}

	async function inspectMedia() {
		if (sourceBusy || recording || inspectingMedia || !mediaUrl.trim()) return;
		inspectingMedia = true;
		mediaInfo = null;
		const controller = newController();
		try {
			const response = await apiFetch('/api/audio/media-info', {
				method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
				body: JSON.stringify({ url: mediaUrl.trim() })
			});
			const payload = await response.json();
			if (!disposed && !controller.signal.aborted) mediaInfo = payload;
		} catch (error) {
			if (!disposed && !controller.signal.aborted) onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			controllers.delete(controller);
			if (!disposed) inspectingMedia = false;
		}
	}

	async function importMediaAudio() {
		if (sourceBusy || recording) return;
		if (!mediaUrl.trim()) { onNotice('error', t('voice.ed.needUrl')); return; }
		const start = parseClockTime(clipStart);
		const end = parseClockTime(clipEnd);
		if (Number.isNaN(start) || Number.isNaN(end)) { onNotice('error', t('voice.link.badRange')); return; }
		importingMedia = true;
		const controller = newController();
		try {
			const response = await apiFetch('/api/audio/media-import', {
				method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
				body: JSON.stringify({
					url: mediaUrl.trim(), isolate_voice: isolateMediaVoice,
					...(start !== null ? { start_seconds: start } : {}), ...(end !== null ? { end_seconds: end } : {})
				})
			});
			const payload = await response.json();
			const audio = await fetch(audioUrl(payload.audio_url), { signal: controller.signal });
			if (!audio.ok) throw new Error(t('voice.ed.mediaOpenFail'));
			const blob = await audio.blob();
			if (disposed || controller.signal.aborted) return;
			const sourceFile = new File([blob], payload.filename || 'media-audio.wav', { type: blob.type || 'audio/wav' });
			const title = payload.title || (payload.platform === 'instagram' ? 'Instagram audio' : 'YouTube audio');
			if (!name.trim()) name = title;
			useAudio(sourceFile, payload.audio_url, title + (payload.voice_isolated ? t('voice.ed.isolated') : ''));
			onNotice('success', t('voice.ed.imported'));
		} catch (error) {
			if (!disposed && !controller.signal.aborted) onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			controllers.delete(controller);
			if (!disposed) importingMedia = false;
		}
	}

	async function toggleRecord() {
		if (recording) { recorder?.stop(); return; }
		if (sourceBusy) return;
		const request = ++recordRequest;
		recordingPending = true;
		try {
			const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			if (disposed || request !== recordRequest) { stream.getTracks().forEach((track) => track.stop()); return; }
			recordingStream = stream;
			const mimeType = ['audio/webm', 'audio/mp4'].find((type) => MediaRecorder.isTypeSupported(type));
			const nextRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
			recorder = nextRecorder;
			const chunks: Blob[] = [];
			nextRecorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
			nextRecorder.onstop = () => {
				clearRecordingTimer();
				stream.getTracks().forEach((track) => track.stop());
				recordingStream = null;
				recording = false;
				if (disposed || request !== recordRequest || !chunks.length) return;
				const type = nextRecorder.mimeType || chunks[0].type || 'audio/webm';
				const extension = type.includes('mp4') ? 'm4a' : 'webm';
				useAudio(new File(chunks, 'voice-' + Date.now() + '.' + extension, { type }));
			};
			nextRecorder.onerror = () => {
				clearRecordingTimer();
				stream.getTracks().forEach((track) => track.stop());
				recording = false;
				if (!disposed) onNotice('error', t('voice.ed.recordFail'));
			};
			nextRecorder.start(250);
			recordingSeconds = 0;
			recordingTimer = setInterval(() => { recordingSeconds++; }, 1000);
			recording = true;
		} catch (error) {
			clearRecordingTimer();
			recordingStream?.getTracks().forEach((track) => track.stop());
			recordingStream = null;
			if (!disposed) onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			if (!disposed) recordingPending = false;
		}
	}

	async function analyzeSource() {
		if (controlsDisabled || analyzing) return;
		const revision = sourceRevision;
		const request = ++analysisRequest;
		const controller = newController();
		analyzing = true;
		analysisError = '';
		try {
			const source = await ensureUploadedSource(revision);
			const response = await apiFetch('/api/audio/sample-analysis', {
				method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
				body: JSON.stringify({ audio_url: source })
			});
			const result: SampleAnalysis = await response.json();
			if (!disposed && revision === sourceRevision && request === analysisRequest && !controller.signal.aborted) analysis = result;
		} catch (error) {
			if (!disposed && revision === sourceRevision && !controller.signal.aborted) analysisError = error instanceof Error ? error.message : String(error);
		} finally {
			controllers.delete(controller);
			if (!disposed && request === analysisRequest) analyzing = false;
		}
	}

	function editTranscript(value: string) {
		transcriptRevision++;
		transcript = value;
		transcriptBinding = rangeKey;
	}

	function chooseCandidate(candidate: SampleCandidate) {
		changeRange(candidate.start, candidate.end);
	}

	function chooseTranscript(row: TimedTranscript) {
		if (controlsDisabled) return;
		changeRange(row.start, row.end);
		editTranscript(row.text);
	}

	async function transcribeWindow() {
		if (controlsDisabled || windowBusy) return;
		const revision = sourceRevision;
		const request = ++windowRequest;
		const requestedKey = rangeKey;
		const provider = sttProvider;
		const language = sttLanguage;
		const window = sampleTranscriptWindow(trimStart, trimEnd, duration);
		const controller = newController();
		windowBusy = true;
		windowError = '';
		try {
			const source = await ensureUploadedSource(revision);
			const response = await apiFetch('/api/audio/sample-transcript', {
				method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
				body: JSON.stringify({ audio_url: source, provider, language, ...window })
			});
			const result = await response.json();
			if (disposed || revision !== sourceRevision || request !== windowRequest || controller.signal.aborted) return;
			if (rangeKey !== requestedKey || provider !== sttProvider || language !== sttLanguage) {
				windowError = t('voice.ed.windowChanged');
				return;
			}
			transcriptRows = groupSampleTranscript(result.segments || []);
			transcriptWindow = window;
			windowProviderLabel = provider === 'apple-speech' ? 'Apple Speech' : 'Whisper';
		} catch (error) {
			if (!disposed && revision === sourceRevision && !controller.signal.aborted) windowError = error instanceof Error ? error.message : String(error);
		} finally {
			controllers.delete(controller);
			if (!disposed && request === windowRequest) windowBusy = false;
		}
	}

	async function transcribeSelection() {
		if (!file || controlsDisabled || transcribing) return;
		const revision = sourceRevision;
		const request = ++selectionRequest;
		const requestedKey = rangeKey;
		const textRevision = transcriptRevision;
		const provider = sttProvider;
		const language = sttLanguage;
		const controller = newController();
		transcribing = true;
		try {
			const form = new FormData();
			form.append('audio', file);
			form.append('provider', provider);
			if (language) form.append('language', language);
			form.append('trim_start', String(trimStart));
			form.append('trim_end', String(trimEnd));
			const response = await apiFetch('/api/stt', { method: 'POST', body: form, signal: controller.signal });
			const payload = await response.json();
			if (disposed || revision !== sourceRevision || request !== selectionRequest || controller.signal.aborted) return;
			if (requestedKey !== rangeKey || textRevision !== transcriptRevision || provider !== sttProvider || language !== sttLanguage) {
				onNotice('info', t('voice.ed.selectionChanged'));
				return;
			}
			if (!payload.text?.trim()) { onNotice('info', t('voice.ed.noTranscript')); return; }
			editTranscript(payload.text);
			onNotice('success', t('voice.ed.transcribed', { engine: provider === 'apple-speech' ? 'Apple Speech' : 'Whisper' }));
		} catch (error) {
			if (!disposed && revision === sourceRevision && !controller.signal.aborted) onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			controllers.delete(controller);
			if (!disposed && request === selectionRequest) transcribing = false;
		}
	}

	async function saveVoice() {
		if (!file || controlsDisabled || transcribing || busy) return;
		if (transcriptStale) {
			onNotice('error', t('voice.ed.stale'));
			return;
		}
		busy = true;
		wave?.pause();
		try {
			const form = new FormData();
			form.append('name', name.trim() || t('voice.ed.defaultName'));
			form.append('transcript', transcript);
			form.append('trim_start', String(trimStart));
			form.append('trim_end', String(trimEnd));
			form.append('audio', file);
			const response = await apiFetch('/api/voices', { method: 'POST', body: form });
			const voice = await response.json();
			if (!disposed) {
				onNotice('success', t('voice.ed.saved'));
				await onSaved(voice);
			}
		} catch (error) {
			if (!disposed) onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			if (!disposed) busy = false;
		}
	}
</script>

<section class="surface">
	<div class="voice-create-layout">
		<div class="section-heading">
			<div>
				<h2>{t('nav.voice.register')}</h2>
			</div>
			<button class="secondary-action" disabled={busy} onclick={onCancel}><ArrowLeft size={17} />{t('voice.ed.list')}</button>
		</div>
		<div class="voice-form-flow">
			<VoiceSampleInputPanel
				{recording} {recordingSeconds} {mediaUrl} {mediaTitle} {isolateMediaVoice}
				sourceAudioUrl={uploadedUrl}
				busy={busy || recordingPending} {importingMedia}
				onFileChange={onFileChange} onToggleRecord={toggleRecord}
				{mediaInfo} {inspectingMedia} {clipStart} {clipEnd}
				onMediaUrlChange={(value) => { mediaUrl = value; mediaInfo = null; }}
				onInspectMedia={inspectMedia}
				onClipChange={(start, end) => { clipStart = start; clipEnd = end; }}
				onIsolateMediaVoiceChange={(value) => (isolateMediaVoice = value)}
				onImportMedia={importMediaAudio}
			/>
			<VoiceWaveformPanel
				{previewUrl} {timelineTicks} {trimStart} {trimEnd} {duration} {currentTime}
				{overviewPeaks} audioRegions={analysis?.regions || []} {viewStart} {viewEnd}
				disabled={controlsDisabled}
				onWaveformElement={(element) => (waveformEl = element)}
				onPlaySelection={() => void previewRange(trimStart, trimEnd)}
				onPause={() => wave?.pause()} onReset={() => seekTime(0)}
				onChangeRange={changeRange} onSeekTime={seekTime}
				onZoomIn={() => zoomTo(visibleSeconds / 2)}
				onZoomOut={() => zoomTo(visibleSeconds * 2)}
				onFocusSelection={focusSelection} onShowAll={() => zoomTo(duration, duration / 2)}
			/>
			{#if file}
				<VoiceSampleAnalysisPanel
					{analysis} {analyzing} {analysisError} {windowBusy} {windowError}
					{transcriptRows} {transcriptWindow} {sttLabel} transcriptProviderLabel={windowProviderLabel}
					disabled={controlsDisabled} {trimStart} {trimEnd}
					onAnalyze={analyzeSource} onChoose={chooseCandidate} onChooseRegion={changeRange}
					onPreview={(start, end) => void previewRange(start, end)}
					onTranscribeWindow={transcribeWindow} onChooseTranscript={chooseTranscript}
				/>
			{/if}
			<VoiceCreateScriptPanel
				{name} {transcript} {sampleText} {sttProvider} {sttLanguage}
				busy={sourceBusy || recording} {transcribing} {transcriptStale} hasFile={Boolean(file) && duration > 0}
				onNameChange={(value) => (name = value)} onTranscriptChange={editTranscript}
				onSttProviderChange={(value) => (sttProvider = value)}
				onSttLanguageChange={(value) => (sttLanguage = value)}
				onTranscribeSelection={transcribeSelection}
				onConfirmTranscript={() => editTranscript(transcript)}
			/>
			<div class="form-actions">
				<button class="primary-action full" disabled={controlsDisabled || transcribing || !file || transcriptStale} onclick={saveVoice}>
					<Save size={17} />{busy ? t('tts.editor.saving') : t('voice.ed.save')}
				</button>
			</div>
		</div>
	</div>
</section>

<style>
	.voice-create-layout { grid-template-columns: minmax(0, 1fr); min-width: 0; }
	.voice-form-flow { min-width: 0; grid-template-columns: minmax(0, 1fr); }
</style>
