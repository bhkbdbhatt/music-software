<script lang="ts">
	import { Monitor, Moon, Sun } from '@lucide/svelte';

	type Pref = 'light' | 'dark' | 'system';

	const ICONS: Record<Pref, typeof Sun> = { light: Sun, dark: Moon, system: Monitor };
	const LABELS: Record<Pref, string> = { light: 'Light', dark: 'Dark', system: 'System' };
	const ORDER: Pref[] = ['light', 'dark', 'system'];

	let pref = $state<Pref>('system');

	$effect(() => {
		const stored = document.documentElement.dataset.themePref as Pref | undefined;
		pref = stored && ORDER.includes(stored) ? stored : 'system';
	});

	$effect(() => {
		if (pref !== 'system') return;
		const media = window.matchMedia('(prefers-color-scheme: dark)');
		const apply = () => {
			document.documentElement.dataset.theme = media.matches ? 'dark' : 'light';
		};
		media.addEventListener('change', apply);
		return () => media.removeEventListener('change', apply);
	});

	function setPref(next: Pref) {
		pref = next;
		const root = document.documentElement;
		root.dataset.themePref = next;
		if (next !== 'system') {
			root.dataset.theme = next;
		} else {
			root.dataset.theme = window.matchMedia('(prefers-color-scheme: dark)').matches
				? 'dark'
				: 'light';
		}
		try {
			localStorage.setItem('sf-theme', next);
		} catch {
			// storage unavailable (private mode); theme still applies for this session
		}
	}

	function cycle() {
		setPref(ORDER[(ORDER.indexOf(pref) + 1) % ORDER.length]);
	}

	const Icon = $derived(ICONS[pref]);
</script>

<button
	type="button"
	onclick={cycle}
	aria-label="Theme: {LABELS[pref]}. Click to change."
	title="Theme: {LABELS[pref]}"
	class="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
>
	<Icon size={15} />
	<span class="hidden sm:inline">{LABELS[pref]}</span>
</button>
