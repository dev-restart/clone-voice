<script lang="ts">
	import { Activity, ArrowRight, AudioLines, Check, Cpu, Mic, Plus, RefreshCw, ShieldCheck, Sparkles, Wand2 } from '@lucide/svelte';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import TtsTemplatePicker from '$lib/components/tts/TtsTemplatePicker.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import { audioUrl } from '$lib/studio/api';
	import type { ProductionTemplate } from '$lib/studio/production';
	import type { ContentItem, RuntimeHealth, RuntimeModelStatus, VoiceProfile } from '$lib/studio/types';

	let {
		voicesCount = 0,
		voices = [],
		selectedVoiceId = '',
		models = [],
		contents = [],
		health = null,
		lastRefreshedAt = '',
		refreshing = false,
		onCreateVoice,
		onNavigateTts,
		onNavigateSfx,
		onCreateTts,
		onOpenContent,
		onUseTemplate,
		onOpenSettings,
		onNavigateStory,
		onNavigateStt,
		onNavigateChanger,
		onRefresh,
		onSelectVoice,
		onUseVoice
	}: {
		voicesCount?: number;
		voices?: VoiceProfile[];
		selectedVoiceId?: string;
		models?: RuntimeModelStatus[];
		contents?: ContentItem[];
		health?: RuntimeHealth | null;
		lastRefreshedAt?: string;
		refreshing?: boolean;
		onCreateVoice: () => void;
		onNavigateTts: () => void;
		onNavigateSfx: () => void;
		onCreateTts: () => void;
		onOpenContent: (content: ContentItem) => void;
		onUseTemplate: (template: ProductionTemplate) => void;
		onOpenSettings: () => void;
		onNavigateStory: () => void;
		onNavigateStt: () => void;
		onNavigateChanger: () => void;
		onRefresh: () => void;
		onSelectVoice: (id: string) => void;
		onUseVoice: (id: string, target: 'tts' | 'story' | 'changer') => void;
	} = $props();

	let availableModels = $derived(models.filter((model) => model.status === 'available'));
	let unavailableModels = $derived(models.filter((model) => model.status === 'unavailable'));
	let primaryModel = $derived(availableModels.find((model) => model.capabilities.tts) ?? availableModels[0]);
	let totalResults = $derived(contents.reduce((sum, item) => sum + item.results.length, 0));
	let vcReady = $derived(models.some((model) => model.status === 'available' && model.capabilities.voice_conversion));
	let sttReady = $derived(models.some((model) => model.status === 'available' && model.capabilities.stt) || health?.ok);
	let selectedVoice = $derived(voices.find((voice) => voice.id === selectedVoiceId));
	let recentContents = $derived([...contents].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 5));

	// First-run checklist: each step is derived from real state, so it completes by itself.
	let voiceEngineReady = $derived(availableModels.some((model) => model.capabilities.tts));
	let steps = $derived([
		{ id: 'engine', done: voiceEngineReady, label: t('home.start.engine'), action: t('home.start.engine.action'), run: onOpenSettings },
		{ id: 'voice', done: voicesCount > 0, label: t('home.start.voice'), action: t('home.start.voice.action'), run: onCreateVoice },
		{ id: 'speech', done: totalResults > 0, label: t('home.start.speech'), action: t('home.start.speech.action'), run: onCreateTts }
	]);
	let doneCount = $derived(steps.filter((step) => step.done).length);
	let nextStepId = $derived(steps.find((step) => !step.done)?.id);

	const cardClass = 'border-border bg-card rounded-xl border p-5';
</script>

<section class="home-dashboard grid gap-6">
	<header class="flex flex-wrap items-center justify-between gap-3">
		<h2 class="text-2xl font-semibold">{t('home.title')}</h2>
		<span class="text-muted-foreground inline-flex items-center gap-1 text-xs">
			<Badge variant="success"><ShieldCheck size={12} aria-hidden="true" />{t('home.offline')}</Badge>
			<HelpPopover label={t('home.offline')} text={t('home.offline.help')} />
		</span>
	</header>

	{#if doneCount < steps.length}
		<section class="{cardClass} grid gap-3" aria-labelledby="start-heading">
			<div class="flex items-center justify-between gap-3">
				<h3 id="start-heading" class="text-base font-semibold">{t('home.start.title')}</h3>
				<span class="text-muted-foreground text-xs">{t('home.start.progress', { done: doneCount, total: steps.length })}</span>
			</div>
			<ol class="m-0 grid list-none gap-2 p-0">
				{#each steps as step, index (step.id)}
					<li class="flex items-center gap-3 rounded-lg px-1 py-1">
						<span class="flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold {step.done ? 'bg-success text-white' : step.id === nextStepId ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'}">
							{#if step.done}<Check size={14} aria-hidden="true" />{:else}{index + 1}{/if}
						</span>
						<span class="flex-1 text-sm {step.done ? 'text-muted-foreground line-through' : ''}">{step.label}</span>
						{#if !step.done}
							<Button variant={step.id === nextStepId ? 'default' : 'outline'} size="sm" onclick={step.run}>{step.action}<ArrowRight size={14} aria-hidden="true" /></Button>
						{/if}
					</li>
				{/each}
			</ol>
		</section>
	{/if}

	<nav class="core-workflows" aria-label={t('home.workflows.aria')}>
		<button onclick={onCreateTts}><AudioLines size={24} /><strong>{t('nav.tts')}</strong><span>{t('home.tts.desc')}</span></button>
		<button onclick={onNavigateSfx}><Sparkles size={24} /><strong>{t('nav.sfx')}</strong><span>{t('home.sfx.desc')}</span></button>
		<button onclick={onNavigateChanger}><Wand2 size={24} /><strong>{t('nav.changer')}</strong><span>{t('home.cover.desc')}</span></button>
	</nav>

	{#if voices.length}
		<section class="{cardClass} grid gap-4" aria-labelledby="voice-start-heading">
			<div class="flex items-center justify-between gap-3">
				<h3 id="voice-start-heading" class="text-base font-semibold">{t('home.voices.title')}</h3>
				<span class="text-muted-foreground text-xs">{t('home.count', { count: voices.length })}</span>
			</div>
			<div class="grid gap-4 md:grid-cols-[minmax(0,1.5fr)_minmax(220px,1fr)]">
				<div class="grid min-w-0 content-start gap-2.5">
					<label for="home-voice-select" class="text-sm font-semibold">{t('home.voices.select')}</label>
					<select id="home-voice-select" class="studio-input" value={selectedVoiceId} onchange={(event) => onSelectVoice(event.currentTarget.value)}>
						<option value="">{t('home.voices.placeholder')}</option>
						{#each voices as voice (voice.id)}<option value={voice.id}>{voice.name}</option>{/each}
					</select>
					{#if selectedVoice}
						<audio class="h-10 w-full" controls preload="none" aria-label={t('home.voices.sample')} src={audioUrl(selectedVoice.audio_url)}></audio>
					{/if}
				</div>
				<div class="grid content-start gap-2">
					<Button onclick={() => onUseVoice(selectedVoiceId, 'tts')} disabled={!selectedVoice}><AudioLines size={16} />{t('home.voices.narrate')}</Button>
					<Button variant="secondary" onclick={() => onUseVoice(selectedVoiceId, 'changer')} disabled={!selectedVoice || !vcReady}><Wand2 size={16} />{t('home.voices.cover')}</Button>
				</div>
			</div>
		</section>
	{:else}
		<div class="bg-brand-soft flex flex-wrap items-center gap-3 rounded-xl px-5 py-4">
			<Mic size={19} class="text-brand shrink-0" aria-hidden="true" />
			<strong class="flex-1 text-sm">{t('home.firstVoice')}</strong>
			<Button variant="secondary" onclick={onCreateVoice}><Plus size={16} />{t('nav.voice.register')}</Button>
		</div>
	{/if}

	<section class="grid gap-3">
		<h3 class="text-base font-semibold">{t('home.templates.title')}</h3>
		<TtsTemplatePicker onSelect={onUseTemplate} />
	</section>

	<section class="text-muted-foreground flex flex-wrap gap-x-6 gap-y-1 text-sm" aria-label={t('home.summary.aria')}>
		<span>{t('home.summary.voices')} <strong class="text-foreground">{t('home.count', { count: voicesCount })}</strong></span>
		<span>{t('home.summary.scripts')} <strong class="text-foreground">{t('home.count', { count: contents.length })}</strong></span>
		<span>{t('home.summary.results')} <strong class="text-foreground">{t('home.count', { count: totalResults })}</strong></span>
	</section>

	<div class="grid items-start gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(260px,1fr)]">
		<section class="{cardClass} grid gap-3">
			<div class="flex items-center justify-between gap-3">
				<h3 class="text-base font-semibold">{t('home.recent.title')}</h3>
				<Button variant="ghost" size="sm" onclick={onNavigateTts}>{t('home.recent.all')}</Button>
			</div>
			<div class="recent-work-list">
				{#each recentContents as item (item.id)}
					<button onclick={() => onOpenContent(item)}>
						<span class="recent-work-icon"><AudioLines size={17} /></span>
						<span class="recent-work-copy"><strong>{item.title}</strong><small>{new Date(item.updated_at).toLocaleString(i18n.intl)}</small></span>
						<span class="recent-work-result">{t('home.recent.results', { count: item.results.length })}</span>
					</button>
				{:else}
					<div class="flex items-center justify-between gap-3 py-2">
						<span class="text-muted-foreground text-sm">{t('home.recent.empty')}</span>
						<Button variant="outline" size="sm" onclick={onCreateTts}><Plus size={14} />{t('home.recent.new')}</Button>
					</div>
				{/each}
			</div>
		</section>

		<aside class="{cardClass} grid gap-3">
			<div class="flex items-center justify-between gap-3">
				<div>
					<h3 class="text-base font-semibold">{t('home.status.title')}</h3>
					<p class="text-muted-foreground text-xs">{lastRefreshedAt ? t('home.status.checked', { time: lastRefreshedAt }) : t('home.status.now')}</p>
				</div>
				<Button variant="ghost" size="icon" aria-label={t('models.reload')} onclick={onRefresh} disabled={refreshing}><RefreshCw size={16} class={refreshing ? 'animate-spin' : ''} /></Button>
			</div>
			<div class="grid gap-2 text-sm">
				<div class="flex items-center justify-between gap-3"><span class="inline-flex items-center gap-2"><Activity size={16} />{t('home.status.server')}</span><Badge variant={health?.ok ? 'success' : 'danger'}>{health?.ok ? t('home.status.ok') : t('home.status.check')}</Badge></div>
				<div class="flex items-center justify-between gap-3"><span class="inline-flex items-center gap-2"><Cpu size={16} />{t('home.status.engine')}</span><strong>{primaryModel?.label ?? t('home.status.needsSetup')}</strong></div>
			</div>
			<div class="flex flex-wrap gap-2">
				<Button variant="secondary" size="sm" onclick={onNavigateStt} disabled={!sttReady}><Mic size={15} />{t('home.status.stt')}</Button>
				<Button variant="secondary" size="sm" onclick={onNavigateChanger} disabled={!vcReady}><Wand2 size={15} />{t('nav.changer')}</Button>
			</div>
			{#if !primaryModel || unavailableModels.length}<button class="runtime-setup-link" onclick={onOpenSettings}>{t('home.status.setup')}</button>{/if}
		</aside>
	</div>
</section>

<style>
	.core-workflows { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
	.core-workflows button { display: grid; align-content: start; text-align: left; gap: 10px; border: 1px solid var(--border); border-radius: 12px; padding: 22px; background: var(--card); color: var(--foreground); cursor: pointer; }
	.core-workflows button:hover { border-color: var(--accent); background: var(--accent-soft); }
	.core-workflows button:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
	.core-workflows strong { font-size: 18px; }
	.core-workflows span { color: var(--muted-foreground); font-size: 13px; line-height: 1.6; }
	@media (max-width: 760px) { .core-workflows { grid-template-columns: 1fr; gap: 10px; } .core-workflows button { padding: 18px; gap: 6px; } }
</style>
