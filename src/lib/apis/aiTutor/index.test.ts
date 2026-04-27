import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	buildAITutorUrl,
	fetchAITutor,
	fetchAITutorJson,
	parseAITutorError,
	pollAITutorJob
} from './index';

describe('aiTutor api helpers', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
		vi.useRealTimers();
	});

	afterEach(() => {
		vi.restoreAllMocks();
		vi.useRealTimers();
	});

	describe('buildAITutorUrl', () => {
		it('normalizes path and keeps only meaningful query values', () => {
			const url = buildAITutorUrl('analysis', {
				homework_id: 'hw-1',
				page: 2,
				include_errors: true,
				empty: '',
				nil: null,
				missing: undefined
			});

			expect(url).toBe(
				'http://localhost:3000/api/ai-tutor/analysis?homework_id=hw-1&page=2&include_errors=true'
			);
		});
	});

	describe('parseAITutorError', () => {
		it('extracts detail string', async () => {
			const response = new Response(JSON.stringify({ detail: 'Bad request detail' }), {
				status: 400,
				headers: { 'content-type': 'application/json' }
			});

			await expect(parseAITutorError(response)).resolves.toBe('Bad request detail');
		});

		it('extracts message string', async () => {
			const response = new Response(JSON.stringify({ message: 'Request denied' }), {
				status: 403,
				headers: { 'content-type': 'application/json' }
			});

			await expect(parseAITutorError(response)).resolves.toBe('Request denied');
		});

		it('joins pydantic-like detail array errors', async () => {
			const response = new Response(
				JSON.stringify({
					detail: [{ msg: 'field required' }, { loc: ['group_id'], msg: 'invalid value' }]
				}),
				{ status: 422, headers: { 'content-type': 'application/json' } }
			);

			await expect(parseAITutorError(response)).resolves.toBe('field required, invalid value');
		});

		it('falls back to http status when payload is not json', async () => {
			const response = new Response('not-json', { status: 502 });

			await expect(parseAITutorError(response)).resolves.toBe('Request failed: 502');
		});
	});

	describe('fetch helpers', () => {
		it('fetchAITutor sends auth and custom headers', async () => {
			const fetchMock = vi.fn().mockResolvedValue(
				new Response(JSON.stringify({ ok: true }), {
					status: 200,
					headers: { 'content-type': 'application/json' }
				})
			);
			vi.stubGlobal('fetch', fetchMock);

			const response = await fetchAITutor('/analysis', {
				token: 'token-abc',
				headers: { 'x-test-header': 'yes' }
			});

			expect(response.ok).toBe(true);
			expect(fetchMock).toHaveBeenCalledWith('http://localhost:3000/api/ai-tutor/analysis', {
				method: 'GET',
				headers: {
					Authorization: 'Bearer token-abc',
					'x-test-header': 'yes'
				},
				body: null
			});
		});

		it('fetchAITutor throws backend error detail for non-2xx response', async () => {
			vi.stubGlobal(
				'fetch',
				vi.fn().mockResolvedValue(
					new Response(JSON.stringify({ detail: 'homework_id is required' }), {
						status: 400,
						headers: { 'content-type': 'application/json' }
					})
				)
			);

			await expect(fetchAITutor('/analysis')).rejects.toThrow('homework_id is required');
		});

		it('fetchAITutorJson returns parsed payload', async () => {
			vi.stubGlobal(
				'fetch',
				vi.fn().mockResolvedValue(
					new Response(JSON.stringify({ rows: [{ id: 'a1' }] }), {
						status: 200,
						headers: { 'content-type': 'application/json' }
					})
				)
			);

			const payload = await fetchAITutorJson<{ rows: Array<{ id: string }> }>('/analysis');

			expect(payload.rows).toHaveLength(1);
			expect(payload.rows[0].id).toBe('a1');
		});
	});

	describe('pollAITutorJob', () => {
		it('polls until status becomes done and emits onStatus callbacks', async () => {
			vi.useFakeTimers();
			const fetchMock = vi
				.fn()
				.mockResolvedValueOnce(
					new Response(JSON.stringify({ status: 'running', progress: 0.2 }), {
						status: 200,
						headers: { 'content-type': 'application/json' }
					})
				)
				.mockResolvedValueOnce(
					new Response(JSON.stringify({ status: 'running', progress: 0.7 }), {
						status: 200,
						headers: { 'content-type': 'application/json' }
					})
				)
				.mockResolvedValueOnce(
					new Response(JSON.stringify({ status: 'done', artifacts: ['report.pdf'] }), {
						status: 200,
						headers: { 'content-type': 'application/json' }
					})
				);

			vi.stubGlobal('fetch', fetchMock);
			const onStatus = vi.fn();

			const promise = pollAITutorJob('job-1', 'jwt-123', { intervalMs: 50, onStatus });
			await vi.advanceTimersByTimeAsync(110);
			const result = await promise;

			expect(fetchMock).toHaveBeenCalledTimes(3);
			expect(fetchMock).toHaveBeenLastCalledWith(
				'http://localhost:3000/api/ai-tutor/pipeline/status/job-1',
				{
					method: 'GET',
					headers: {
						Authorization: 'Bearer jwt-123'
					},
					body: null
				}
			);
			expect(onStatus).toHaveBeenCalledTimes(3);
			expect(result).toEqual({ status: 'done', artifacts: ['report.pdf'] });
		});

		it('throws when backend marks job as failed', async () => {
			vi.stubGlobal(
				'fetch',
				vi.fn().mockResolvedValue(
					new Response(JSON.stringify({ status: 'failed', error: 'Pipeline timeout' }), {
						status: 200,
						headers: { 'content-type': 'application/json' }
					})
				)
			);

			await expect(pollAITutorJob('job-failed')).rejects.toThrow('Pipeline timeout');
		});
	});
});
