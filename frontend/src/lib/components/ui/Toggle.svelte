<script lang="ts">
	interface Props {
		checked?: boolean;
		disabled?: boolean;
		'aria-label'?: string;
		onchange?: (checked: boolean) => void;
	}

	let {
		checked = $bindable(false),
		disabled = false,
		'aria-label': ariaLabel,
		onchange
	}: Props = $props();

	function toggle() {
		if (disabled) return;
		checked = !checked;
		onchange?.(checked);
	}
</script>

<button
	type="button"
	role="switch"
	aria-checked={checked}
	aria-label={ariaLabel}
	{disabled}
	onclick={toggle}
	class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50 {checked
		? 'bg-primary'
		: 'bg-muted'}"
>
	<span
		class="pointer-events-none block h-4 w-4 rounded-full bg-white shadow-sm transition-transform {checked
			? 'translate-x-4'
			: 'translate-x-0'}"
	></span>
</button>
