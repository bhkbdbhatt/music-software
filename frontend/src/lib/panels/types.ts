import type { Component } from 'svelte';
import type { components } from '#lib/api/schema.js';
import type { Peaks } from '#lib/audio/peaks.js';

export type GenerationSpec = components['schemas']['GenerationSpec'];
export type GenerationResponse = components['schemas']['GenerationResponse'];
export type JobStatus = components['schemas']['GenerationResponse']['status'];

/** Everything a panel may need to render; pages assemble it once. */
export interface PanelContext {
	spec: GenerationSpec | null;
	response: GenerationResponse | null;
	/** URL of the variant currently selected for playback. */
	url: string | null;
	peaks: Peaks | null;
	durationMs: number;
	/** Decoded PCM of the active variant, when available. */
	samples: Float32Array | null;
	sampleRate: number;
	loading: boolean;
	error: string;
}

export function emptyContext(): PanelContext {
	return {
		spec: null,
		response: null,
		url: null,
		peaks: null,
		durationMs: 0,
		samples: null,
		sampleRate: 44100,
		loading: false,
		error: ''
	};
}

export type PanelId =
	'player' | 'waveform' | 'spectrum' | 'spec' | 'analysis' | 'constraints' | 'metadata' | 'raw';

export interface PanelDefinition {
	id: PanelId;
	title: string;
	icon: Component<{ size?: number | string; class?: string }>;
	component: Component<{ context: PanelContext }>;
	defaultVisible: boolean;
}
