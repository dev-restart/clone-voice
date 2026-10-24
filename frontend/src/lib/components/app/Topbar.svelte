<script lang="ts">
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import { t, type MessageKey } from '$lib/i18n/index.svelte';
	import type { MenuKey } from '$lib/studio/types';
	import LanguageSwitcher from './LanguageSwitcher.svelte';
	import { studioMenus } from './navigation';

	let { active }: { active: MenuKey } = $props();

	let title = $derived(
		active === 'voices' ? t('nav.tts') : t(studioMenus.find((menu) => menu.key === active)?.labelKey ?? 'nav.home')
	);
	let description = $derived(t(`page.${active}` as MessageKey));
</script>

<header class="studio-topbar">
	<div class="flex items-center gap-1">
		<h1 data-route-heading tabindex="-1">{title}</h1>
		<HelpPopover label={title} text={description} />
	</div>
	<LanguageSwitcher class="shrink-0" />
</header>
