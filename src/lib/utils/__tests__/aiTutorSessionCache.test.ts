import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
	clearAITutorSessionCache,
	clearAITutorSessionCacheByGroup,
	clearAITutorSessionCacheByPrefix,
	loadWithAITutorSessionCache,
	readAITutorSessionCache,
	writeAITutorSessionCache
} from '../aiTutorSessionCache';

describe('aiTutorSessionCache', () => {
	beforeEach(() => {
		sessionStorage.clear();
		vi.restoreAllMocks();
	});

	it('writes and reads cache entry while ttl is valid', () => {
		writeAITutorSessionCache('group-a:homework', { rows: 2 });

		const value = readAITutorSessionCache<{ rows: number }>('group-a:homework', 60_000);

		expect(value).toEqual({ rows: 2 });
	});

	it('returns null and clears entry once ttl expires', () => {
		vi.spyOn(Date, 'now')
			.mockReturnValueOnce(1000)
			.mockReturnValueOnce(4000);

		writeAITutorSessionCache('group-a:analysis', { id: 'a1' });
		const value = readAITutorSessionCache('group-a:analysis', 2000);

		expect(value).toBeNull();
		expect(sessionStorage.getItem('ai_tutor_session_cache:group-a:analysis')).toBeNull();
	});

	it('supports direct and prefix-based clearing', () => {
		writeAITutorSessionCache('g1:homework', [1, 2]);
		writeAITutorSessionCache('g1:analysis', [3]);
		writeAITutorSessionCache('g2:analysis', [4]);

		clearAITutorSessionCache('g1:homework');
		clearAITutorSessionCacheByPrefix('g1:');

		expect(sessionStorage.getItem('ai_tutor_session_cache:g1:homework')).toBeNull();
		expect(sessionStorage.getItem('ai_tutor_session_cache:g1:analysis')).toBeNull();
		expect(sessionStorage.getItem('ai_tutor_session_cache:g2:analysis')).not.toBeNull();
	});

	it('clears all group-related keys across pages', () => {
		writeAITutorSessionCache('student-analysis:group-42:homework', ['a']);
		writeAITutorSessionCache('topic-analysis:group-42:error-types', ['b']);
		writeAITutorSessionCache('student-analysis:group-99:homework', ['c']);

		clearAITutorSessionCacheByGroup('group-42');

		expect(sessionStorage.getItem('ai_tutor_session_cache:student-analysis:group-42:homework')).toBeNull();
		expect(sessionStorage.getItem('ai_tutor_session_cache:topic-analysis:group-42:error-types')).toBeNull();
		expect(sessionStorage.getItem('ai_tutor_session_cache:student-analysis:group-99:homework')).not.toBeNull();
	});

	it('returns cached value immediately and revalidates in background', async () => {
		writeAITutorSessionCache('group-a:topic', { version: 1 });

		const onCached = vi.fn();
		const loader = vi.fn().mockResolvedValue({ version: 2 });

		const first = await loadWithAITutorSessionCache({
			key: 'group-a:topic',
			ttlMs: 60_000,
			loader,
			onCached
		});

		expect(first).toEqual({ version: 1 });
		expect(onCached).toHaveBeenCalledWith({ version: 1 });
		expect(loader).toHaveBeenCalledTimes(1);

		await vi.waitFor(() => {
			expect(onCached).toHaveBeenLastCalledWith({ version: 2 });
		});
		expect(readAITutorSessionCache<{ version: number }>('group-a:topic', 60_000)).toEqual({
			version: 2
		});
	});

	it('deduplicates concurrent cache misses for same key', async () => {
		const loader = vi.fn().mockResolvedValue({ rows: [1, 2, 3] });

		const [a, b] = await Promise.all([
			loadWithAITutorSessionCache({
				key: 'group-a:homework',
				ttlMs: 60_000,
				loader
			}),
			loadWithAITutorSessionCache({
				key: 'group-a:homework',
				ttlMs: 60_000,
				loader
			})
		]);

		expect(loader).toHaveBeenCalledTimes(1);
		expect(a).toEqual({ rows: [1, 2, 3] });
		expect(b).toEqual({ rows: [1, 2, 3] });
	});

	it('reports background refresh errors without dropping cached payload', async () => {
		writeAITutorSessionCache('group-a:analysis', { stable: true });
		const onRefreshError = vi.fn();

		const value = await loadWithAITutorSessionCache({
			key: 'group-a:analysis',
			ttlMs: 60_000,
			loader: vi.fn().mockRejectedValue(new Error('network down')),
			onRefreshError
		});

		expect(value).toEqual({ stable: true });

		await vi.waitFor(() => {
			expect(onRefreshError).toHaveBeenCalledTimes(1);
		});
		expect(readAITutorSessionCache('group-a:analysis', 60_000)).toEqual({ stable: true });
	});
});
