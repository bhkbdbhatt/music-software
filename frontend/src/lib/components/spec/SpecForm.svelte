<script lang="ts">
	import { SPEC_SECTIONS } from '#lib/spec/fields.js';
	import { defaultSpec, getPath, setPath, validateSpec } from '#lib/spec/spec.js';
	import type { GenerationSpec, SpecField } from '#lib/spec/types.js';
	import { cn } from '#lib/utils/cn.js';
	import Field from '#lib/components/ui/Field.svelte';
	import Input from '#lib/components/ui/Input.svelte';
	import Select from '#lib/components/ui/Select.svelte';
	import Slider from '#lib/components/ui/Slider.svelte';
	import Toggle from '#lib/components/ui/Toggle.svelte';

	interface Props {
		spec?: GenerationSpec;
		errors?: Record<string, string>;
		class?: string;
	}

	let { spec = $bindable(defaultSpec()), errors = {}, class: className = '' }: Props = $props();

	const allErrors = $derived({ ...validateSpec(spec), ...errors });

	function cssId(path: string): string {
		return `sf-${path.replaceAll('.', '-')}`;
	}

	function update(path: string, value: unknown): void {
		spec = setPath(spec, path, value);
	}

	function readNumber(event: Event): number | undefined {
		const raw = (event.currentTarget as HTMLInputElement).value;
		if (raw === '') return undefined;
		const parsed = Number(raw);
		return Number.isNaN(parsed) ? undefined : parsed;
	}

	function onNumberChange(path: string) {
		return (event: Event) => {
			const parsed = readNumber(event);
			if (parsed !== undefined) update(path, parsed);
		};
	}

	function onTextChange(path: string, nullable: boolean) {
		return (event: Event) => {
			const raw = (event.currentTarget as HTMLInputElement).value;
			update(path, nullable && raw === '' ? null : raw);
		};
	}

	function onRange2Change(path: string, index: number) {
		return (event: Event) => {
			const parsed = readNumber(event);
			if (parsed === undefined) return;
			const current = [...((getPath(spec, path) as [number, number]) ?? [0, 0])];
			current[index] = parsed;
			update(path, current);
		};
	}

	function numberValue(field: SpecField): number | string {
		const raw = getPath(spec, field.path);
		return raw === null || raw === undefined ? '' : (raw as number | string);
	}

	function rangeValue(field: SpecField): number {
		const raw = getPath(spec, field.path);
		return typeof raw === 'number' ? raw : (field.min ?? 0);
	}

	function formatNumber(value: number): string {
		return String(Number(value.toFixed(2)));
	}
</script>

<div class={cn('space-y-6', className)}>
	{#each SPEC_SECTIONS as section (section.id)}
		{#if section.advanced}
			<details class="group rounded-lg border border-border">
				<summary
					class="cursor-pointer px-4 py-3 text-sm font-medium select-none marker:content-none"
				>
					<span class="group-open:hidden">+ </span><span class="hidden group-open:inline">-</span
					>{section.title}
				</summary>
				<div class="border-t border-border px-4 py-4">
					{#if section.description}
						<p class="mb-3 text-xs text-muted-foreground">{section.description}</p>
					{/if}
					<div class="grid gap-x-4 gap-y-3 sm:grid-cols-2">
						{#each section.fields as field (field.path)}
							{@render fieldRow(field)}
						{/each}
					</div>
				</div>
			</details>
		{:else}
			<section>
				<h3 class="text-sm font-semibold tracking-tight">{section.title}</h3>
				{#if section.description}
					<p class="mt-0.5 mb-3 text-xs text-muted-foreground">{section.description}</p>
				{:else}
					<div class="mb-3"></div>
				{/if}
				<div class="grid gap-x-4 gap-y-3 sm:grid-cols-2">
					{#each section.fields as field (field.path)}
						{@render fieldRow(field)}
					{/each}
				</div>
			</section>
		{/if}
	{/each}
</div>

{#snippet fieldRow(field: SpecField)}
	{#if !field.showIf || field.showIf(spec)}
		{@const id = cssId(field.path)}
		{@const error = allErrors[field.path]}
		<div class={field.wide ? 'sm:col-span-2' : ''}>
			{#if field.control === 'boolean'}
				<div class="flex items-center justify-between gap-3 pt-1 pb-1">
					<div>
						<span class="text-xs font-medium text-muted-foreground">{field.label}</span>
						{#if field.hint}
							<p class="mt-0.5 text-xs text-muted-foreground/80">{field.hint}</p>
						{/if}
					</div>
					<Toggle
						checked={getPath(spec, field.path) as boolean}
						aria-label={field.label}
						onchange={(checked) => update(field.path, checked)}
					/>
				</div>
				{#if error}
					<p class="text-xs text-destructive" role="alert">{error}</p>
				{/if}
			{:else if field.control === 'range'}
				<Field label={field.label} hint={field.hint} {error} for={id}>
					<Slider
						min={field.min}
						max={field.max}
						step={field.step}
						value={rangeValue(field)}
						format={formatNumber}
						oninput={(event) => {
							const parsed = (event.currentTarget as HTMLInputElement).valueAsNumber;
							if (!Number.isNaN(parsed)) update(field.path, parsed);
						}}
					/>
				</Field>
			{:else if field.control === 'range2'}
				{@const range = ((getPath(spec, field.path) as [number, number]) ?? [0, 0]) as [
					number,
					number
				]}
				<Field label={field.label} hint={field.hint} {error} for={id}>
					<div class="flex items-center gap-2">
						<Input
							type="number"
							id={`${id}-min`}
							value={range[0] ?? 0}
							min={field.min}
							step={field.step}
							onchange={onRange2Change(field.path, 0)}
						/>
						<span class="text-xs text-muted-foreground">to</span>
						<Input
							type="number"
							id={`${id}-max`}
							value={range[1] ?? 0}
							min={field.min}
							step={field.step}
							onchange={onRange2Change(field.path, 1)}
						/>
						{#if field.unit}
							<span class="text-xs whitespace-nowrap text-muted-foreground">{field.unit}</span>
						{/if}
					</div>
				</Field>
			{:else if field.control === 'select'}
				<Field label={field.label} hint={field.hint} {error} for={id}>
					<Select
						options={(field.options ?? []).map((option) => ({
							value: String(option.value),
							label: option.label
						}))}
						value={String(getPath(spec, field.path))}
						{id}
						onchange={(event) => {
							const raw = (event.currentTarget as HTMLSelectElement).value;
							const original = (field.options ?? []).find((option) => String(option.value) === raw);
							update(field.path, original ? original.value : raw);
						}}
					/>
				</Field>
			{:else if field.control === 'combobox'}
				<Field label={field.label} hint={field.hint} {error} for={id}>
					<Input
						{id}
						list={`${id}-list`}
						value={(getPath(spec, field.path) ?? '') as string}
						placeholder={field.placeholder}
						invalid={!!error}
						onchange={onTextChange(field.path, false)}
					/>
					<datalist id={`${id}-list`}>
						{#each field.comboboxValues ?? [] as option (option)}
							<option value={option}></option>
						{/each}
					</datalist>
				</Field>
			{:else if field.control === 'number'}
				<Field label={field.label} hint={field.hint} {error} for={id}>
					<div class="flex items-center gap-2">
						<Input
							type="number"
							{id}
							value={numberValue(field)}
							min={field.min}
							max={field.max}
							step={field.step}
							invalid={!!error}
							onchange={onNumberChange(field.path)}
						/>
						{#if field.unit}
							<span class="text-xs whitespace-nowrap text-muted-foreground">{field.unit}</span>
						{/if}
					</div>
				</Field>
			{:else}
				<Field label={field.label} hint={field.hint} {error} for={id}>
					<Input
						{id}
						value={(getPath(spec, field.path) ?? '') as string}
						placeholder={field.placeholder}
						invalid={!!error}
						onchange={onTextChange(
							field.path,
							field.path === 'mood' || field.path === 'reference_sample_url'
						)}
					/>
				</Field>
			{/if}
		</div>
	{/if}
{/snippet}
