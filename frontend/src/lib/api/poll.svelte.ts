import { errorMessage } from './client.js';

type Until<T> = (data: T) => boolean;

/**
 * Repeating async data fetcher with Svelte 5 reactive state.
 *
 * `refresh` is skipped while a fetch is in flight, errors are surfaced via
 * `error`, and polling stops automatically once `until(data)` returns true.
 */
export class Poller<T> {
	data = $state<T | null>(null);
	error = $state<string | null>(null);
	loading = $state(false);

	readonly #fetcher: () => Promise<T>;
	readonly #intervalMs: number;
	readonly #until: Until<T>;
	#timer: ReturnType<typeof setInterval> | null = null;
	#inFlight = false;

	constructor(fetcher: () => Promise<T>, intervalMs = 1000, until: Until<T> = () => false) {
		this.#fetcher = fetcher;
		this.#intervalMs = intervalMs;
		this.#until = until;
	}

	async refresh(): Promise<void> {
		if (this.#inFlight) return;
		this.#inFlight = true;
		this.loading = true;
		try {
			const data = await this.#fetcher();
			this.data = data;
			this.error = null;
			if (this.#until(data)) this.stop();
		} catch (error) {
			this.error = errorMessage(error);
		} finally {
			this.loading = false;
			this.#inFlight = false;
		}
	}

	start(): void {
		if (this.#timer !== null) return;
		void this.refresh();
		this.#timer = setInterval(() => {
			void this.refresh();
		}, this.#intervalMs);
	}

	stop(): void {
		if (this.#timer !== null) {
			clearInterval(this.#timer);
			this.#timer = null;
		}
	}

	get running(): boolean {
		return this.#timer !== null;
	}

	destroy(): void {
		this.stop();
	}
}
