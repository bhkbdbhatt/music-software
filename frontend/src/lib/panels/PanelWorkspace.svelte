<script lang="ts">
	import type { GenerationResponse, GenerationSpec } from '#lib/api/types.js';
	import { errorMessage } from '#lib/api/client.js';
	import { loadAudio } from '#lib/audio/decode.js';
	import type { Peaks } from '#lib/audio/peaks.js';
	import Compare from '#lib/components/audio/Compare.svelte';
	import WorkspaceGrid from './WorkspaceGrid.svelte';
	import { emptyContext } from './types.js';
	import type { PanelContext } from './types.js';

	interface Props {
		/** Spec shown before/alongside the response (the submitted copy). */
		spec?: GenerationSpec | null;
		response?: GenerationResponse | null;
		/** True while the page is still waiting on the job itself. */
		loading?: boolean;
		error?: string;
		storageKey?: string;
		class?: string;
	}

	let {
		spec = null,
		response = null,
		loading = false,
		error = '',
		storageKey = 'workspace',
		class: className = ''
	}: Props = $props();

	let context = $state<PanelContext>({ ...emptyContext() });
	let active = $state(0);
	let decoding = $state(false);
	let decodeError = $state('');
	let variantPeaks = $state<Record<number, Peaks>>({});

	const files = $derived(response?.files ?? []);
	const activeSpec = $derived(spec ?? response?.spec ?? null);
	const jobKey = $derived(response?.job_id ?? '');
	const activeIndex = $derived(Math.min(active, Math.max(0, files.length - 1)));
	const activeFile = $derived(files[activeIndex] ?? null);

	const variants = $derived(
		files.map((file, index) => ({
			id: String(index),
			label: `Variant ${index + 1}`,
			url: file.url,
			peaks: variantPeaks[index] ?? null,
			durationMs: file.duration_ms ?? 0
		}))
	);

	$effect(() => {
		context.spec = activeSpec;
		context.response = response;
		context.loading = loading || decoding;
		context.error = error || decodeError;
	});

	$effect(() => {
		void jobKey;
		active = 0;
		variantPeaks = {};
	});

	$effect(() => {
		const url = activeFile?.url ?? null;
		const index = activeIndex;
		if (!url) {
			context.url = null;
			context.peaks = null;
			context.samples = null;
			context.durationMs = 0;
			decoding = false;
			decodeError = '';
			return;
		}
		let cancelled = false;
		decoding = true;
		decodeError = '';
		context.url = url;
		loadAudio(url, 2048)
			.then((loaded) => {
				if (cancelled) return;
				context.peaks = loaded.peaks;
				context.durationMs = loaded.durationMs;
				context.sampleRate = loaded.sampleRate;
				context.samples = loaded.buffer.getChannelData(0);
				variantPeaks[index] = loaded.peaks;
				decoding = false;
			})
			.catch((cause: unknown) => {
				if (cancelled) return;
				decodeError = errorMessage(cause);
				decoding = false;
			});
		return () => {
			cancelled = true;
		};
	});
</script>

{#if variants.length > 1}
	<Compare {variants} bind:active class="mb-4" />
{/if}
<WorkspaceGrid {context} {storageKey} class={className} />
