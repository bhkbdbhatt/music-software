<script lang="ts">
	import { onMount } from 'svelte';
	import { dndzone, type DndEvent } from 'svelte-dnd-action';
	import { LayoutGrid, Plus, RotateCcw, X } from '@lucide/svelte';
	import { PANELS, PANEL_BY_ID, PANEL_IDS, defaultOrder } from '#lib/panels/registry.js';
	import type { PanelContext, PanelId } from '#lib/panels/types.js';
	import Button from '#lib/components/ui/Button.svelte';
	import Modal from '#lib/components/ui/Modal.svelte';
	import Toggle from '#lib/components/ui/Toggle.svelte';

	interface Props {
		context: PanelContext;
		storageKey?: string;
		class?: string;
	}

	let { context, storageKey = 'workspace', class: className = '' }: Props = $props();

	const STORAGE_PREFIX = 'sf-panels:';

	function loadOrder(key: string): PanelId[] {
		try {
			const raw = localStorage.getItem(STORAGE_PREFIX + key);
			if (!raw) return defaultOrder();
			const parsed: unknown = JSON.parse(raw);
			if (!Array.isArray(parsed)) return defaultOrder();
			const ids = parsed.filter((id): id is PanelId => PANEL_IDS.includes(id as PanelId));
			return ids.length > 0 ? ids : defaultOrder();
		} catch {
			return defaultOrder();
		}
	}

	let order = $state<PanelId[]>(defaultOrder());
	let pickerOpen = $state(false);

	onMount(() => {
		order = loadOrder(storageKey);
	});

	$effect(() => {
		try {
			localStorage.setItem(STORAGE_PREFIX + storageKey, JSON.stringify(order));
		} catch {
			// Storage may be unavailable (private mode); layout still works in-memory.
		}
	});

	type DndItem = { id: PanelId };
	const dndItems = $derived(order.map((id) => ({ id })));
	const definitions = $derived(
		order
			.map((id) => PANEL_BY_ID[id])
			.filter((panel): panel is NonNullable<typeof panel> => !!panel)
	);
	const hidden = $derived(PANELS.filter((panel) => !order.includes(panel.id)));

	function hide(id: PanelId): void {
		order = order.filter((existing) => existing !== id);
	}

	function show(id: PanelId): void {
		if (!order.includes(id)) order = [...order, id];
	}

	function toggle(id: PanelId, visible: boolean): void {
		if (visible) show(id);
		else hide(id);
	}

	function syncFromDnd(event: CustomEvent<DndEvent<DndItem>>): void {
		order = event.detail.items.map((item) => item.id).filter((id) => PANEL_IDS.includes(id));
	}

	function reset(): void {
		order = defaultOrder();
	}
</script>

<div class={className}>
	<div class="mb-3 flex items-center justify-between gap-2">
		<p class="text-xs text-muted-foreground">
			{definitions.length} panel{definitions.length === 1 ? '' : 's'} · drag to reorder
		</p>
		<div class="flex gap-2">
			<Button variant="outline" size="sm" onclick={reset} aria-label="Reset layout">
				<RotateCcw size={14} /> Reset
			</Button>
			<Button variant="outline" size="sm" onclick={() => (pickerOpen = true)}>
				<LayoutGrid size={14} /> Panels
				{#if hidden.length > 0}
					<span class="ml-1 rounded-full bg-muted px-1.5 text-[10px]">+{hidden.length}</span>
				{/if}
			</Button>
		</div>
	</div>

	<div
		class="grid grid-cols-1 gap-4 lg:grid-cols-2"
		use:dndzone={{ items: dndItems, flipDurationMs: 150 }}
		onconsider={syncFromDnd}
		onfinalize={syncFromDnd}
	>
		{#each definitions as panel (panel.id)}
			<section class="flex min-h-40 flex-col rounded-lg border border-border bg-card">
				<header class="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
					<span class="flex items-center gap-2 text-xs font-semibold tracking-tight">
						<panel.icon size={14} class="text-muted-foreground" />
						{panel.title}
					</span>
					<button
						type="button"
						aria-label="Hide {panel.title}"
						onclick={() => hide(panel.id)}
						class="cursor-pointer rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
					>
						<X size={13} />
					</button>
				</header>
				<div class="flex-1 p-3">
					<panel.component {context} />
				</div>
			</section>
		{/each}
	</div>

	{#if definitions.length === 0}
		<div
			class="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border px-6 py-10 text-center"
		>
			<p class="text-sm text-muted-foreground">Every panel is hidden.</p>
			<Button variant="outline" size="sm" onclick={() => (pickerOpen = true)}>
				<Plus size={14} /> Add a panel
			</Button>
		</div>
	{/if}
</div>

<Modal open={pickerOpen} title="Workspace panels" onclose={() => (pickerOpen = false)}>
	<div class="space-y-1">
		{#each PANELS as panel (panel.id)}
			<div class="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-muted">
				<span class="flex items-center gap-2 text-sm">
					<panel.icon size={15} class="text-muted-foreground" />
					{panel.title}
				</span>
				<Toggle
					checked={order.includes(panel.id)}
					aria-label="Show {panel.title}"
					onchange={(visible) => toggle(panel.id, visible)}
				/>
			</div>
		{/each}
	</div>
</Modal>
