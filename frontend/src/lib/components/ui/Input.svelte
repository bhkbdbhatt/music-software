<script lang="ts">
	import { cn } from '#lib/utils/cn.js';

	interface Props {
		type?: 'text' | 'number' | 'search' | 'password';
		value?: string | number;
		placeholder?: string;
		name?: string;
		id?: string;
		disabled?: boolean;
		min?: number;
		max?: number;
		step?: number;
		invalid?: boolean;
		list?: string;
		class?: string;
		oninput?: (event: Event) => void;
		onchange?: (event: Event) => void;
	}

	let {
		type = 'text',
		value = $bindable(''),
		placeholder,
		name,
		id,
		disabled = false,
		min,
		max,
		step,
		invalid = false,
		list,
		class: className = '',
		oninput,
		onchange
	}: Props = $props();
</script>

<input
	{type}
	{name}
	{id}
	{placeholder}
	{disabled}
	{min}
	{max}
	{step}
	{list}
	bind:value
	aria-invalid={invalid || undefined}
	oninput={(event) => oninput?.(event)}
	onchange={(event) => onchange?.(event)}
	class={cn(
		'h-9 w-full rounded-md border bg-card px-3 text-sm text-foreground transition-colors',
		'placeholder:text-muted-foreground',
		'focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary/60',
		'disabled:cursor-not-allowed disabled:opacity-50',
		invalid ? 'border-destructive' : 'border-border',
		className
	)}
/>
