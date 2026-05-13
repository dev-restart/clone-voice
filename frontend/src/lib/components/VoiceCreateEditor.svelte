<script lang="ts">
	import { onDestroy, tick } from 'svelte';
	import { FFmpeg } from '@ffmpeg/ffmpeg';
	import { ArrowLeft, Save } from 'lucide-svelte';
	import WaveSurfer from 'wavesurfer.js';
	import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js';
	import VoiceCreateScriptPanel from '$lib/components/voice/VoiceCreateScriptPanel.svelte';
	import VoiceSampleInputPanel from '$lib/components/voice/VoiceSampleInputPanel.svelte';
	import VoiceWaveformPanel from '$lib/components/voice/VoiceWaveformPanel.svelte';
	import { apiFetch, audioUrl } from '$lib/studio/api';
	import type { VoiceProfile } from '$lib/studio/types';

	let {
		onSaved,
		onCancel,
		onNotice
	}: {
		onSaved: (voice: VoiceProfile) => void | Promise<void>;
		onCancel: () => void;
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
	} = $props();

	const sampleText = '안녕하세요. 이 목소리는 음성 합성을 위한 샘플입니다. 또렷하고 자연스럽게 말하며 억양과 발음이 잘 드러나도록 녹음합니다.';
	let name = $state('');
	let transcript = $state('');
	let sttProvider = $state<'whisper' | 'apple-speech'>('whisper');
	let sttLanguage = $state('ko');
	let file = $state<File | null>(null);
	let youtubeUrl = $state('');
	let youtubeTitle = $state('');
	let isolateYouTubeVoice = $state(true);
	let importingYouTube = $state(false);
	let previewUrl = $state('');
	let duration = $state(0);
	let trimStart = $state(0);
	let trimEnd = $state(10);
	let timelineTicks = $derived.by(() => {
		if (!duration) return [];
		const segments = Math.min(8, Math.max(2, Math.ceil(duration)));
		return Array.from({ length: segments + 1 }, (_, index) => (duration / segments) * index);
	});
	let waveformEl = $state<HTMLDivElement | null>(null);
	let wave: WaveSurfer | null = null;
	let regions: ReturnType<typeof RegionsPlugin.create> | null = null;
	let activeRegion: any = null;
	let busy = $state(false);
	let recording = $state(false);
	let recordingSeconds = $state(0);
	let recorder: MediaRecorder | null = null;
	let recordingStream: MediaStream | null = null;
	let recordingTimer: ReturnType<typeof setInterval> | null = null;
	let chunks: Blob[] = [];
	let ffmpegReady = $state(false);
	let ffmpegTried = false;

	onDestroy(() => {
		wave?.destroy();
		if (previewUrl) URL.revokeObjectURL(previewUrl);
		clearRecordingTimer();
		recordingStream?.getTracks().forEach((track) => track.stop());
	});

	function clearRecordingTimer() {
		if (!recordingTimer) return;
		clearInterval(recordingTimer);
		recordingTimer = null;
	}

	async function ensureFfmpeg() {
		if (ffmpegReady || ffmpegTried) return ffmpegReady;
		ffmpegTried = true;
		try {
			const ffmpeg = new FFmpeg();
			await ffmpeg.load();
			ffmpegReady = true;
			return true;
		} catch {
			ffmpegReady = false;
			return false;
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
			trimEnd = Math.min(10, Math.max(3, decodedDuration));
			activeRegion = regions?.addRegion({
				start: trimStart,
				end: trimEnd,
				color: 'rgba(17, 24, 39, 0.18)',
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
		await ensureFfmpeg();
	}

	function setWaveformElement(element: HTMLDivElement) {
		waveformEl = element;
	}

	function onFileChange(event: Event) {
		const input = event.target as HTMLInputElement;
		file = input.files?.[0] ?? null;
		if (!file) return;
		if (previewUrl) URL.revokeObjectURL(previewUrl);
		previewUrl = URL.createObjectURL(file);
		if (!name.trim()) name = file.name.replace(/\.[^.]+$/, '');
		youtubeTitle = '';
		void setupWaveform(previewUrl);
	}

	async function loadImportedAudio(payload: { audio_url: string; filename: string; title?: string; voice_isolated?: boolean }) {
		const response = await fetch(audioUrl(payload.audio_url));
		if (!response.ok) throw new Error('가져온 유튜브 오디오 파일을 열 수 없습니다.');
		const blob = await response.blob();
		file = new File([blob], payload.filename || 'youtube-audio.wav', { type: blob.type || 'audio/wav' });
		if (previewUrl) URL.revokeObjectURL(previewUrl);
		previewUrl = URL.createObjectURL(file);
		youtubeTitle = payload.voice_isolated ? `${payload.title || 'YouTube audio'} · 말소리 정리 적용` : payload.title || '';
		if (!name.trim()) name = payload.title || file.name.replace(/\.[^.]+$/, '');
		void setupWaveform(previewUrl);
	}

	async function importYouTubeAudio() {
		if (!youtubeUrl.trim()) {
			onNotice('error', '유튜브 주소를 입력해 주세요.');
			return;
		}
		importingYouTube = true;
		try {
			const response = await apiFetch('/api/audio/youtube-import', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ url: youtubeUrl.trim(), isolate_voice: isolateYouTubeVoice })
			});
			const payload = await response.json();
			await loadImportedAudio(payload);
			onNotice('success', payload.voice_isolated ? '유튜브 음성을 말소리 중심으로 정리했습니다. 파형에서 사용할 구간을 선택해 주세요.' : '유튜브 음성을 가져왔습니다. 파형에서 사용할 구간을 선택해 주세요.');
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			importingYouTube = false;
		}
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
				const blob = new Blob(chunks, { type: 'audio/webm' });
				file = new File([blob], `voice-${Date.now()}.webm`, { type: 'audio/webm' });
				if (previewUrl) URL.revokeObjectURL(previewUrl);
				previewUrl = URL.createObjectURL(file);
				recording = false;
				void setupWaveform(previewUrl);
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

	async function prepareAudioForUpload() {
		if (!file) return null;
		try {
			const ffmpeg = new FFmpeg();
			await ffmpeg.load();
			const inputName = `input${file.name.slice(file.name.lastIndexOf('.')) || '.webm'}`;
			await ffmpeg.writeFile(inputName, new Uint8Array(await file.arrayBuffer()));
			await ffmpeg.exec([
				'-i',
				inputName,
				'-ss',
				String(Math.max(0, trimStart)),
				'-to',
				String(Math.max(trimStart + 0.1, trimEnd)),
				'-ac',
				'1',
				'-ar',
				'24000',
				'-sample_fmt',
				's16',
				'voice.wav'
			]);
			const data = await ffmpeg.readFile('voice.wav');
			const bytes = typeof data === 'string' ? new TextEncoder().encode(data) : data;
			const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
			return new File([buffer], 'voice.wav', { type: 'audio/wav' });
		} catch {
			return null;
		}
	}

	async function saveVoice() {
		if (!file) {
			onNotice('error', '등록할 음성 파일이나 녹음이 필요합니다.');
			return;
		}
		busy = true;
		try {
			const processed = await prepareAudioForUpload();
			const form = new FormData();
			form.append('name', name || '새 목소리');
			form.append('transcript', transcript);
			if (processed) {
				form.append('trim_start', '0');
				form.append('trim_end', String(Math.max(0.1, trimEnd - trimStart)));
				form.append('audio', processed);
			} else {
				form.append('trim_start', String(trimStart));
				form.append('trim_end', String(trimEnd));
				form.append('audio', file);
			}
			const response = await apiFetch('/api/voices', { method: 'POST', body: form });
			const voice = await response.json();
			await onSaved(voice);
			onNotice('success', '선택 구간을 새 목소리로 저장했습니다.');
			name = '';
			transcript = '';
			file = null;
			previewUrl = '';
			wave?.destroy();
			wave = null;
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			busy = false;
		}
	}

	async function transcribeSelection() {
		if (!file) return;
		busy = true;
		try {
			const form = new FormData();
			form.append('audio', file);
			form.append('provider', sttProvider);
			if (sttLanguage) form.append('language', sttLanguage);
			form.append('trim_start', String(trimStart));
			form.append('trim_end', String(trimEnd));
			const response = await apiFetch('/api/stt', { method: 'POST', body: form });
			const payload = await response.json();
			transcript = payload.text || transcript;
			onNotice('success', `${sttProvider === 'apple-speech' ? 'Apple Speech' : 'Whisper'}로 선택 구간 대본을 가져왔습니다.`);
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			busy = false;
		}
	}
</script>

<section class="surface">
	<div class="voice-create-layout">
		<div class="section-heading">
			<div>
				<h2>목소리 만들기</h2>
				<p>대본을 확인한 뒤 녹음, 파일 업로드, 유튜브 음성 가져오기 중 하나로 샘플을 준비하세요.</p>
			</div>
			<button class="secondary-action" onclick={onCancel}><ArrowLeft size={17} />목록</button>
		</div>

		<div class="voice-form-flow">
			<VoiceCreateScriptPanel
				{name}
				{transcript}
				{sampleText}
				{sttProvider}
				{sttLanguage}
				{busy}
				hasFile={Boolean(file)}
				onNameChange={(value) => (name = value)}
				onTranscriptChange={(value) => (transcript = value)}
				onSttProviderChange={(value) => (sttProvider = value)}
				onSttLanguageChange={(value) => (sttLanguage = value)}
				onTranscribeSelection={transcribeSelection}
			/>

			<VoiceSampleInputPanel
				{recording}
				{recordingSeconds}
				{youtubeUrl}
				{youtubeTitle}
				{isolateYouTubeVoice}
				{busy}
				{importingYouTube}
				onFileChange={onFileChange}
				onToggleRecord={toggleRecord}
				onYoutubeUrlChange={(value) => (youtubeUrl = value)}
				onIsolateYouTubeVoiceChange={(value) => (isolateYouTubeVoice = value)}
				onImportYouTube={importYouTubeAudio}
			/>

			<VoiceWaveformPanel
				{previewUrl}
				{timelineTicks}
				{trimStart}
				{trimEnd}
				{ffmpegReady}
				onWaveformElement={setWaveformElement}
				onPlaySelection={() => activeRegion?.play()}
				onPause={() => wave?.pause()}
				onReset={() => wave?.seekTo(0)}
			/>

			<div class="form-actions">
				<button class="primary-action full" disabled={busy || !file} onclick={saveVoice}>
					<Save size={17} />
					{busy ? '저장 중...' : '목소리 저장'}
				</button>
			</div>
		</div>
	</div>
</section>
