<script lang="ts">
	import type { PanelContext } from '#lib/panels/types.js';
	import Spectrum from '#lib/components/audio/Spectrum.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	interface Props {
		context: PanelContext;
	}

	let { context }: Props = $props();

	const constraints = $derived(
		context.spec
			? {
					floorHz: context.spec.spectral_floor_hz,
					ceilingHz: context.spec.spectral_ceiling_hz,
					fundamental: context.spec.fundamental_hz as [number, number]
				}
			: null
	);
</script>

{#if context.samples}
	<Spectrum samples={context.samples} sampleRate={context.sampleRate} {constraints} height={180} />
{:else if context.loading}
	<div class="flex h-[180px] items-center justify-center gap-2 text-xs text-muted-foreground">
		<Spinner size={14} /> Decoding spectrum…
	</div>
{:else}
	<div
		class="flex h-[180px] items-center justify-center rounded-md border border-dashed border-border text-xs text-muted-foreground"
	>
		{context.error || 'Decode a variant to see its spectrum'}
	</div>
{/if}
