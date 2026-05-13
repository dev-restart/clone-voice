<script lang="ts">
	import { FileAudio, Mic, TextCursorInput } from 'lucide-svelte';

	let {
		fileName,
		busy,
		recording,
		sttProvider,
		text,
		onFileChange,
		onToggleRecord,
		onTranscribe,
		onTextChange
	}: {
		fileName?: string;
		busy: boolean;
		recording: boolean;
		sttProvider: 'whisper' | 'apple-speech';
		text: string;
		onFileChange: (event: Event) => void;
		onToggleRecord: () => void;
		onTranscribe: () => void;
		onTextChange: (value: string) => void;
	} = $props();
</script>

<section class="surface workspace-main stt-input-card">
	<div class="section-heading">
		<div>
			<h2>오디오 텍스트화</h2>
			<p>파일을 올리거나 바로 녹음한 뒤, 결과 텍스트를 확인하고 필요한 언어로 번역합니다.</p>
		</div>
		<button class="primary-action" disabled={busy || !fileName} onclick={onTranscribe}><TextCursorInput size={18} />{sttProvider === 'apple-speech' ? 'Apple Speech 변환' : 'Whisper 변환'}</button>
	</div>

	<div class="stt-flow-row" aria-label="음성 텍스트 변환 단계">
		<span class:active={Boolean(fileName)}>1. 오디오 선택</span>
		<span class:active={Boolean(text.trim())}>2. 텍스트 확인</span>
		<span>3. 번역 선택</span>
	</div>

	<div class="upload-zone stt-dropzone">
		<div class="stt-file-icon"><FileAudio size={34} /></div>
		<div class="stt-dropcopy">
			<h3>{fileName ?? '오디오 파일을 선택하거나 바로 녹음하세요'}</h3>
			<p>{fileName ? '선택한 오디오를 변환할 준비가 됐습니다.' : 'WAV, MP3, M4A, WebM 파일을 사용할 수 있습니다.'}</p>
		</div>
		<div class="button-row stt-upload-actions">
			<label class="secondary-action">파일 선택<input class="hidden" type="file" accept="audio/*" onchange={onFileChange} /></label>
			<button class="secondary-action" class:recording onclick={onToggleRecord}><Mic size={17} />{recording ? '녹음 종료' : '녹음'}</button>
		</div>
	</div>

	<div class="stt-result-panel">
		<div class="result-editor-head">
			<div>
				<h3>변환 텍스트</h3>
				<p>{text.trim() ? `${text.length.toLocaleString()}자 · 직접 수정 가능` : '변환 결과가 표시되면 내용을 다듬은 뒤 번역할 수 있습니다.'}</p>
			</div>
			<span class="soft-badge">{text.trim() ? '결과 있음' : '대기 중'}</span>
		</div>
		<textarea class="script-editor short" value={text} oninput={(event) => onTextChange(event.currentTarget.value)} placeholder="변환된 텍스트가 여기에 표시됩니다. 필요하면 직접 수정하세요."></textarea>
	</div>
</section>
