import type { components } from '#lib/api/schema.js';

export type GenerationSpec = components['schemas']['GenerationSpec'];
export type Tolerances = components['schemas']['Tolerances'];
export type SampleType = GenerationSpec['type'];
export type OutputFormat = GenerationSpec['format'];

export type FieldControl =
	'text' | 'number' | 'select' | 'boolean' | 'range' | 'range2' | 'combobox';

export interface FieldOption {
	value: string | number;
	label: string;
}

export interface SpecField {
	/** Dotted path into the spec, e.g. `tolerances.peak_db`. */
	path: string;
	label: string;
	control: FieldControl;
	options?: FieldOption[];
	comboboxValues?: string[];
	min?: number;
	max?: number;
	step?: number;
	unit?: string;
	hint?: string;
	placeholder?: string;
	wide?: boolean;
	showIf?: (spec: GenerationSpec) => boolean;
}

export interface SpecSection {
	id: string;
	title: string;
	description?: string;
	advanced?: boolean;
	fields: SpecField[];
}
