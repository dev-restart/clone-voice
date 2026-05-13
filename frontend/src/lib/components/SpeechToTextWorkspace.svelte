<script lang="ts">
	import SpeechInputPanel from '$lib/components/stt/SpeechInputPanel.svelte';
	import SttSettingsPanel from '$lib/components/stt/SttSettingsPanel.svelte';
	import SttTranslationResults from '$lib/components/stt/SttTranslationResults.svelte';
	import { apiFetch } from '$lib/studio/api';

	let { onNotice }: { onNotice: (type: 'success' | 'error' | 'info', text: string) => void } = $props();

	let file = $state<File | null>(null);
	let sttProvider = $state<'whisper' | 'apple-speech'>('whisper');
	let language = $state('');
	let text = $state('');
	let translations = $state<Record<string, string>>({});
	let targets = $state<string[]>(['ko', 'en']);
	let busy = $state(false);
	let recording = $state(false);
	let recorder: MediaRecorder | null = null;
	let chunks: Blob[] = [];

	function onFileChange(event: Event) {
		file = (event.target as HTMLInputElement).files?.[0] ?? null;
	}

	async function toggleRecord() {
		if (recording) {
			recorder?.stop();
			return;
		}
		const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
		chunks = [];
		recorder = new MediaRecorder(stream, { mimeType: MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : undefined });
		recorder.ondataavailable = (event) => {
			if (event.data.size) chunks.push(event.data);
		};
		recorder.onstop = () => {
			stream.getTracks().forEach((track) => track.stop());
			file = new File([new Blob(chunks, { type: 'audio/webm' })], `stt-${Date.now()}.webm`, { type: 'audio/webm' });
			recording = false;
		};
		recorder.start(250);
		recording = true;
	}

	async function transcribe() {
		if (!file) {
			onNotice('error', '텍스트로 변환할 음성 파일이 필요합니다.');
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
			onNotice('success', '음성을 텍스트로 변환했습니다.');
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
			onNotice('success', '텍스트 번역을 완료했습니다.');
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
