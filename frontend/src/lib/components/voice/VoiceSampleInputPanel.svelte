<script lang="ts">
	import { Link, Loader2, Mic, Upload } from 'lucide-svelte';
	import { formatTime } from '$lib/studio/api';

	let {
		recording,
		recordingSeconds,
		youtubeUrl,
		youtubeTitle,
		isolateYouTubeVoice,
		busy,
		importingYouTube,
		onFileChange,
		onToggleRecord,
		onYoutubeUrlChange,
		onIsolateYouTubeVoiceChange,
		onImportYouTube
	}: {
		recording: boolean;
		recordingSeconds: number;
		youtubeUrl: string;
		youtubeTitle: string;
		isolateYouTubeVoice: boolean;
		busy: boolean;
		importingYouTube: boolean;
		onFileChange: (event: Event) => void;
		onToggleRecord: () => void;
		onYoutubeUrlChange: (value: string) => void;
		onIsolateYouTubeVoiceChange: (value: boolean) => void;
		onImportYouTube: () => void;
	} = $props();
</script>

<div class="upload-zone">
	<h3>파일 업로드 또는 녹음</h3>
	<p>파형에서 사용할 5~10초 구간을 선택합니다.</p>
	{#if recording}
		<div class="recording-panel" aria-live="polite">
			<span class="recording-dot"></span>
			<strong>녹음 중 {formatTime(recordingSeconds)}</strong>
			<small>5~10초 정도 녹음한 뒤 녹음 종료를 누르세요.</small>
		</div>
	{/if}
	<div class="button-row center">
		<label class="secondary-action">
			<Upload size={17} />
			업로드
			<input class="hidden" type="file" accept="audio/*" onchange={onFileChange} />
		</label>
		<button class="secondary-action" class:recording onclick={onToggleRecord}>
			<Mic size={17} />
			{recording ? '녹음 종료' : '녹음'}
		</button>
	</div>
	<div class="youtube-import-panel">
		<label>
			<span>유튜브 주소</span>
			<input class="studio-input" value={youtubeUrl} oninput={(event) => onYoutubeUrlChange(event.currentTarget.value)} placeholder="https://www.youtube.com/watch?v=... 또는 https://www.youtube.com/shorts/..." />
			<small>일반 영상, Shorts, youtu.be 공유 주소를 지원합니다.</small>
			<div class="youtube-cleanup-toggle">
				<input type="checkbox" checked={isolateYouTubeVoice} onchange={(event) => onIsolateYouTubeVoiceChange(event.currentTarget.checked)} />
				<span>배경음·효과음을 줄이고 말소리 중심으로 가져오기</span>
			</div>
		</label>
		<button class="secondary-action" disabled={busy || importingYouTube || !youtubeUrl.trim()} onclick={onImportYouTube}>
			{#if importingYouTube}<Loader2 class="spin" size={17} />가져오는 중{:else}<Link size={17} />유튜브 음성 가져오기{/if}
		</button>
	</div>
	{#if youtubeTitle}
		<p class="field-helper">가져온 영상: {youtubeTitle}</p>
	{/if}
</div>
