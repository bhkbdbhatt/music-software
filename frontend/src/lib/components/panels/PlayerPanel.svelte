<script lang="ts">
	import type { PanelContext } from '#lib/panels/types.js';
	import Player from '#lib/components/audio/Player.svelte';
	import EmptyState from '#lib/components/ui/EmptyState.svelte';
	import { FileAudio } from '@lucide/svelte';

	interface Props {
		context: PanelContext;
	}

	let { context }: Props = $props();
</script>

{#if context.url}
	<Player
		src={context.url}
		peaks={context.peaks}
		durationMs={context.durationMs}
		label={context.url}
	/>
{:else}
	<EmptyState
		icon={FileAudio}
		title="No file selected"
		description="A rendered variant appears here once the job produces audio."
	/>
{/if}
