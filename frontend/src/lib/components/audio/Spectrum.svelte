<script lang="ts">
	import { scaleLog } from 'd3';
	import { formatHz } from '#lib/audio/format.js';
	import { spectrumAt } from '#lib/audio/fft.js';

	interface Constraints {
		floorHz: number;
		ceilingHz: number;
		fundamental?: [number, number];
	}

	interface Props {
		samples?: Float32Array | null;
		sampleRate?: number;
		fftSize?: number;
		constraints?: Constraints | null;
		height?: number;
		class?: string;
	}

	let {
		samples = null,
		sampleRate = 44100,
		fftSize = 4096,
		constraints = null,
		height = 160,
		class: className = ''
	}: Props = $props();

	const TICKS = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];

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
		const success = cssVar('--color-success') || '#4ade80';
		const destructive = cssVar('--color-destructive') || '#f87171';
		const overlay = cssVar('--color-overlay') || 'rgba(0,0,0,0.5)';

		const axisHeight = 22;
		const plotHeight = height - axisHeight;
		ctx.clearRect(0, 0, cssWidth, height);

		const x = scaleLog().domain([20, 20000]).range([0, cssWidth]);
		const minDb = -90;
		const maxDb = 0;
		const y = (db: number) =>
			plotHeight - ((Math.max(minDb, Math.min(maxDb, db)) - minDb) / (maxDb - minDb)) * plotHeight;

		// Decade gridlines.
		ctx.strokeStyle = border;
		ctx.globalAlpha = 0.5;
		for (const freq of [100, 1000, 10000]) {
			const gx = x(freq);
			ctx.beginPath();
			ctx.moveTo(gx, 0);
			ctx.lineTo(gx, plotHeight);
			ctx.stroke();
		}
		ctx.globalAlpha = 1;

		if (constraints) {
			if (constraints.fundamental) {
				const x0 = x(Math.max(20, constraints.fundamental[0]));
				const x1 = x(Math.min(20000, constraints.fundamental[1]));
				ctx.fillStyle = overlay;
				ctx.fillRect(x0, 0, Math.max(1, x1 - x0), plotHeight);
			}
			const lines: [number, string][] = [
				[constraints.floorHz, success],
				[constraints.ceilingHz, destructive]
			];
			for (const [freq, color] of lines) {
				const gx = x(Math.max(20, Math.min(20000, freq)));
				ctx.strokeStyle = color;
				ctx.setLineDash([4, 3]);
				ctx.beginPath();
				ctx.moveTo(gx, 0);
				ctx.lineTo(gx, plotHeight);
				ctx.stroke();
				ctx.setLineDash([]);
			}
		}

		if (samples && samples.length > fftSize) {
			const offset = Math.max(0, Math.floor(samples.length / 2) - fftSize / 2);
			const magnitudes = spectrumAt(samples, offset, fftSize);
			const nyquist = sampleRate / 2;
			ctx.strokeStyle = primary;
			ctx.beginPath();
			let started = false;
			for (let i = 1; i < magnitudes.length; i++) {
				const freq = (i / magnitudes.length) * nyquist;
				if (freq < 20) continue;
				if (freq > 20000) break;
				const db = 20 * Math.log10(Math.max(1e-7, magnitudes[i]));
				const px = x(freq);
				const py = y(db);
				if (!started) {
					ctx.moveTo(px, py);
					started = true;
				} else {
					ctx.lineTo(px, py);
				}
			}
			ctx.stroke();
		} else {
			ctx.fillStyle = muted;
			ctx.font = '11px sans-serif';
			ctx.fillText('No spectrum', 8, plotHeight / 2);
		}

		// Frequency axis.
		ctx.fillStyle = muted;
		ctx.font = '10px sans-serif';
		ctx.strokeStyle = border;
		ctx.beginPath();
		ctx.moveTo(0, plotHeight + 0.5);
		ctx.lineTo(cssWidth, plotHeight + 0.5);
		ctx.stroke();
		for (const freq of TICKS) {
			const gx = x(freq);
			ctx.beginPath();
			ctx.moveTo(gx, plotHeight);
			ctx.lineTo(gx, plotHeight + 4);
			ctx.stroke();
			const label = formatHz(freq);
			const measured = ctx.measureText(label).width;
			ctx.fillText(
				label,
				Math.min(cssWidth - measured, Math.max(0, gx - measured / 2)),
				height - 6
			);
		}
	}

	$effect(() => {
		void samples;
		void constraints;
		void sampleRate;
		void fftSize;
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
</script>

<!-- svelte-ignore a11y_no_interactive_element_to_noninteractive_role -->
<canvas
	bind:this={canvas}
	class="block w-full {className}"
	style="height: {height}px"
	role="img"
	aria-label="Spectrum"
></canvas>
