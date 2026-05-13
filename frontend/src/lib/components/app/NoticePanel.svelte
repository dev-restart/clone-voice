<script lang="ts">
	import type { StudioNotice } from '$lib/studio/types';

	let { notice }: { notice: StudioNotice } = $props();
</script>

<div class={`notice ${notice.type}`} role={notice.type === 'error' ? 'alert' : 'status'}>{notice.text}</div>
