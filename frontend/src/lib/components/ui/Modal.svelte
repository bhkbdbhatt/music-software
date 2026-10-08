<script lang="ts">
	import type { Snippet } from 'svelte';
	import { X } from '@lucide/svelte';
	import { cn } from '#lib/utils/cn.js';

	interface Props {
		open?: boolean;
		title: string;
		size?: 'sm' | 'md' | 'lg';
		class?: string;
		onclose: () => void;
		children?: Snippet;
		footer?: Snippet;
	}

	let {
		open = $bindable(false),
		title,
		size = 'md',
		class: className = '',
		onclose,
		children,
		footer
	}: Props = $props();

	$effect(() => {
		if (!open) return;
		const onKeydown = (event: KeyboardEvent) => {
			if (event.key === 'Escape') onclose();
		};
		document.addEventListener('keydown', onKeydown);
		return () => document.removeEventListener('keydown', onKeydown);
	});

	const SIZES = { sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-3xl' } as const;
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-overlay p-4 pt-[10vh]"
		role="presentation"
		onclick={(event) => {
			if (event.target === event.currentTarget) onclose();
		}}
	>
		<div
			role="dialog"
			aria-modal="true"
			aria-label={title}
			class={cn(
				'w-full rounded-lg border border-border bg-card shadow-xl',
				'focus-visible:outline-none',
				SIZES[size],
				className
			)}
		>
			<div class="flex items-center justify-between border-b border-border px-4 py-3">
				<h2 class="text-sm font-semibold tracking-tight">{title}</h2>
				<button
					type="button"
					onclick={onclose}
					aria-label="Close dialog"
					class="cursor-pointer rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
				>
					<X size={16} />
				</button>
			</div>
			<div class="px-4 py-4">
				{@render children?.()}
			</div>
			{#if footer}
				<div class="flex justify-end gap-2 border-t border-border px-4 py-3">
					{@render footer()}
				</div>
			{/if}
		</div>
	</div>
{/if}
