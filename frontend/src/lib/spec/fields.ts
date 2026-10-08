import type { SpecSection } from './types.js';

export const CATEGORY_SUGGESTIONS = [
	'kick',
	'snare',
	'hihat',
	'clap',
	'tom',
	'riser',
	'impact',
	'pad',
	'bass',
	'arp',
	'lead',
	'texture',
	'stinger',
	'fx'
];

export const KEY_SUGGESTIONS = [
	'Cm',
	'C#m',
	'Dm',
	'Ebm',
	'Em',
	'Fm',
	'F#m',
	'Gm',
	'G#m',
	'Am',
	'Bbm',
	'Bm',
	'C',
	'C#',
	'D',
	'Eb',
	'E',
	'F',
	'F#',
	'G',
	'Ab',
	'A',
	'Bb',
	'B'
];

export const GENRE_SUGGESTIONS = [
	'techno',
	'house',
	'trance',
	'dnb',
	'hiphop',
	'lofi',
	'ambient',
	'cinematic',
	'rock',
	'pop',
	'experimental'
];

export const SPEC_SECTIONS: SpecSection[] = [
	{
		id: 'basic',
		title: 'Sample',
		fields: [
			{
				path: 'type',
				label: 'Type',
				control: 'select',
				options: [
					{ value: 'one_shot', label: 'One-shot' },
					{ value: 'loop', label: 'Loop' },
					{ value: 'texture', label: 'Texture' },
					{ value: 'stinger', label: 'Stinger' }
				]
			},
			{
				path: 'category',
				label: 'Category',
				control: 'combobox',
				comboboxValues: CATEGORY_SUGGESTIONS,
				hint: 'Instrument or role, e.g. kick'
			},
			{
				path: 'duration_ms',
				label: 'Duration',
				control: 'number',
				unit: 'ms',
				min: 1,
				step: 1,
				showIf: (spec) => spec.type !== 'loop'
			},
			{
				path: 'duration_beats',
				label: 'Length',
				control: 'number',
				unit: 'beats',
				min: 0.25,
				step: 0.25,
				showIf: (spec) => spec.type === 'loop'
			},
			{
				path: 'sample_rate',
				label: 'Sample rate',
				control: 'select',
				options: [
					{ value: 44100, label: '44.1 kHz' },
					{ value: 48000, label: '48 kHz' },
					{ value: 88200, label: '88.2 kHz' },
					{ value: 96000, label: '96 kHz' }
				]
			},
			{
				path: 'bit_depth',
				label: 'Bit depth',
				control: 'select',
				options: [
					{ value: 16, label: '16-bit' },
					{ value: 24, label: '24-bit' },
					{ value: 32, label: '32-bit' }
				]
			},
			{
				path: 'channels',
				label: 'Channels',
				control: 'select',
				options: [
					{ value: 1, label: 'Mono' },
					{ value: 2, label: 'Stereo' }
				]
			}
		]
	},
	{
		id: 'spectral',
		title: 'Spectral constraints',
		description: 'Hard targets, enforced by post-processing and re-measured.',
		fields: [
			{
				path: 'fundamental_hz',
				label: 'Fundamental range',
				control: 'range2',
				unit: 'Hz',
				min: 1,
				step: 1,
				wide: true,
				hint: 'The detected pitch is shifted into this window.'
			},
			{
				path: 'spectral_floor_hz',
				label: 'Spectral floor',
				control: 'number',
				unit: 'Hz',
				min: 0,
				step: 1,
				hint: 'High-pass corner'
			},
			{
				path: 'spectral_ceiling_hz',
				label: 'Spectral ceiling',
				control: 'number',
				unit: 'Hz',
				min: 1,
				step: 10,
				hint: 'Low-pass corner'
			},
			{
				path: 'spectral_tilt_db_per_octave',
				label: 'Spectral tilt',
				control: 'range',
				min: -24,
				max: 24,
				step: 0.5,
				unit: 'dB/oct'
			},
			{
				path: 'peak_db',
				label: 'Peak level',
				control: 'number',
				unit: 'dBFS',
				min: -100,
				max: 0,
				step: 0.5
			}
		]
	},
	{
		id: 'envelope',
		title: 'Envelope',
		description: 'ADSR shape, verified against the rendered amplitude envelope.',
		fields: [
			{ path: 'attack_ms', label: 'Attack', control: 'number', unit: 'ms', min: 0, step: 0.1 },
			{ path: 'decay_ms', label: 'Decay', control: 'number', unit: 'ms', min: 0, step: 1 },
			{
				path: 'sustain_level',
				label: 'Sustain',
				control: 'range',
				min: 0,
				max: 1,
				step: 0.01
			},
			{ path: 'release_ms', label: 'Release', control: 'number', unit: 'ms', min: 0, step: 1 }
		]
	},
	{
		id: 'context',
		title: 'Musical context',
		description: 'Soft conditioning: shapes the model, never guaranteed.',
		fields: [
			{ path: 'bpm', label: 'BPM', control: 'number', min: 1, max: 400, step: 1 },
			{
				path: 'key',
				label: 'Key',
				control: 'combobox',
				comboboxValues: KEY_SUGGESTIONS
			},
			{
				path: 'genre',
				label: 'Genre',
				control: 'combobox',
				comboboxValues: GENRE_SUGGESTIONS
			},
			{ path: 'mood', label: 'Mood', control: 'text', placeholder: 'dark, ethereal...' },
			{
				path: 'reference_sample_url',
				label: 'Reference sample',
				control: 'text',
				wide: true,
				placeholder: 'https://... (make something like this)'
			}
		]
	},
	{
		id: 'batch',
		title: 'Batch',
		fields: [
			{ path: 'batch_size', label: 'Variants', control: 'number', min: 1, max: 64, step: 1 },
			{
				path: 'diversity',
				label: 'Diversity',
				control: 'range',
				min: 0,
				max: 1,
				step: 0.05,
				hint: '0 = identical, 1 = maximum variation'
			}
		]
	},
	{
		id: 'output',
		title: 'Output',
		fields: [
			{
				path: 'format',
				label: 'Format',
				control: 'select',
				options: [
					{ value: 'wav', label: 'WAV' },
					{ value: 'flac', label: 'FLAC' },
					{ value: 'mp3', label: 'MP3' }
				]
			},
			{
				path: 'metadata_embed',
				label: 'Embed metadata',
				control: 'boolean',
				hint: 'Licence + generation parameters in the file header'
			},
			{
				path: 'stereo_width',
				label: 'Stereo width',
				control: 'range',
				min: 0,
				max: 4,
				step: 0.05,
				hint: 'Side/mid ratio; null leaves the model untouched'
			}
		]
	},
	{
		id: 'tolerances',
		title: 'Verification tolerances',
		description: 'How close is close enough when checking the rendered file?',
		advanced: true,
		fields: [
			{
				path: 'tolerances.fundamental_hz',
				label: 'Pitch slack',
				control: 'number',
				unit: 'Hz',
				min: 0,
				step: 0.5
			},
			{
				path: 'tolerances.peak_db',
				label: 'Peak slack',
				control: 'number',
				unit: 'dB',
				min: 0,
				step: 0.1
			},
			{
				path: 'tolerances.attack_ms',
				label: 'Attack slack',
				control: 'number',
				unit: 'ms',
				min: 0,
				step: 0.5
			},
			{
				path: 'tolerances.duration_pct',
				label: 'Duration slack',
				control: 'number',
				min: 0,
				max: 1,
				step: 0.005,
				hint: 'Relative, 0.02 = 2%'
			},
			{
				path: 'tolerances.ceiling_violation_db',
				label: 'Ceiling leakage',
				control: 'number',
				unit: 'dB',
				max: 0,
				step: 5
			},
			{
				path: 'tolerances.floor_slope_db_per_oct',
				label: 'Floor slope',
				control: 'number',
				unit: 'dB/oct',
				max: 0,
				step: 1
			},
			{
				path: 'tolerances.tilt_db_per_octave',
				label: 'Tilt slack',
				control: 'number',
				unit: 'dB/oct',
				min: 0,
				step: 0.25
			},
			{
				path: 'tolerances.stereo_width',
				label: 'Width slack',
				control: 'number',
				min: 0,
				step: 0.01
			}
		]
	}
];
