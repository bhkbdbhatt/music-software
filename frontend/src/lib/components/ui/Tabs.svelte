<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '#lib/utils/cn.js';

	interface Tab {
		id: string;
		label: string;
	}

	interface Props {
		tabs: Tab[];
		value?: string;
		class?: string;
		onchange?: (id: string) => void;
		children?: Snippet;
	}

	let {
		tabs,
		value = $bindable(tabs[0]?.id ?? ''),
		class: className = '',
		onchange,
		children
	}: Props = $props();

	function select(id: string) {
		value = id;
		onchange?.(id);
	}
</script>

<div class={cn('border-b border-border', className)}>
	<div class="flex gap-1 overflow-x-auto" role="tablist">
		{#each tabs as tab (tab.id)}
			<button
				type="button"
				role="tab"
				aria-selected={value === tab.id}
				onclick={() => select(tab.id)}
				class="cursor-pointer border-b-2 px-3 py-2 text-sm whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary {value ===
				tab.id
					? 'border-primary font-medium text-foreground'
					: 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				{tab.label}
			</button>
		{/each}
	</div>
</div>

{#if children}
	<div class="pt-4">{@render children()}</div>
{/if}
