<script lang="ts">
	import { Pause, Play } from '@lucide/svelte';
	import { formatTime } from '#lib/audio/format.js';
	import type { Peaks } from '#lib/audio/peaks.js';
	import Button from '#lib/components/ui/Button.svelte';
	import Waveform from './Waveform.svelte';

	interface Variant {
		id: string;
		label: string;
		url: string;
		peaks?: Peaks | null;
		durationMs?: number;
	}

	interface Marker {
		ms: number;
		label?: string;
	}

	interface Props {
		variants: Variant[];
		active?: number;
		markers?: Marker[];
		class?: string;
	}

	let { variants, active = $bindable(0), markers = [], class: className = '' }: Props = $props();

	let audio: HTMLAudioElement | undefined = $state();
	let playing = $state(false);
	let currentTimeMs = $state(0);
	let totalMs = $state(0);
	let resumeAfterSwitch = false;

	const current = $derived(variants[active]);
	const currentDuration = $derived(current?.durationMs || totalMs || 0);

	function onMeta(): void {
		if (audio && Number.isFinite(audio.duration)) {
			totalMs = audio.duration * 1000;
			if (resumeAfterSwitch) {
				resumeAfterSwitch = false;
				void audio.play().catch(() => undefined);
			}
		}
	}

	function onTime(): void {
		if (audio) currentTimeMs = audio.currentTime * 1000;
	}

	async function toggle(): Promise<void> {
		if (!audio) return;
		if (playing) {
			audio.pause();
		} else {
			try {
				await audio.play();
			} catch {
				// Autoplay/gesture policy: ignore, UI stays in paused state.
			}
		}
	}

	function selectVariant(index: number): void {
		const element = audio;
		if (index === active || !element) return;
		const keepPosition = element.currentTime;
		const wasPlaying = playing;
		active = index;
		resumeAfterSwitch = wasPlaying;
		// Wait for the new src to load, then restore position (handled in onMeta).
		element.addEventListener(
			'loadedmetadata',
			() => {
				element.currentTime = keepPosition;
			},
			{ once: true }
		);
	}

	function seek(ms: number): void {
		if (!audio) return;
		audio.currentTime = ms / 1000;
		currentTimeMs = ms;
	}
</script>

<div class="rounded-lg border border-border bg-card p-3 {className}">
	<audio
		bind:this={audio}
		src={current?.url}
		preload="metadata"
		onplay={() => (playing = true)}
		onpause={() => (playing = false)}
		onended={() => (playing = false)}
		onloadedmetadata={onMeta}
		ontimeupdate={onTime}
	></audio>

	<div class="mb-2 flex items-center justify-between gap-2">
		<div class="flex gap-1">
			{#each variants as variant, index (variant.id)}
				<Button
					variant={index === active ? 'primary' : 'ghost'}
					size="sm"
					onclick={() => selectVariant(index)}
					aria-pressed={index === active}
				>
					{variant.label}
				</Button>
			{/each}
		</div>
		<span class="text-xs text-muted-foreground tabular-nums">
			{formatTime(currentTimeMs)} / {formatTime(currentDuration)}
		</span>
	</div>

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
			<Waveform
				peaks={current?.peaks ?? null}
				durationMs={currentDuration}
				progressMs={currentTimeMs}
				{markers}
				onseek={seek}
			/>
		</div>
	</div>
</div>
