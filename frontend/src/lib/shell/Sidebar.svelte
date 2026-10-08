<script lang="ts">
	import { page } from '$app/state';
	import { NAV_GROUPS, APP_NAME, APP_ICON } from './nav';
	import ThemeToggle from './ThemeToggle.svelte';

	interface Props {
		open: boolean;
		onNavigate?: () => void;
	}

	let { open, onNavigate }: Props = $props();

	function isActive(href: string): boolean {
		const path = page.url.pathname;
		if (href === '/') return path === '/';
		return path === href || path.startsWith(`${href}/`);
	}
</script>

{#if open}
	<button
		class="fixed inset-0 z-40 bg-overlay md:hidden"
		aria-label="Close navigation"
		onclick={() => onNavigate?.()}
	></button>
{/if}

<aside
	class="fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-border bg-card transition-transform md:translate-x-0 {open
		? 'translate-x-0'
		: '-translate-x-full'}"
>
	<div class="flex items-center gap-2 border-b border-border px-4 py-3.5">
		<APP_ICON size={20} class="text-primary" />
		<span class="text-sm font-semibold tracking-tight">{APP_NAME}</span>
	</div>

	<nav class="flex-1 overflow-y-auto px-3 py-4">
		{#each NAV_GROUPS as group (group.label)}
			<div class="mb-5">
				<div
					class="mb-1.5 px-2 text-[11px] font-medium tracking-wider text-muted-foreground uppercase"
				>
					{group.label}
				</div>
				<ul class="space-y-0.5">
					{#each group.items as item (item.href)}
						<li>
							<a
								href={item.href}
								aria-current={isActive(item.href) ? 'page' : undefined}
								onclick={() => onNavigate?.()}
								class="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors {isActive(
									item.href
								)
									? 'bg-muted font-medium text-foreground'
									: 'text-muted-foreground hover:bg-muted hover:text-foreground'}"
							>
								<item.icon size={17} />
								{item.label}
							</a>
						</li>
					{/each}
				</ul>
			</div>
		{/each}
	</nav>

	<div class="border-t border-border px-3 py-3 md:hidden">
		<ThemeToggle />
	</div>
</aside>
