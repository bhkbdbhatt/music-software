<script lang="ts">
	import type { PanelContext } from '#lib/panels/types.js';
	import Badge from '#lib/components/ui/Badge.svelte';
	import EmptyState from '#lib/components/ui/EmptyState.svelte';

	interface Props {
		context: PanelContext;
	}

	let { context }: Props = $props();

	interface Row {
		label: string;
		target: string;
		measured: string;
		ok: boolean | undefined;
	}

	const rows = $derived.by((): Row[] => {
		const spec = context.spec;
		const response = context.response;
		if (!spec || !response) return [];
		const file = (response.files ?? [])[0];
		const analysis = file?.spectral_analysis ?? null;
		const met = response.constraints_met ?? {};
		const tol = spec.tolerances;
		const [fMin, fMax] = spec.fundamental_hz;
		const verdict = (key: string): boolean | undefined => (key in met ? met[key] : undefined);
		const show = (value: number | null | undefined, digits = 1): string =>
			value === null || value === undefined ? '—' : String(Number(value.toFixed(digits)));

		return [
			{
				label: 'Duration',
				target: `${spec.type === 'loop' ? 'derived' : `${spec.duration_ms} ms`} (±${(tol?.duration_pct ?? 0.02) * 100}%)`,
				measured: show(file?.duration_ms, 0),
				ok: verdict('duration_ms')
			},
			{
				label: 'Peak',
				target: `${spec.peak_db} dBFS (±${tol?.peak_db ?? 0.5})`,
				measured: show(file?.peak_db),
				ok: verdict('peak_db')
			},
			{
				label: 'Fundamental',
				target: `${fMin}–${fMax} Hz (±${tol?.fundamental_hz ?? 5})`,
				measured: analysis ? `${show(analysis.fundamental_detected_hz)} Hz` : '—',
				ok: verdict('fundamental_hz')
			},
			{
				label: 'Ceiling leakage',
				target: `≤ ${tol?.ceiling_violation_db ?? -40} dB`,
				measured: analysis ? `${show(analysis.ceiling_violation_db)} dB` : '—',
				ok: verdict('spectral_ceiling_hz')
			},
			{
				label: 'Floor slope',
				target: `≤ ${tol?.floor_slope_db_per_oct ?? -12} dB/oct`,
				measured: analysis ? `${show(analysis.floor_slope_db_per_oct)} dB/oct` : '—',
				ok: verdict('spectral_floor_hz')
			},
			{
				label: 'Tilt',
				target: `${spec.spectral_tilt_db_per_octave} dB/oct (±${tol?.tilt_db_per_octave ?? 1.5})`,
				measured: analysis ? `${show(analysis.tilt_measured_db_per_octave)} dB/oct` : '—',
				ok: verdict('spectral_tilt_db_per_octave')
			},
			{
				label: 'Attack',
				target: `${spec.attack_ms} ms (±${tol?.attack_ms ?? 2})`,
				measured: analysis ? `${show(analysis.attack_measured_ms)} ms` : '—',
				ok: verdict('attack_ms')
			}
		];
	});
</script>

{#if rows.length === 0}
	<EmptyState title="Nothing measured yet" description="Verdicts appear when analysis completes." />
{:else}
	<div class="space-y-1.5">
		{#each rows as row (row.label)}
			<div
				class="grid grid-cols-[1fr_auto_auto] items-center gap-3 rounded-md border border-border px-3 py-2"
			>
				<div class="min-w-0">
					<p class="text-xs font-medium">{row.label}</p>
					<p class="truncate text-[11px] text-muted-foreground">target {row.target}</p>
				</div>
				<p class="text-xs text-muted-foreground tabular-nums">{row.measured}</p>
				{#if row.ok === undefined}
					<Badge tone="neutral">pending</Badge>
				{:else if row.ok}
					<Badge tone="success">met</Badge>
				{:else}
					<Badge tone="danger">missed</Badge>
				{/if}
			</div>
		{/each}
	</div>
{/if}
