<script lang="ts">
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import { onMount } from 'svelte';
	import { i18n, t } from '$lib/i18n/index.svelte';

	let { children } = $props();
	onMount(() => i18n.init());
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>{t('app.title')}</title>
	<meta name="description" content={t('app.description')} />
</svelte:head>
{@render children()}
