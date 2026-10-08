<script lang="ts">
	import { Menu } from '@lucide/svelte';
	import { page } from '$app/state';
	import type { Snippet } from 'svelte';
	import { NAV_GROUPS } from './nav';
	import ThemeToggle from './ThemeToggle.svelte';

	interface Props {
		onMenuToggle: () => void;
		actions?: Snippet;
	}

	let { onMenuToggle, actions }: Props = $props();

	const title = $derived.by(() => {
		const path = page.url.pathname;
		for (const group of NAV_GROUPS) {
			for (const item of group.items) {
				if (
					item.href === '/' ? path === '/' : path === item.href || path.startsWith(`${item.href}/`)
				) {
					return item.label;
				}
			}
		}
		return 'SampleForge';
	});
</script>

<header
	class="sticky top-0 z-30 flex items-center gap-3 border-b border-border bg-card/90 px-4 py-2.5 backdrop-blur"
>
	<button
		type="button"
		onclick={onMenuToggle}
		aria-label="Toggle navigation"
		class="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground md:hidden"
	>
		<Menu size={18} />
	</button>

	<h1 class="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight">{title}</h1>

	<div class="flex items-center gap-2">
		{#if actions}{@render actions()}{/if}
		<ThemeToggle />
	</div>
</header>
