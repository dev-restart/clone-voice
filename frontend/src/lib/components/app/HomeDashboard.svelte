<script lang="ts">
	import { Activity, AudioLines, Mic, Plus, RefreshCw, Settings, Wand2 } from 'lucide-svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import { Card } from '$lib/components/ui/card';
	import type { ContentItem, RuntimeHealth, RuntimeModelStatus } from '$lib/studio/types';

	let {
		voicesCount = 0,
		models = [],
		contents = [],
		health = null,
		lastRefreshedAt = '',
		refreshing = false,
		onCreateVoice,
		onNavigateTts,
		onNavigateStt,
		onNavigateChanger,
		onRefresh
	}: {
		voicesCount?: number;
		models?: RuntimeModelStatus[];
		contents?: ContentItem[];
		health?: RuntimeHealth | null;
		lastRefreshedAt?: string;
		refreshing?: boolean;
		onCreateVoice: () => void;
		onNavigateTts: () => void;
		onNavigateStt: () => void;
		onNavigateChanger: () => void;
		onRefresh: () => void;
	} = $props();

	let availableModels = $derived(models.filter((model) => model.status === 'available'));
	let unavailableModels = $derived(models.filter((model) => model.status === 'unavailable'));
	let vcReady = $derived(models.some((model) => model.status === 'available' && model.capabilities.voice_conversion));
	let sttReady = $derived(models.some((model) => model.status === 'available' && model.capabilities.stt) || health?.ok);
	let recommended = $derived.by(() => {
		if (voicesCount === 0) return '먼저 기준 목소리를 등록하면 TTS와 보이스 체인저 결과를 바로 비교할 수 있습니다.';
		if (!availableModels.length) return '사용 가능한 생성 모델이 없습니다. 모델 설정에서 노출 상태와 준비 상태를 확인하세요.';
		if (!contents.length) return '짧은 안내문을 저장해 두면 다국어 TTS 결과를 반복해서 비교하기 좋습니다.';
		if (!vcReady) return 'Seed-VC 설정을 완료하면 녹음 파일을 선택한 목소리로 직접 변환할 수 있습니다.';
		return '기준 목소리와 콘텐츠가 준비됐습니다. TTS 결과를 만들고 STT로 품질을 확인하세요.';
	});

	function modelBadge(model: RuntimeModelStatus) {
		return model.status === 'available' ? 'success' : 'warning';
	}

	function healthBadge() {
		if (!health) return 'warning';
		return health.ok && !health.model.error ? 'success' : 'danger';
	}

	let refreshIconClass = $derived(refreshing ? 'spin' : '');
</script>

<section class="home-grid">
	<article class="home-hero">
		<img class="hero-art" src="/visuals/studio-hero.png" alt="" aria-hidden="true" />
		<div class="hero-copy">
			<h2>음성 제작 작업실</h2>
			<p>
				등록한 목소리, 대본, 생성 모델을 한 화면에서 확인하고 바로 제작합니다.
				TTS와 변환 결과를 비교하면서 필요한 작업만 이어가세요.
			</p>
			<div class="hero-signal-strip" aria-label="스튜디오 준비 상태">
				<span><strong>{voicesCount}</strong> 기준 목소리</span>
				<span><strong>{availableModels.length}</strong> 사용 가능 모델</span>
				<span><strong>{contents.length}</strong> 저장 콘텐츠</span>
			</div>
		</div>
		<div class="button-row hero-actions">
			<Button onclick={onCreateVoice}><Plus size={17} />새 목소리</Button>
			<Button variant="secondary" onclick={onNavigateTts}><AudioLines size={17} />음성 생성</Button>
			<Button variant="ghost" onclick={onRefresh} disabled={refreshing}><RefreshCw size={17} class={refreshIconClass} />상태 갱신</Button>
		</div>
	</article>

	<div class="home-stat-row">
		<article class="stat-card">
			<span>{voicesCount}</span>
			<p>등록 목소리</p>
		</article>
		<article class="stat-card">
			<span>{availableModels.length}</span>
			<p>사용 가능 모델</p>
		</article>
		<article class="stat-card">
			<span>{contents.length}</span>
			<p>저장 콘텐츠</p>
		</article>
	</div>

	<Card class="surface dashboard-panel system-panel">
		<div class="section-heading compact">
			<div>
				<h2>작업 상태</h2>
				<p>{lastRefreshedAt ? `${lastRefreshedAt} 기준` : '현재 제작 준비 상태를 확인합니다.'}</p>
			</div>
			<Activity size={20} />
		</div>
		<div class="status-list">
			<div>
				<span>API</span>
				<Badge variant={healthBadge()}>{health?.ok ? '정상' : '확인 필요'}</Badge>
			</div>
			<div>
				<span>Voice Engine</span>
				<strong>{health?.model.engine ?? '-'}</strong>
			</div>
			<div>
				<span>Device</span>
				<strong>{health?.model.device ?? '-'}</strong>
			</div>
		</div>
		{#if health?.model.error}
			<p class="warning-note">{health.model.error}</p>
		{/if}
	</Card>

	<Card class="surface dashboard-panel model-panel">
		<div class="section-heading compact">
			<div>
				<h2>생성 모델</h2>
				<p>제작에 사용할 수 있는 모델과 확인이 필요한 모델을 구분합니다.</p>
			</div>
			<Settings size={20} />
		</div>
		<div class="compact-list">
			{#each models as model (model.id)}
				<div>
					<strong>{model.label}</strong>
					<Badge variant={modelBadge(model)}>{model.status === 'unavailable' ? '설정 필요' : '사용 가능'}</Badge>
				</div>
			{/each}
		</div>
		{#if unavailableModels.length}
			<p class="warning-note">{unavailableModels.length}개 모델은 설정 확인이 필요합니다.</p>
		{/if}
	</Card>

	<Card class="surface dashboard-panel content-panel">
		<h2>최근 콘텐츠</h2>
		<div class="compact-list">
			{#each contents.slice(0, 5) as item (item.id)}
				<div><strong>{item.title}</strong><span>{item.results.length} 결과</span></div>
			{:else}
				<p>아직 저장된 콘텐츠가 없습니다. 첫 대본을 저장하면 생성 결과와 번역본을 함께 관리할 수 있습니다.</p>
			{/each}
		</div>
	</Card>

	<Card class="surface dashboard-panel workflow-panel">
		<div class="section-heading compact">
			<div>
				<h2>빠른 작업</h2>
				<p>현재 준비 상태에 맞춰 다음 제작 단계를 추천합니다.</p>
			</div>
		</div>
		<div class="workflow-actions">
			<Button variant="secondary" onclick={onNavigateTts}><AudioLines size={17} />TTS</Button>
			<Button variant="secondary" onclick={onNavigateStt} disabled={!sttReady}><Mic size={17} />STT</Button>
			<Button variant="secondary" onclick={onNavigateChanger} disabled={!vcReady}><Wand2 size={17} />변환</Button>
		</div>
		<div class="recommendation-box">
			<strong>추천 다음 작업</strong>
			<p>{recommended}</p>
		</div>
	</Card>
</section>
