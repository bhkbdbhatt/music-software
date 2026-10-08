<script lang="ts">
	import type { PanelContext } from '#lib/panels/types.js';
	import SpecSummary from './SpecSummary.svelte';
	import EmptyState from '#lib/components/ui/EmptyState.svelte';

	interface Props {
		context: PanelContext;
	}

	let { context }: Props = $props();
</script>

{#if context.spec}
	<SpecSummary spec={context.spec} />
{:else}
	<EmptyState title="No spec" description="The generation spec appears here." />
{/if}
