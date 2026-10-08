<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Component } from 'svelte';

	interface Props {
		icon?: Component<{ size?: number | string; class?: string }>;
		title: string;
		description?: string;
		children?: Snippet;
	}

	let { icon: Icon, title, description, children }: Props = $props();
</script>

<div
	class="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border px-6 py-12 text-center"
>
	{#if Icon}
		<Icon size={22} class="text-muted-foreground" />
	{/if}
	<p class="text-sm font-medium">{title}</p>
	{#if description}
		<p class="max-w-sm text-xs text-muted-foreground">{description}</p>
	{/if}
	{#if children}
		<div class="mt-2">{@render children()}</div>
	{/if}
</div>
