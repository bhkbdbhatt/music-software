<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		label: string;
		hint?: string;
		error?: string;
		for?: string;
		inline?: boolean;
		children?: Snippet;
	}

	let { label, hint, error, for: htmlFor, inline = false, children }: Props = $props();
</script>

<div class={inline ? 'space-y-1' : 'space-y-1.5'}>
	<label for={htmlFor} class="block text-xs font-medium text-muted-foreground">
		{label}
	</label>
	{@render children?.()}
	{#if error}
		<p class="text-xs text-destructive" role="alert">{error}</p>
	{:else if hint}
		<p class="text-xs text-muted-foreground">{hint}</p>
	{/if}
</div>
