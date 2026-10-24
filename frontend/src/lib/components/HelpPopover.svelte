<script lang="ts">
	import { CircleHelp } from '@lucide/svelte';
	import { onDestroy } from 'svelte';
	import * as Popover from '$lib/components/ui/popover';
	import { t } from '$lib/i18n/index.svelte';

	// A "?" button that explains one control. Opens on hover, focus-click or keyboard, closes on Escape / outside click.
	let { label, text, title }: { label: string; text: string; title?: string } = $props();

	let open = $state(false);
	let pinned = $state(false);
	let leaveTimer: ReturnType<typeof setTimeout> | undefined;
	onDestroy(() => clearTimeout(leaveTimer));

	function hoverEnter(event: PointerEvent) {
		if (event.pointerType === 'touch') return;
		clearTimeout(leaveTimer);
		open = true;
	}

	function hoverLeave(event: PointerEvent) {
		if (event.pointerType === 'touch' || pinned) return;
		// Leave a short grace period so the pointer can cross the gap between the button and the card.
		leaveTimer = setTimeout(() => (open = false), 180);
	}

	function toggle(event: MouseEvent) {
		event.preventDefault();
		clearTimeout(leaveTimer);
		if (open && pinned) {
			open = false;
			pinned = false;
		} else {
			open = true;
			pinned = true;
		}
	}
</script>

<Popover.Root bind:open onOpenChange={(next) => { if (!next) pinned = false; }}>
	<Popover.Trigger
		type="button"
		aria-label={t('common.help', { label })}
		class="text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-ring/60 data-[state=open]:bg-muted data-[state=open]:text-foreground inline-flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-full align-middle outline-none focus-visible:ring-2"
		onpointerenter={hoverEnter}
		onpointerleave={hoverLeave}
		onclick={toggle}
	>
		<CircleHelp size={15} aria-hidden="true" />
	</Popover.Trigger>
	<Popover.Content
		role="note"
		aria-label={t('common.helpGroup', { label })}
		class="w-64 max-w-[calc(100vw-2rem)] gap-1.5 p-3 text-xs leading-relaxed font-normal"
		side="bottom"
		align="start"
		collisionPadding={16}
		trapFocus={false}
		onOpenAutoFocus={(event) => event.preventDefault()}
		onCloseAutoFocus={(event) => event.preventDefault()}
		onpointerenter={hoverEnter}
		onpointerleave={hoverLeave}
	>
		{#if title}<p class="text-foreground text-[0.8rem] font-semibold">{title}</p>{/if}
		<p class="text-foreground/90 break-words">{text}</p>
	</Popover.Content>
</Popover.Root>
