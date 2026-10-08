<script lang="ts">
	import { ChevronDown } from '@lucide/svelte';
	import { cn } from '#lib/utils/cn.js';

	interface Option {
		value: string;
		label: string;
	}

	interface Props {
		options: Option[];
		value?: string;
		name?: string;
		id?: string;
		disabled?: boolean;
		class?: string;
		onchange?: (event: Event) => void;
	}

	let {
		options,
		value = $bindable(''),
		name,
		id,
		disabled = false,
		class: className = '',
		onchange
	}: Props = $props();
</script>

<div class={cn('relative', className)}>
	<select
		{name}
		{id}
		{disabled}
		bind:value
		onchange={(event) => onchange?.(event)}
		class="h-9 w-full appearance-none rounded-md border border-border bg-card pr-8 pl-3 text-sm text-foreground transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary/60 disabled:cursor-not-allowed disabled:opacity-50"
	>
		{#each options as option (option.value)}
			<option value={option.value}>{option.label}</option>
		{/each}
	</select>
	<ChevronDown
		size={14}
		class="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-muted-foreground"
	/>
</div>
