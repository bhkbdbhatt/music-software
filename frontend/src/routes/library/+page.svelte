<script lang="ts">
	import { onMount } from 'svelte';
	import { Download, Library as LibraryIcon, Play, Search } from '@lucide/svelte';
	import { APP_NAME } from '#lib/shell/nav.js';
	import { api, errorMessage } from '#lib/api/client.js';
	import { loadPeaks } from '#lib/audio/decode.js';
	import { formatTime } from '#lib/audio/format.js';
	import type { Peaks } from '#lib/audio/peaks.js';
	import type { JobList } from '#lib/api/types.js';
	import Player from '#lib/components/audio/Player.svelte';
	import Button from '#lib/components/ui/Button.svelte';
	import EmptyState from '#lib/components/ui/EmptyState.svelte';
	import Input from '#lib/components/ui/Input.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	interface LibraryEntry {
		jobId: string;
		variant: number;
		url: string;
		durationMs: number | null | undefined;
		peakDb: number | null | undefined;
		category: string;
		genre: string;
		key: string;
		createdAt: string;
	}

	let entries = $state<LibraryEntry[]>([]);
	let loading = $state(true);
	let loadError = $state('');
	let query = $state('');
	let selectedUrl = $state('');
	let selectedPeaks = $state<Peaks | null>(null);
	let peaksLoading = $state(false);

	const filtered = $derived(
		query.trim().length === 0
			? entries
			: entries.filter((entry) => {
					const haystack =
						`${entry.category} ${entry.genre} ${entry.key} ${entry.jobId}`.toLowerCase();
					return haystack.includes(query.trim().toLowerCase());
				})
	);
	const selected = $derived(entries.find((entry) => entry.url === selectedUrl) ?? null);

	async function refresh(): Promise<void> {
		loading = true;
		loadError = '';
		try {
			const [complete, warnings] = await Promise.all([
				api.listJobs({ limit: 100, status: 'complete' }),
				api.listJobs({ limit: 100, status: 'complete_with_warnings' })
			]);
			entries = [...merge(complete), ...merge(warnings)];
		} catch (cause) {
			loadError = errorMessage(cause);
		} finally {
			loading = false;
		}
	}

	function merge(list: JobList): LibraryEntry[] {
		const result: LibraryEntry[] = [];
		for (const item of list.items ?? []) {
			(item.files ?? []).forEach((file, index) => {
				result.push({
					jobId: item.job_id,
					variant: index,
					url: file.url,
					durationMs: file.duration_ms,
					peakDb: file.peak_db,
					category: item.spec?.category ?? 'unknown',
					genre: item.spec?.genre ?? '',
					key: item.spec?.key ?? '',
					createdAt: item.created_at
				});
			});
		}
		return result;
	}

	onMount(() => {
		void refresh();
	});

	$effect(() => {
		const url = selectedUrl;
		if (!url) {
			selectedPeaks = null;
			return;
		}
		let cancelled = false;
		peaksLoading = true;
		loadPeaks(url, 640)
			.then((peaks) => {
				if (cancelled) return;
				selectedPeaks = peaks;
				peaksLoading = false;
			})
			.catch(() => {
				if (cancelled) return;
				selectedPeaks = null;
				peaksLoading = false;
			});
		return () => {
			cancelled = true;
		};
	});
</script>

<svelte:head><title>Library — {APP_NAME}</title></svelte:head>

<section class="mb-6">
	<h2 class="text-lg font-semibold tracking-tight">Library</h2>
	<p class="mt-1 text-sm text-muted-foreground">Generated samples, searchable and playable.</p>
</section>

<div class="mb-4 flex flex-wrap items-center gap-3">
	<div class="relative min-w-52 flex-1">
		<Search
			size={14}
			class="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground"
		/>
		<Input
			type="search"
			placeholder="Search category, genre, key, or job id."
			class="pl-8"
			value={query}
			oninput={(event) => (query = (event.currentTarget as HTMLInputElement).value)}
		/>
	</div>
	<Button variant="outline" onclick={() => void refresh()} {loading}>Refresh</Button>
	<span class="text-xs text-muted-foreground">{filtered.length} samples</span>
</div>

{#if loadError}
	<div
		class="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
		role="alert"
	>
		{loadError}
	</div>
{/if}

{#if selected}
	<div class="mb-4">
		<Player
			src={selected.url}
			peaks={selectedPeaks}
			durationMs={selected.durationMs ?? 0}
			label="{selected.category} · {selected.jobId} · variant {selected.variant + 1}"
		/>
		{#if peaksLoading}
			<p class="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
				<Spinner size={12} /> Loading waveform…
			</p>
		{/if}
	</div>
{/if}

{#if loading && entries.length === 0}
	<div class="flex items-center gap-2 text-sm text-muted-foreground">
		<Spinner size={14} /> Loading library…
	</div>
{:else if entries.length === 0}
	<EmptyState
		icon={LibraryIcon}
		title="Nothing in the library yet"
		description="Completed jobs appear here as playable samples."
	>
		<a href="/generate" class="text-sm text-primary hover:underline">Generate your first sample</a>
	</EmptyState>
{:else if filtered.length === 0}
	<EmptyState title="No matches" description="Try a different search term." />
{:else}
	<ul class="divide-y divide-border rounded-lg border border-border bg-card">
		{#each filtered as entry (`${entry.jobId}:${entry.variant}`)}
			<li class="flex flex-wrap items-center gap-3 px-3 py-2">
				<button
					type="button"
					class="min-w-0 flex-1 text-left"
					onclick={() => (selectedUrl = entry.url)}
				>
					<span class="text-sm font-medium">{entry.category}</span>
					<span class="ml-2 text-xs text-muted-foreground">
						{entry.genre}{entry.key ? ` · ${entry.key}` : ''}
					</span>
					<span class="block truncate font-mono text-xs text-muted-foreground">
						{entry.jobId} · variant {entry.variant + 1}
					</span>
				</button>
				<span class="text-xs text-muted-foreground tabular-nums">
					{entry.durationMs != null ? formatTime(entry.durationMs) : '—'}
					{entry.peakDb != null ? ` · ${entry.peakDb.toFixed(1)} dB` : ''}
				</span>
				<button
					type="button"
					class="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
					aria-label="Play {entry.category} from {entry.jobId}"
					onclick={() => (selectedUrl = entry.url)}
				>
					<Play size={15} />
				</button>
				<a
					href={entry.url}
					download="{entry.jobId}-{entry.variant + 1}.wav"
					aria-label="Download {entry.jobId} variant {entry.variant + 1}"
					class="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
				>
					<Download size={15} />
				</a>
			</li>
		{/each}
	</ul>
{/if}
