<script lang="ts">
	import { goto } from '$app/navigation';
	import { Pencil, Play, Plus, ScrollText } from '@lucide/svelte';
	import { APP_NAME } from '#lib/shell/nav.js';
	import { api, errorMessage } from '#lib/api/client.js';
	import { defaultSpec, validateSpec } from '#lib/spec/spec.js';
	import type { GenerationSpec, RecipeRead } from '#lib/api/types.js';
	import SpecForm from '#lib/components/spec/SpecForm.svelte';
	import Button from '#lib/components/ui/Button.svelte';
	import EmptyState from '#lib/components/ui/EmptyState.svelte';
	import Field from '#lib/components/ui/Field.svelte';
	import Input from '#lib/components/ui/Input.svelte';
	import Modal from '#lib/components/ui/Modal.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	let recipes = $state<RecipeRead[]>([]);
	let loading = $state(true);
	let loadError = $state('');

	let editorOpen = $state(false);
	let editingId = $state<string | null>(null);
	let formName = $state('');
	let formDescription = $state('');
	let formSpec = $state<GenerationSpec>(defaultSpec());
	let formError = $state('');
	let saving = $state(false);
	let runningId = $state<string | null>(null);

	const formErrors = $derived(validateSpec(formSpec));

	async function refresh(): Promise<void> {
		loading = true;
		loadError = '';
		try {
			const page = await api.listRecipes({ limit: 100 });
			recipes = page.items ?? [];
		} catch (cause) {
			loadError = errorMessage(cause);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void refresh();
	});

	function openNew(): void {
		editingId = null;
		formName = '';
		formDescription = '';
		formSpec = defaultSpec();
		formError = '';
		editorOpen = true;
	}

	function openEdit(recipe: RecipeRead): void {
		editingId = recipe.id;
		formName = recipe.name;
		formDescription = recipe.description ?? '';
		formSpec = structuredClone(recipe.spec);
		formError = '';
		editorOpen = true;
	}

	async function save(): Promise<void> {
		formError = '';
		if (formName.trim().length === 0) {
			formError = 'Name is required.';
			return;
		}
		if (Object.keys(formErrors).length > 0) {
			formError = 'Fix the spec before saving.';
			return;
		}
		saving = true;
		try {
			if (editingId) {
				await api.updateRecipe(editingId, {
					name: formName.trim(),
					description: formDescription.trim() || null,
					spec: formSpec
				});
			} else {
				await api.createRecipe({
					name: formName.trim(),
					description: formDescription.trim() || null,
					spec: formSpec
				});
			}
			editorOpen = false;
			await refresh();
		} catch (cause) {
			formError = errorMessage(cause);
		} finally {
			saving = false;
		}
	}

	async function run(recipe: RecipeRead): Promise<void> {
		runningId = recipe.id;
		try {
			const launched = await api.runRecipe(recipe.id);
			await goto(`/jobs/${launched.job_id}`);
		} catch (cause) {
			loadError = errorMessage(cause);
		} finally {
			runningId = null;
		}
	}

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleDateString(undefined, {
			month: 'short',
			day: 'numeric',
			year: 'numeric'
		});
	}
</script>

<svelte:head><title>Recipes — {APP_NAME}</title></svelte:head>

<section class="mb-6 flex flex-wrap items-center gap-3">
	<div class="min-w-0 flex-1">
		<h2 class="text-lg font-semibold tracking-tight">Recipes</h2>
		<p class="mt-1 text-sm text-muted-foreground">Saved starting points for generation specs.</p>
	</div>
	<Button variant="primary" onclick={openNew}>
		<Plus size={15} /> New recipe
	</Button>
</section>

{#if loadError}
	<div
		class="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
		role="alert"
	>
		{loadError}
	</div>
{/if}

{#if loading && recipes.length === 0}
	<div class="flex items-center gap-2 text-sm text-muted-foreground">
		<Spinner size={14} /> Loading recipes…
	</div>
{:else if recipes.length === 0}
	<EmptyState
		icon={ScrollText}
		title="No recipes yet"
		description="Save a spec as a recipe to reuse it later."
	>
		<Button variant="primary" onclick={openNew}>
			<Plus size={15} /> New recipe
		</Button>
	</EmptyState>
{:else}
	<div class="space-y-3">
		{#each recipes as recipe (recipe.id)}
			<div
				class="flex flex-wrap items-center gap-4 rounded-lg border border-border bg-card px-4 py-3"
			>
				<div class="min-w-0 flex-1">
					<div class="flex items-center gap-2">
						<span class="font-medium">{recipe.name}</span>
						<span class="text-xs text-muted-foreground">{recipe.spec.category}</span>
					</div>
					{#if recipe.description}
						<p class="mt-0.5 truncate text-sm text-muted-foreground">{recipe.description}</p>
					{/if}
					<p class="mt-0.5 text-xs text-muted-foreground">
						Updated {formatDate(recipe.updated_at)}
					</p>
				</div>
				<div class="flex items-center gap-2">
					<Button
						variant="primary"
						size="sm"
						loading={runningId === recipe.id}
						onclick={() => void run(recipe)}
					>
						<Play size={14} /> Run
					</Button>
					<Button variant="outline" size="sm" onclick={() => openEdit(recipe)}>
						<Pencil size={14} /> Edit
					</Button>
				</div>
			</div>
		{/each}
	</div>
{/if}

<Modal
	bind:open={editorOpen}
	title={editingId ? 'Edit recipe' : 'New recipe'}
	size="lg"
	onclose={() => (editorOpen = false)}
>
	<div class="space-y-4">
		<Field label="Name" hint="Unique, lowercase names work best." for="recipe-name">
			<Input
				id="recipe-name"
				value={formName}
				placeholder="kick_909"
				oninput={(event) => (formName = (event.currentTarget as HTMLInputElement).value)}
			/>
		</Field>
		<Field label="Description" for="recipe-description">
			<Input
				id="recipe-description"
				value={formDescription}
				placeholder="What this recipe is for."
				oninput={(event) => (formDescription = (event.currentTarget as HTMLInputElement).value)}
			/>
		</Field>
		<SpecForm bind:spec={formSpec} errors={formErrors} />
		{#if formError}
			<p class="text-sm text-destructive" role="alert">{formError}</p>
		{/if}
	</div>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (editorOpen = false)}>Cancel</Button>
		<Button variant="primary" loading={saving} onclick={() => void save()}>Save</Button>
	{/snippet}
</Modal>
