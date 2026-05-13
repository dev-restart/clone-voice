<script lang="ts">
	import { Mic } from 'lucide-svelte';
	import { languages } from '$lib/studio/api';

	let {
		name,
		transcript,
		sampleText,
		sttProvider,
		sttLanguage,
		busy,
		hasFile,
		onNameChange,
		onTranscriptChange,
		onSttProviderChange,
		onSttLanguageChange,
		onTranscribeSelection
	}: {
		name: string;
		transcript: string;
		sampleText: string;
		sttProvider: 'whisper' | 'apple-speech';
		sttLanguage: string;
		busy: boolean;
		hasFile: boolean;
		onNameChange: (value: string) => void;
		onTranscriptChange: (value: string) => void;
		onSttProviderChange: (value: 'whisper' | 'apple-speech') => void;
		onSttLanguageChange: (value: string) => void;
		onTranscribeSelection: () => void;
	} = $props();
</script>

<div class="voice-form-flow">
	<label>목소리 이름<input class="studio-input" value={name} oninput={(event) => onNameChange(event.currentTarget.value)} placeholder="예: 내 목소리 - 차분한 톤" /></label>

	<label>
		<span class="label-row">
			샘플 발화 대본
			<button class="secondary-action compact" disabled={busy || !hasFile} onclick={onTranscribeSelection} type="button"><Mic size={16} />{sttProvider === 'apple-speech' ? 'Apple Speech' : 'Whisper'} 대본 가져오기</button>
		</span>
		<textarea class="studio-input transcript-box" value={transcript} oninput={(event) => onTranscriptChange(event.currentTarget.value)} placeholder={sampleText}></textarea>
	</label>
	<div class="settings-inline">
		<label>대본 읽기 provider
			<select class="studio-input" value={sttProvider} onchange={(event) => onSttProviderChange(event.currentTarget.value as 'whisper' | 'apple-speech')}>
				<option value="whisper">Whisper</option>
				<option value="apple-speech">Apple Speech</option>
			</select>
		</label>
		<label>대본 언어
			<select class="studio-input" value={sttLanguage} onchange={(event) => onSttLanguageChange(event.currentTarget.value)}>
				{#each languages as item}<option value={item.code}>{item.label}</option>{/each}
			</select>
		</label>
	</div>
	<p class="field-helper">녹음은 예시 문장을 참고하고, 실제 저장 대본은 직접 입력하거나 대본 가져오기로 선택 구간을 텍스트화해 채웁니다.</p>
</div>
