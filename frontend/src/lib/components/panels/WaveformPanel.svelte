<script lang="ts">
	import { AudioWaveform } from '@lucide/svelte';
	import type { PanelContext } from '#lib/panels/types.js';
	import Waveform from '#lib/components/audio/Waveform.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	interface Props {
		context: PanelContext;
	}

	let { context }: Props = $props();
</script>

{#if context.peaks && context.durationMs > 0}
	<Waveform peaks={context.peaks} durationMs={context.durationMs} height={90} />
{:else if context.loading}
	<div class="flex h-24 items-center justify-center gap-2 text-xs text-muted-foreground">
		<Spinner size={14} /> Loading waveform…
	</div>
{:else}
	<div
		class="flex h-24 flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border text-xs text-muted-foreground"
	>
		<AudioWaveform size={18} />
		{context.error || 'No audio yet'}
	</div>
{/if}
