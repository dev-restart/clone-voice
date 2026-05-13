<script lang="ts">
	import { ArrowLeft, Languages, Loader2, Play, Save, Sparkles } from 'lucide-svelte';
	import ProgressPanel from '$lib/components/app/ProgressPanel.svelte';
	import { languages } from '$lib/studio/api';
	import type { ContentItem } from '$lib/studio/types';

	let {
		selectedContentId,
		title,
		text,
		translations,
		selectedTargets,
		busy,
		canSave,
		canGenerate,
		canTranslate,
		modelId = '',
		speed = 1,
		generationProgress,
		onBack,
		onSave,
		onGenerate,
		onTranslate,
		onTitleChange,
		onTextChange,
		onTranslationChange,
		onToggleTarget
	}: {
		selectedContentId: string;
		title: string;
		text: string;
		translations: Record<string, string>;
		selectedTargets: string[];
		busy: boolean;
		canSave: boolean;
		canGenerate: boolean;
		canTranslate: boolean;
		modelId?: string;
		speed?: number;
		generationProgress: { percent: number; message: string; elapsed: number; active: boolean };
		onBack: () => void;
		onSave: () => void;
		onGenerate: (targetLanguage?: string, targetText?: string) => void;
		onTranslate: () => void;
		onTitleChange: (value: string) => void;
		onTextChange: (value: string) => void;
		onTranslationChange: (code: string, value: string) => void;
		onToggleTarget: (code: string) => void;
	} = $props();

	function appendTag(tag: string) {
		onTextChange(`${text.trim()} ${tag} `.trimStart());
	}

	let textLength = $derived(text.trim().length);
	let safeSpeed = $derived(Math.max(0.5, Math.min(2, speed || 1)));
	let estimatedSeconds = $derived(textLength ? Math.max(3, Math.round(textLength / 6 / safeSpeed)) : 0);
	let estimatedLength = $derived(estimatedSeconds ? `${estimatedSeconds}초 안팎` : '대기');
	let longVoxCpmScript = $derived(modelId === 'voxcpm' && estimatedSeconds > 90);
</script>

<section class="surface workspace-main tts-editor-card">
	<div class="section-heading">
		<div>
			<h2>{selectedContentId ? '대본 작업실' : '새 음성 콘텐츠'}</h2>
			<p>대본을 저장하고, 원하는 목소리와 언어 설정으로 음성을 생성합니다.</p>
		</div>
		<div class="button-row wrap">
			<button class="secondary-action" onclick={onBack}><ArrowLeft size={17} />목록</button>
			<button class="secondary-action" disabled={!canSave} onclick={onSave}><Save size={17} />저장</button>
			<button class="primary-action" disabled={!canGenerate} onclick={() => onGenerate()}>
				{#if busy}<Loader2 class="spin" size={18} />생성 중{:else}<Sparkles size={18} />음성 생성{/if}
			</button>
		</div>
	</div>

	<div class="tts-editor-meta" aria-label="대본 상태">
		<span><strong>{selectedContentId ? '저장된 콘텐츠' : '새 초안'}</strong><small>상태</small></span>
		<span><strong>{textLength.toLocaleString()}자</strong><small>대본 길이</small></span>
		<span><strong>{estimatedLength}</strong><small>예상 음성 길이</small></span>
	</div>

	<label class="title-field">제목<input class="studio-input" value={title} oninput={(event) => onTitleChange(event.currentTarget.value)} placeholder="예: 서비스 소개 내레이션" /></label>
	<ProgressPanel progress={generationProgress} fallbackMessage="음성 생성 중입니다." />
	{#if longVoxCpmScript}
		<p class="warning-note">VoxCPM2 긴 대본은 음색 흔들림을 줄이는 범위 안에서 자동 분할해 생성합니다. 90초 이하 대본은 한 번에 생성됩니다.</p>
	{/if}
	<div class="script-field-head">
		<div>
			<strong>대본</strong>
			<p>짧은 대본은 한 번에 생성하고, 긴 대본은 안정성을 위해 자동 분할됩니다. 필요한 경우 아래 태그를 넣어 감정을 보강하세요.</p>
		</div>
		<span class="soft-badge">{textLength.toLocaleString()}자</span>
	</div>
	<textarea class="script-editor" value={text} oninput={(event) => onTextChange(event.currentTarget.value)} placeholder="음성으로 만들 대본을 입력하세요. 예: 오늘 업데이트 내용을 차분하게 안내합니다."></textarea>
	<div class="inline-toolbar">
		<button onclick={() => appendTag('[laughter]')}>웃음 태그</button>
		<button onclick={() => appendTag('[sigh]')}>한숨 태그</button>
		<button onclick={() => appendTag('[gasp]')}>놀람 태그</button>
	</div>

	<section class="translation-band">
		<div>
			<h3><Languages size={18} />언어 변환</h3>
			<p>원본이 한국어가 아니어도 원하는 언어로 번역 후 해당 언어 발음 힌트를 적용합니다.</p>
		</div>
		<div class="button-row">
			{#each languages.filter((item) => item.code !== 'ko') as item (item.code)}
				<button class:selected={selectedTargets.includes(item.code)} onclick={() => onToggleTarget(item.code)}>{item.label}</button>
			{/each}
			<button class="secondary-action" disabled={!canTranslate} onclick={onTranslate}>선택 언어 번역</button>
		</div>
	</section>
	<div class="translation-grid">
		{#each Object.entries(translations) as [code, value] (code)}
			<article>
				<strong>{languages.find((item) => item.code === code)?.label ?? code}</strong>
				<textarea class="studio-input" value={value} oninput={(event) => onTranslationChange(code, event.currentTarget.value)}></textarea>
				<button class="secondary-action full" disabled={busy} onclick={() => onGenerate(code, translations[code])}><Play size={17} />이 번역본으로 생성</button>
			</article>
		{:else}
			<div class="translation-empty-inline">
				<strong>번역본이 아직 없습니다.</strong>
				<p>언어를 선택하고 번역하면 언어별 대본이 이곳에 표시됩니다.</p>
			</div>
		{/each}
	</div>
</section>
