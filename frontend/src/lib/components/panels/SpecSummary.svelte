<script lang="ts">
	import { SPEC_SECTIONS } from '#lib/spec/fields.js';
	import { getPath } from '#lib/spec/spec.js';
	import type { GenerationSpec } from '#lib/spec/types.js';

	interface Props {
		spec: GenerationSpec;
	}

	let { spec }: Props = $props();

	function formatValue(sectionId: string, path: string): string {
		const field = SPEC_SECTIONS.find((s) => s.id === sectionId)?.fields.find(
			(f) => f.path === path
		);
		if (!field) return '—';
		const raw = getPath(spec, path);
		if (raw === null || raw === undefined || raw === '') return '—';

		switch (field.control) {
			case 'select': {
				const option = field.options?.find((o) => String(o.value) === String(raw));
				return option ? option.label : String(raw);
			}
			case 'boolean':
				return raw ? 'Yes' : 'No';
			case 'range2': {
				const [lo, hi] = raw as [number, number];
				return `${lo}–${hi}${field.unit ? ` ${field.unit}` : ''}`;
			}
			case 'combobox':
			case 'text':
				return String(raw);
			default: {
				const num = Number(raw);
				const text = Number.isInteger(num) ? String(num) : String(Number(num.toFixed(3)));
				return field.unit ? `${text} ${field.unit}` : text;
			}
		}
	}
</script>

<div class="space-y-4">
	{#each SPEC_SECTIONS.filter((s) => !s.advanced) as section (section.id)}
		<div>
			<h4 class="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
				{section.title}
			</h4>
			<dl class="grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-3">
				{#each section.fields as field (field.path)}
					{#if !field.showIf || field.showIf(spec)}
						<div class="min-w-0">
							<dt class="text-[11px] text-muted-foreground">{field.label}</dt>
							<dd class="truncate text-xs font-medium" title={formatValue(section.id, field.path)}>
								{formatValue(section.id, field.path)}
							</dd>
						</div>
					{/if}
				{/each}
			</dl>
		</div>
	{/each}
</div>
