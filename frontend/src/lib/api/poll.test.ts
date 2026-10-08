import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Poller } from './poll.svelte.js';

describe('Poller', () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('captures fetched data and clears errors', async () => {
		const poller = new Poller(async () => ({ value: 42 }));
		expect(poller.data).toBeNull();
		expect(poller.error).toBeNull();

		await poller.refresh();
		expect(poller.data).toEqual({ value: 42 });
		expect(poller.loading).toBe(false);
		expect(poller.error).toBeNull();
	});

	it('surfaces failures via errorMessage and keeps prior data', async () => {
		let fail = false;
		const poller = new Poller(async () => {
			if (fail) throw new Error('backend down');
			return 'ok';
		});
		await poller.refresh();
		expect(poller.data).toBe('ok');

		fail = true;
		await poller.refresh();
		expect(poller.error).toBe('backend down');
		expect(poller.data).toBe('ok');
	});

	it('polls on an interval and stops once until() is satisfied', async () => {
		let ticks = 0;
		const fetcher = vi.fn(async () => {
			ticks += 1;
			return { done: ticks >= 3 };
		});
		const poller = new Poller(fetcher, 1000, (data) => data.done);

		poller.start();
		expect(poller.running).toBe(true);
		expect(fetcher).toHaveBeenCalledTimes(1);

		await vi.advanceTimersByTimeAsync(1000);
		expect(fetcher).toHaveBeenCalledTimes(2);
		await vi.advanceTimersByTimeAsync(1000);
		expect(fetcher).toHaveBeenCalledTimes(3);
		expect(poller.running).toBe(false);

		await vi.advanceTimersByTimeAsync(5_000);
		expect(fetcher).toHaveBeenCalledTimes(3);
	});

	it('ignores refresh calls while a fetch is already in flight', async () => {
		let resolveFetch: (value: string) => void = () => {};
		const fetcher = vi.fn(
			() =>
				new Promise<string>((resolve) => {
					resolveFetch = resolve;
				})
		);
		const poller = new Poller(fetcher);

		const first = poller.refresh();
		await poller.refresh();
		expect(fetcher).toHaveBeenCalledTimes(1);
		expect(poller.loading).toBe(true);

		resolveFetch('done');
		await first;
		expect(poller.data).toBe('done');
		expect(poller.loading).toBe(false);
	});

	it('destroy stops the interval', async () => {
		const fetcher = vi.fn(async () => 'x');
		const poller = new Poller(fetcher, 1000);
		poller.start();
		expect(poller.running).toBe(true);
		poller.destroy();
		expect(poller.running).toBe(false);
		await vi.advanceTimersByTimeAsync(5_000);
		expect(fetcher).toHaveBeenCalledTimes(1);
	});
});
