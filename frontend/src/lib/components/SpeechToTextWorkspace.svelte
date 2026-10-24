<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { onMount, onDestroy } from 'svelte';
	import SpeechInputPanel from '$lib/components/stt/SpeechInputPanel.svelte';
	import SttSettingsPanel from '$lib/components/stt/SttSettingsPanel.svelte';
	import SttTranslationResults from '$lib/components/stt/SttTranslationResults.svelte';
	import { apiFetch } from '$lib/studio/api';

	let { defaultSttProvider = 'apple-speech', onNotice }: { defaultSttProvider?: 'apple-speech' | 'whisper'; onNotice: (type: 'success' | 'error' | 'info', text: string) => void } = $props();

	let file = $state<File | null>(null);
	let sttProvider = $state<'whisper' | 'apple-speech'>('apple-speech');
	onMount(() => { sttProvider = defaultSttProvider; });
	let language = $state('');
	let text = $state('');
	let translations = $state<Record<string, string>>({});
	let targets = $state<string[]>(['ko', 'en']);
	let busy = $state(false);
	let recording = $state(false);
	let recorder: MediaRecorder | null = null;
	let chunks: Blob[] = [];
	let stream: MediaStream | null = null;
	let disposed = false;
	onDestroy(() => { disposed = true; if (recorder?.state === 'recording') recorder.stop(); stream?.getTracks().forEach((track) => track.stop()); });

	function onFileChange(event: Event) {
		file = (event.target as HTMLInputElement).files?.[0] ?? null;
	}

	async function toggleRecord() {
		if (recording) {
			recorder?.stop();
			return;
		}
		try {
			stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			if (disposed) { stream.getTracks().forEach((track) => track.stop()); return; }
			chunks = [];
			recorder = new MediaRecorder(stream, { mimeType: MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : undefined });
			recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
			recorder.onstop = () => {
				stream?.getTracks().forEach((track) => track.stop());
				if (disposed) return;
				const mime = recorder?.mimeType || chunks[0]?.type || 'audio/webm';
				file = new File([new Blob(chunks, { type: mime })], `stt-${Date.now()}.${mime.includes('mp4') ? 'm4a' : 'webm'}`, { type: mime });
				recording = false;
			};
			recorder.start(250);
			recording = true;
		} catch (error) {
			stream?.getTracks().forEach((track) => track.stop());
			onNotice('error', error instanceof Error ? error.message : t('stt.recordFail'));
		}
	}

	async function transcribe() {
		if (!file) {
			onNotice('error', t('stt.needFile'));
			return;
		}
		busy = true;
		try {
			const form = new FormData();
			form.append('audio', file);
			form.append('provider', sttProvider);
			if (language) form.append('language', language);
			const response = await apiFetch('/api/stt', { method: 'POST', body: form });
			const payload = await response.json();
			text = payload.text;
			onNotice('success', t('stt.done'));
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			busy = false;
		}
	}

	async function translateText() {
		if (!text.trim()) return;
		busy = true;
		try {
			const response = await apiFetch('/api/translate', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ text, languages: targets })
			});
			const payload = await response.json();
			translations = payload.translations ?? {};
			onNotice('success', t('stt.translated'));
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			busy = false;
		}
	}

	function toggleTarget(code: string) {
		targets = targets.includes(code) ? targets.filter((item) => item !== code) : [...targets, code];
	}
</script>

<div class="workspace-grid stt-workspace">
	<SpeechInputPanel
		fileName={file?.name}
		{busy}
		{recording}
		{sttProvider}
		{text}
		onFileChange={onFileChange}
		onToggleRecord={toggleRecord}
		onTranscribe={transcribe}
		onTextChange={(value) => (text = value)}
	/>
	<div class="inspector-stack">
		<SttSettingsPanel
			{sttProvider}
			{language}
			{targets}
			{busy}
			hasText={Boolean(text.trim())}
			onSttProviderChange={(value) => (sttProvider = value)}
			onLanguageChange={(value) => (language = value)}
			onToggleTarget={toggleTarget}
			onTranslate={translateText}
		/>
		<SttTranslationResults {translations} />
	</div>
</div>