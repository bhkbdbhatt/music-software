<script lang="ts">
	import type { PanelContext } from '#lib/panels/types.js';

	interface Props {
		context: PanelContext;
	}

	let { context }: Props = $props();

	const json = $derived(
		JSON.stringify({ spec: context.spec, response: context.response }, null, 2)
	);
</script>

<pre
	class="max-h-96 overflow-auto rounded-md border border-border bg-muted/30 p-3 font-mono text-[11px] leading-relaxed">{json}</pre>
