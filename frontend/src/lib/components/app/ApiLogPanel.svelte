<script lang="ts">
	import type { ApiLogEntry } from '$lib/studio/api';

	let { logs = [], open = false }: { logs?: ApiLogEntry[]; open?: boolean } = $props();
</script>

<details class="api-log-panel" {open}>
	<summary>최근 API 로그</summary>
	<div>
		{#each logs.slice(0, 5) as log}
			<p class:error={!log.ok}>
				<span>{log.at}</span>
				<b>{log.method}</b>
				<code>{log.url}</code>
				<em>{log.status ?? 'network'} · {log.duration_ms}ms</em>
				{#if log.error}<small>{log.error}</small>{/if}
			</p>
		{/each}
	</div>
</details>
