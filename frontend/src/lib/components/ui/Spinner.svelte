<script lang="ts">
	import { LoaderCircle } from '@lucide/svelte';
	import { cn } from '#lib/utils/cn.js';

	interface Props {
		size?: number;
		class?: string;
	}

	let { size = 16, class: className = '' }: Props = $props();
</script>

<span role="status" aria-label="Loading" class={cn('inline-flex', className)}>
	<LoaderCircle {size} class="animate-spin" />
</span>
