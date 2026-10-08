<script lang="ts">
	import type { Snippet } from 'svelte';
	import { LoaderCircle } from '@lucide/svelte';
	import { cn } from '#lib/utils/cn.js';

	type Variant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'destructive';
	type Size = 'sm' | 'md' | 'lg';

	interface Props {
		variant?: Variant;
		size?: Size;
		loading?: boolean;
		disabled?: boolean;
		type?: 'button' | 'submit' | 'reset';
		class?: string;
		'aria-label'?: string;
		'aria-pressed'?: boolean;
		title?: string;
		onclick?: (event: MouseEvent) => void;
		children?: Snippet;
	}

	let {
		variant = 'primary',
		size = 'md',
		loading = false,
		disabled = false,
		type = 'button',
		class: className = '',
		'aria-label': ariaLabel,
		'aria-pressed': ariaPressed,
		title,
		onclick,
		children
	}: Props = $props();

	const VARIANTS: Record<Variant, string> = {
		primary: 'bg-primary text-primary-foreground hover:opacity-90',
		secondary: 'bg-muted text-foreground hover:bg-muted/70',
		outline: 'border border-border bg-card text-foreground hover:bg-muted',
		ghost: 'text-foreground hover:bg-muted',
		destructive: 'bg-destructive text-white hover:opacity-90'
	};

	const SIZES: Record<Size, string> = {
		sm: 'h-8 px-2.5 text-xs',
		md: 'h-9 px-3.5 text-sm',
		lg: 'h-10 px-5 text-sm'
	};
</script>

<button
	{type}
	disabled={disabled || loading}
	aria-label={ariaLabel}
	aria-pressed={ariaPressed}
	aria-busy={loading || undefined}
	{title}
	onclick={(event) => onclick?.(event)}
	class={cn(
		'inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-md font-medium transition-colors select-none',
		'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
		'disabled:pointer-events-none disabled:opacity-50',
		VARIANTS[variant],
		SIZES[size],
		className
	)}
>
	{#if loading}
		<LoaderCircle size={15} class="animate-spin" />
	{/if}
	{@render children?.()}
</button>
