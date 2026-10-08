<script lang="ts">
	import { cn } from '#lib/utils/cn.js';

	interface Props {
		min?: number;
		max?: number;
		step?: number;
		value?: number;
		disabled?: boolean;
		format?: (value: number) => string;
		class?: string;
		oninput?: (event: Event) => void;
	}

	let {
		min = 0,
		max = 100,
		step = 1,
		value = $bindable(0),
		disabled = false,
		format = (v) => `${v}`,
		class: className = '',
		oninput
	}: Props = $props();

	const display = $derived(format(value));
</script>

<div class={cn('flex items-center gap-3', className)}>
	<input
		type="range"
		{min}
		{max}
		{step}
		{disabled}
		bind:value
		oninput={(event) => oninput?.(event)}
		class="w-full cursor-pointer accent-primary disabled:cursor-not-allowed disabled:opacity-50"
	/>
	<span class="w-18 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
		{display}
	</span>
</div>
