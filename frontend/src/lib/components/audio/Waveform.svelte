<script lang="ts">
	import type { Peaks } from '#lib/audio/peaks.js';

	interface Marker {
		ms: number;
		label?: string;
	}

	interface Props {
		peaks?: Peaks | null;
		durationMs?: number;
		progressMs?: number;
		markers?: Marker[];
		height?: number;
		class?: string;
		onseek?: (ms: number) => void;
	}

	let {
		peaks = null,
		durationMs = 0,
		progressMs = 0,
		markers = [],
		height = 64,
		class: className = '',
		onseek
	}: Props = $props();

	let canvas: HTMLCanvasElement | undefined = $state();

	function cssVar(name: string): string {
		return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
	}

	function draw(): void {
		if (!canvas) return;
		const { width: cssWidth } = canvas.getBoundingClientRect();
		if (cssWidth === 0) return;
		const dpr = window.devicePixelRatio || 1;
		canvas.width = Math.round(cssWidth * dpr);
		canvas.height = Math.round(height * dpr);
		const ctx = canvas.getContext('2d');
		if (!ctx) return;
		ctx.scale(dpr, dpr);

		const primary = cssVar('--color-primary') || '#5eead4';
		const muted = cssVar('--color-muted-foreground') || '#888';
		const border = cssVar('--color-border') || '#444';
		const warning = cssVar('--color-warning') || '#facc15';

		ctx.clearRect(0, 0, cssWidth, height);
		const mid = height / 2;

		ctx.strokeStyle = border;
		ctx.beginPath();
		ctx.moveTo(0, mid + 0.5);
		ctx.lineTo(cssWidth, mid + 0.5);
		ctx.stroke();

		if (peaks && durationMs > 0) {
			const buckets = peaks.min.length;
			const playedX = Math.min(cssWidth, ((progressMs ?? 0) / durationMs) * cssWidth);
			const step = cssWidth / buckets;
			for (let i = 0; i < buckets; i++) {
				const x = i * step;
				const lo = Math.max(-1, Math.min(1, peaks.min[i]));
				const hi = Math.max(-1, Math.min(1, peaks.max[i]));
				const yTop = mid - hi * (mid - 2);
				const yBottom = mid - lo * (mid - 2);
				ctx.strokeStyle = x <= playedX ? primary : muted;
				ctx.globalAlpha = x <= playedX ? 1 : 0.55;
				ctx.beginPath();
				ctx.moveTo(x, yTop);
				ctx.lineTo(x, Math.max(yBottom, yTop + 1));
				ctx.stroke();
			}
			ctx.globalAlpha = 1;

			if (playedX > 0) {
				ctx.strokeStyle = primary;
				ctx.beginPath();
				ctx.moveTo(playedX + 0.5, 0);
				ctx.lineTo(playedX + 0.5, height);
				ctx.stroke();
			}
		}

		for (const marker of markers) {
			if (durationMs <= 0) continue;
			const x = (marker.ms / durationMs) * cssWidth;
			if (x < 0 || x > cssWidth) continue;
			ctx.strokeStyle = warning;
			ctx.setLineDash([3, 3]);
			ctx.beginPath();
			ctx.moveTo(x + 0.5, 0);
			ctx.lineTo(x + 0.5, height);
			ctx.stroke();
			ctx.setLineDash([]);
			if (marker.label) {
				ctx.fillStyle = warning;
				ctx.font = '10px sans-serif';
				ctx.fillText(marker.label, x + 3, 10);
			}
		}
	}

	$effect(() => {
		void peaks;
		void progressMs;
		void durationMs;
		void markers;
		draw();
	});

	$effect(() => {
		if (!canvas) return;
		const observer = new ResizeObserver(() => draw());
		observer.observe(canvas);
		const themeObserver = new MutationObserver(() => draw());
		themeObserver.observe(document.documentElement, {
			attributes: true,
			attributeFilter: ['data-theme']
		});
		return () => {
			observer.disconnect();
			themeObserver.disconnect();
		};
	});

	function handleClick(event: MouseEvent): void {
		if (!onseek || durationMs <= 0) return;
		const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
		const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
		onseek(ratio * durationMs);
	}
</script>

<!-- svelte-ignore a11y_no_interactive_element_to_noninteractive_role -->
<canvas
	bind:this={canvas}
	class="block w-full cursor-pointer {className}"
	style="height: {height}px"
	role="img"
	aria-label="Waveform"
	onclick={handleClick}
></canvas>
