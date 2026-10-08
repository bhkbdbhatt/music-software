import {
	AudioLines,
	AudioWaveform,
	Braces,
	CirclePlay,
	FileText,
	Info,
	ListChecks,
	ShieldCheck
} from '@lucide/svelte';
import AnalysisPanel from '#lib/components/panels/AnalysisPanel.svelte';
import ConstraintsPanel from '#lib/components/panels/ConstraintsPanel.svelte';
import MetadataPanel from '#lib/components/panels/MetadataPanel.svelte';
import PlayerPanel from '#lib/components/panels/PlayerPanel.svelte';
import RawPanel from '#lib/components/panels/RawPanel.svelte';
import SpecPanel from '#lib/components/panels/SpecPanel.svelte';
import SpectrumPanel from '#lib/components/panels/SpectrumPanel.svelte';
import WaveformPanel from '#lib/components/panels/WaveformPanel.svelte';
import type { PanelDefinition, PanelId } from './types.js';

export const PANELS: PanelDefinition[] = [
	{
		id: 'player',
		title: 'Player',
		icon: CirclePlay,
		component: PlayerPanel,
		defaultVisible: true
	},
	{
		id: 'waveform',
		title: 'Waveform',
		icon: AudioWaveform,
		component: WaveformPanel,
		defaultVisible: true
	},
	{
		id: 'spectrum',
		title: 'Spectrum',
		icon: AudioLines,
		component: SpectrumPanel,
		defaultVisible: true
	},
	{
		id: 'analysis',
		title: 'Constraint report',
		icon: ListChecks,
		component: AnalysisPanel,
		defaultVisible: true
	},
	{
		id: 'constraints',
		title: 'Verdicts',
		icon: ShieldCheck,
		component: ConstraintsPanel,
		defaultVisible: true
	},
	{
		id: 'spec',
		title: 'Spec',
		icon: FileText,
		component: SpecPanel,
		defaultVisible: false
	},
	{
		id: 'metadata',
		title: 'Metadata',
		icon: Info,
		component: MetadataPanel,
		defaultVisible: false
	},
	{
		id: 'raw',
		title: 'Raw JSON',
		icon: Braces,
		component: RawPanel,
		defaultVisible: false
	}
];

export const PANEL_IDS: PanelId[] = PANELS.map((panel) => panel.id);

export const PANEL_BY_ID: Record<PanelId, PanelDefinition> = Object.fromEntries(
	PANELS.map((panel) => [panel.id, panel])
) as Record<PanelId, PanelDefinition>;

export function defaultOrder(): PanelId[] {
	return PANELS.filter((panel) => panel.defaultVisible).map((panel) => panel.id);
}
