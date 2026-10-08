<script lang="ts">
	import './layout.css';
	import favicon from '#lib/assets/favicon.svg';
	import type { LayoutProps } from './$types';
	import Sidebar from '#lib/shell/Sidebar.svelte';
	import Topbar from '#lib/shell/Topbar.svelte';

	let { children }: LayoutProps = $props();

	let sidebarOpen = $state(false);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<div class="flex min-h-dvh bg-background text-foreground">
	<Sidebar open={sidebarOpen} onNavigate={() => (sidebarOpen = false)} />

	<div class="flex min-w-0 flex-1 flex-col md:pl-64">
		<Topbar onMenuToggle={() => (sidebarOpen = !sidebarOpen)} />
		<main class="min-w-0 flex-1 p-4 md:p-6">
			{@render children()}
		</main>
	</div>
</div>
