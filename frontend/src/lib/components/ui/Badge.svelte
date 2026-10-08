<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '#lib/utils/cn.js';

	type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

	interface Props {
		tone?: Tone;
		class?: string;
		children?: Snippet;
	}

	let { tone = 'neutral', class: className = '', children }: Props = $props();

	const TONES: Record<Tone, string> = {
		neutral: 'bg-muted text-muted-foreground',
		success: 'bg-success/15 text-success',
		warning: 'bg-warning/15 text-warning',
		danger: 'bg-destructive/15 text-destructive',
		info: 'bg-primary/15 text-primary'
	};
</script>

<span
	class={cn(
		'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap',
		TONES[tone],
		className
	)}
>
	{@render children?.()}
</span>
