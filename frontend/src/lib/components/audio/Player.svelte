<script lang="ts">
	import { onMount } from 'svelte';
	import { Pause, Play, Volume2, VolumeX } from '@lucide/svelte';
	import { formatTime } from '#lib/audio/format.js';
	import { loadPeaks } from '#lib/audio/decode.js';
	import type { Peaks } from '#lib/audio/peaks.js';
	import Button from '#lib/components/ui/Button.svelte';
	import Waveform from './Waveform.svelte';

	interface Marker {
		ms: number;
		label?: string;
	}

	interface Props {
		src: string;
		label?: string;
		peaks?: Peaks | null;
		durationMs?: number;
		markers?: Marker[];
		class?: string;
	}

	let {
		src,
		label,
		peaks = null,
		durationMs = 0,
		markers = [],
		class: className = ''
	}: Props = $props();

	let audio: HTMLAudioElement | undefined = $state();
	let playing = $state(false);
	let currentTimeMs = $state(0);
	let metadataMs = $state(0);
	let muted = $state(false);
	let loadedPeaks = $state<Peaks | null>(null);
	let peakError = $state('');

	const totalMs = $derived(durationMs || metadataMs);
	const peaksSource = $derived(peaks ?? loadedPeaks);

	onMount(() => {
		if (!peaks && src) {
			loadPeaks(src, 600)
				.then((loaded) => {
					loadedPeaks = loaded;
				})
				.catch(() => {
					peakError = 'Waveform unavailable';
				});
		}
	});

	async function toggle(): Promise<void> {
		if (!audio) return;
		if (playing) {
			audio.pause();
		} else {
			try {
				await audio.play();
			} catch {
				peakError = 'Playback blocked';
			}
		}
	}

	function seek(ms: number): void {
		if (!audio) return;
		audio.currentTime = ms / 1000;
		currentTimeMs = ms;
	}

	function onMeta(): void {
		if (audio && Number.isFinite(audio.duration)) {
			metadataMs = audio.duration * 1000;
		}
	}

	function onTime(): void {
		if (audio) currentTimeMs = audio.currentTime * 1000;
	}
</script>

<div class="rounded-lg border border-border bg-card p-3 {className}">
	<audio
		bind:this={audio}
		{src}
		preload="metadata"
		{muted}
		onplay={() => (playing = true)}
		onpause={() => (playing = false)}
		onended={() => (playing = false)}
		onloadedmetadata={onMeta}
		ontimeupdate={onTime}
	></audio>

	<div class="flex items-center gap-3">
		<Button
			variant="primary"
			size="sm"
			aria-label={playing ? 'Pause' : 'Play'}
			onclick={toggle}
			class="w-11 shrink-0"
		>
			{#if playing}
				<Pause size={15} />
			{:else}
				<Play size={15} />
			{/if}
		</Button>

		<div class="min-w-0 flex-1">
			{#if peaksSource}
				<Waveform
					peaks={peaksSource}
					durationMs={totalMs}
					progressMs={currentTimeMs}
					{markers}
					onseek={seek}
				/>
			{:else}
				<div
					class="flex h-16 items-center justify-center rounded-md border border-dashed border-border text-xs text-muted-foreground"
				>
					{peakError || 'Loading waveform…'}
				</div>
			{/if}
		</div>

		<Button
			variant="ghost"
			size="sm"
			aria-label={muted ? 'Unmute' : 'Mute'}
			onclick={() => (muted = !muted)}
			class="shrink-0"
		>
			{#if muted}
				<VolumeX size={15} />
			{:else}
				<Volume2 size={15} />
			{/if}
		</Button>

		<span class="shrink-0 text-xs text-muted-foreground tabular-nums">
			{formatTime(currentTimeMs)} / {formatTime(totalMs)}
		</span>
	</div>

	{#if label}
		<p class="mt-2 truncate text-xs text-muted-foreground">{label}</p>
	{/if}
</div>
