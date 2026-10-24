<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { Check, Loader2, Sparkles, X } from '@lucide/svelte';
	import { apiFetch } from '$lib/studio/api';
	import HelpPopover from '$lib/components/HelpPopover.svelte';

	type Mode = 'write' | 'polish' | 'shorten' | 'expand';
	type Proposal = { text: string; mode: Mode; chars: number; estimated_seconds: number; provider: string; model: string };

	let {
		text,
		language,
		disabled = false,
		onApply,
		onNotice
	}: {
		text: string;
		language: string;
		disabled?: boolean;
		onApply: (value: string) => void;
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
	} = $props();

	const lengths = $derived([
		{ label: t('tts.assist.lengthFree'), value: 0 },
		{ label: t('tts.assist.s15'), value: 15 },
		{ label: t('tts.assist.s30'), value: 30 },
		{ label: t('tts.assist.m1'), value: 60 },
		{ label: t('tts.assist.m2'), value: 120 }
	]);
	const tones = $derived([t('tts.assist.tone.friendly'), t('tts.assist.tone.professional'), t('tts.assist.tone.calm'), t('tts.assist.tone.lively')]);
	const editActions = $derived<{ mode: Exclude<Mode, 'write'>; label: string }[]>([
		{ mode: 'polish', label: t('tts.assist.polish') },
		{ mode: 'shorten', label: t('tts.assist.shorten') },
		{ mode: 'expand', label: t('tts.assist.expand') }
	]);
	const supported = ['ko', 'en', 'ja', 'zh'];

	let open = $state(false);
	let brief = $state('');
	let targetSeconds = $state(0);
	let tone = $state('');
	let busyMode = $state<Mode | ''>('');
	let proposal = $state<Proposal | null>(null);
	let hasText = $derived(Boolean(text.trim()));
	let outputLanguage = $derived(supported.includes(language) ? language : 'ko');

	async function run(mode: Mode) {
		if (busyMode || disabled) return;
		if (mode === 'write' && !brief.trim() && !hasText) {
			onNotice('info', t('tts.assist.needBrief'));
			return;
		}
		busyMode = mode;
		try {
			const response = await apiFetch('/api/tts/script-assist', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					mode,
					text: mode === 'write' ? '' : text,
					brief: mode === 'write' ? brief : '',
					tone,
					language: outputLanguage,
					target_seconds: targetSeconds || null
				})
			});
			proposal = { ...(await response.json()), mode };
		} catch (error) {
			onNotice('error', error instanceof Error ? error.message : String(error));
		} finally {
			busyMode = '';
		}
	}

	function apply(replace: boolean) {
		if (!proposal) return;
		onApply(replace || !hasText ? proposal.text : `${text.trimEnd()}\n\n${proposal.text}`);
		proposal = null;
		onNotice('success', t('tts.assist.applied'));
	}
</script>

<section class="script-assist" aria-label={t('tts.assist.region')}>
	<div class="assist-heading">
		<button type="button" class="assist-toggle" aria-expanded={open} onclick={() => (open = !open)}>
			<Sparkles size={16} /><strong>{t('tts.assist.toggle')}</strong>
		</button>
		<HelpPopover label={t('tts.assist.toggle')} text={t('tts.assist.help')} />
	</div>
	{#if open}
		<div class="assist-body">
			<div class="brief-row">
				<input class="studio-input" aria-label={t('tts.assist.briefLabel')} bind:value={brief} maxlength="2000" placeholder={t('tts.assist.briefPlaceholder')} onkeydown={(event) => { if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); void run('write'); } }} />
				<button type="button" class="primary-action" disabled={disabled || Boolean(busyMode)} onclick={() => run('write')}>
					{#if busyMode === 'write'}<Loader2 class="spin" size={16} />{t('tts.assist.making')}{:else}<Sparkles size={16} />{t('tts.assist.make')}{/if}
				</button>
			</div>
			<div class="option-row">
				<div class="chips" role="group" aria-label={t('tts.assist.lengthLabel')}>
					{#each lengths as item (item.value)}<button type="button" class:active={targetSeconds === item.value} onclick={() => (targetSeconds = item.value)}>{item.label}</button>{/each}
				</div>
				<div class="chips" role="group" aria-label={t('tts.assist.toneLabel')}>
					{#each tones as item (item)}<button type="button" class:active={tone === item} onclick={() => (tone = tone === item ? '' : item)}>{item}</button>{/each}
				</div>
			</div>
			{#if hasText}
				<div class="edit-row">
					<span>{t('tts.assist.editPrefix')}</span>
					{#each editActions as action (action.mode)}
						<button type="button" class="secondary-action mini" disabled={disabled || Boolean(busyMode)} onclick={() => run(action.mode)}>
							{#if busyMode === action.mode}<Loader2 class="spin" size={14} />{/if}{action.label}
						</button>
					{/each}
				</div>
			{/if}
			{#if proposal}
				<article class="proposal" aria-live="polite">
					<header><strong>{t('tts.assist.proposal')}</strong><span>{t('tts.assist.proposalMeta', { chars: proposal.chars.toLocaleString(), seconds: proposal.estimated_seconds })}</span></header>
					<p>{proposal.text}</p>
					<footer>
						<button type="button" class="primary-action" onclick={() => apply(true)}><Check size={16} />{proposal.mode === 'write' && hasText ? t('tts.assist.replace') : t('tts.assist.use')}</button>
						{#if proposal.mode === 'write' && hasText}<button type="button" class="secondary-action" onclick={() => apply(false)}>{t('tts.assist.append')}</button>{/if}
						<button type="button" class="secondary-action" onclick={() => (proposal = null)}><X size={16} />{t('common.close')}</button>
					</footer>
				</article>
			{/if}
		</div>
	{/if}
</section>

<style>
	.script-assist { border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--card-elevated); }
	.assist-heading { display: flex; align-items: center; gap: 8px; padding-right: 12px; }
	.assist-toggle { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; border: 0; background: transparent; padding: 11px 14px; text-align: left; color: var(--accent-hover); cursor: pointer; }
	.assist-toggle strong { font-size: 14px; color: var(--foreground); }
	.assist-body { display: grid; gap: 12px; border-top: 1px solid var(--border-soft); padding: 14px; }
	.brief-row { display: flex; gap: 8px; }
	.brief-row .studio-input { flex: 1; min-width: 0; }
	.option-row { display: flex; flex-wrap: wrap; gap: 8px 18px; }
	.chips { display: flex; flex-wrap: wrap; gap: 6px; }
	.chips button { min-height: 28px; border: 1px solid var(--border); border-radius: 999px; background: var(--card); padding: 0 12px; color: var(--muted-foreground); font-size: 12.5px; cursor: pointer; }
	.chips button.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent-hover); font-weight: 650; }
	.edit-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
	.edit-row > span { color: var(--muted-foreground); font-size: 12.5px; }
	.proposal { display: grid; gap: 10px; border: 1px solid var(--accent); border-radius: var(--radius-sm); background: var(--accent-soft); padding: 12px 14px; }
	.proposal header { display: flex; justify-content: space-between; gap: 10px; font-size: 13px; }
	.proposal header span { color: var(--muted-foreground); }
	.proposal p { margin: 0; max-height: 240px; overflow: auto; white-space: pre-wrap; font-size: 14px; line-height: 1.7; }
	.proposal footer { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
	@media (max-width: 640px) { .brief-row { flex-direction: column; } }
</style>
