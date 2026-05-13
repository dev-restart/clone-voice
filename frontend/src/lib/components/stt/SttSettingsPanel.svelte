<script lang="ts">
	import { languages } from '$lib/studio/api';

	let {
		sttProvider,
		language,
		targets,
		busy,
		hasText,
		onSttProviderChange,
		onLanguageChange,
		onToggleTarget,
		onTranslate
	}: {
		sttProvider: 'whisper' | 'apple-speech';
		language: string;
		targets: string[];
		busy: boolean;
		hasText: boolean;
		onSttProviderChange: (value: 'whisper' | 'apple-speech') => void;
		onLanguageChange: (value: string) => void;
		onToggleTarget: (code: string) => void;
		onTranslate: () => void;
	} = $props();
</script>

<aside class="surface inspector stt-settings-card">
	<div class="inspector-heading">
		<h2>인식/번역 설정</h2>
		<p>원본 언어를 알면 인식 정확도가 좋아지고, 변환된 텍스트는 선택한 언어로 번역됩니다.</p>
	</div>
	<label>인식 엔진
		<select class="studio-input" value={sttProvider} onchange={(event) => onSttProviderChange(event.currentTarget.value as 'whisper' | 'apple-speech')}>
			<option value="whisper">Whisper</option>
			<option value="apple-speech">Apple Speech</option>
		</select>
	</label>
	<label>원본 언어
		<select class="studio-input" value={language} onchange={(event) => onLanguageChange(event.currentTarget.value)}>
			<option value="">자동 감지</option>
			{#each languages as item}<option value={item.code}>{item.label}</option>{/each}
		</select>
	</label>
	<div class="translation-target-picker">
		<div>
			<strong>번역 언어</strong>
			<p>여러 언어를 동시에 선택할 수 있습니다.</p>
		</div>
		<div class="button-row wrap stt-lang-row">
			{#each languages as item}<button class:selected={targets.includes(item.code)} onclick={() => onToggleTarget(item.code)}>{item.label}</button>{/each}
		</div>
	</div>
	<button class="primary-action full" disabled={busy || !hasText} onclick={onTranslate}>{hasText ? '선택 언어로 번역' : '텍스트 변환 후 번역'}</button>
</aside>
