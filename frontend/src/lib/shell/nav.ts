import {
	AudioLines,
	LayoutDashboard,
	Library,
	ListChecks,
	Layers,
	ScrollText,
	Settings,
	WandSparkles
} from '@lucide/svelte';
import type { Component } from 'svelte';

export interface NavItem {
	href: string;
	label: string;
	icon: Component<{ size?: number | string; class?: string }>;
}

export interface NavGroup {
	label: string;
	items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
	{
		label: 'Overview',
		items: [{ href: '/', label: 'Dashboard', icon: LayoutDashboard }]
	},
	{
		label: 'Create',
		items: [
			{ href: '/generate', label: 'Generate', icon: WandSparkles },
			{ href: '/recipes', label: 'Recipes', icon: ScrollText }
		]
	},
	{
		label: 'Activity',
		items: [
			{ href: '/jobs', label: 'Jobs', icon: ListChecks },
			{ href: '/batches', label: 'Batches', icon: Layers },
			{ href: '/library', label: 'Library', icon: Library }
		]
	},
	{
		label: 'System',
		items: [{ href: '/settings', label: 'Settings', icon: Settings }]
	}
];

export const APP_NAME = 'SampleForge';
export const APP_ICON = AudioLines;
