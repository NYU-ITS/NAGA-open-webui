import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('$lib/constants', () => ({
	WEBUI_API_BASE_URL: '/api/v1'
}));

const {
	getModels,
	getBaseModels,
	createNewModel,
	getModelById,
	updateModelById,
	toggleModelById,
	deleteModelById,
	deleteAllModels
} = await import('$lib/apis/models');

let fetchMock;

beforeEach(() => {
	fetchMock = vi.fn();
	vi.stubGlobal('fetch', fetchMock);
});

// --- getModels ---
describe('getModels', () => {
	it('calls GET /api/v1/models/ and returns parsed JSON', async () => {
		const mockData = [{ id: 'm1', name: 'Model 1' }];
		fetchMock.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockData) });

		const result = await getModels('test-token');

		expect(fetchMock).toHaveBeenCalledWith('/api/v1/models/', expect.objectContaining({
			method: 'GET',
			headers: expect.objectContaining({ authorization: 'Bearer test-token' })
		}));
		expect(result).toEqual(mockData);
	});

	it('throws full error object on non-OK response', async () => {
		const errorBody = { detail: 'Something went wrong' };
		fetchMock.mockResolvedValue({ ok: false, json: () => Promise.resolve(errorBody) });

		await expect(getModels('token')).rejects.toEqual(errorBody);
	});

	it('throws on network error', async () => {
		fetchMock.mockRejectedValue(new Error('Network fail'));

		await expect(getModels('token')).rejects.toThrow();
	});
});

// --- getBaseModels ---
describe('getBaseModels', () => {
	it('calls GET /api/v1/models/base', async () => {
		const mockData = [{ id: 'base1' }];
		fetchMock.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockData) });

		const result = await getBaseModels('token');
		expect(fetchMock).toHaveBeenCalledWith('/api/v1/models/base', expect.objectContaining({
			method: 'GET',
			headers: expect.objectContaining({ authorization: 'Bearer token' })
		}));
		expect(result).toEqual(mockData);
	});

	it('throws full error object on non-OK response', async () => {
		fetchMock.mockResolvedValue({ ok: false, json: () => Promise.resolve({ detail: 'Unauthorized' }) });

		await expect(getBaseModels('token')).rejects.toEqual({ detail: 'Unauthorized' });
	});
});

// --- createNewModel ---
describe('createNewModel', () => {
	it('calls POST /api/v1/models/create with JSON body', async () => {
		const payload = { id: 'new', name: 'New Model', meta: {}, params: {} };
		fetchMock.mockResolvedValue({ ok: true, json: () => Promise.resolve(payload) });

		const result = await createNewModel('token', payload);
		expect(fetchMock).toHaveBeenCalledWith('/api/v1/models/create', expect.objectContaining({
			method: 'POST',
			headers: expect.objectContaining({ authorization: 'Bearer token' }),
			body: JSON.stringify(payload)
		}));
		expect(result).toEqual(payload);
	});

	it('throws err.detail string on 401 duplicate', async () => {
		fetchMock.mockResolvedValue({
			ok: false,
			json: () => Promise.resolve({ detail: 'MODEL_ID_TAKEN' })
		});

		await expect(createNewModel('token', {})).rejects.toBe('MODEL_ID_TAKEN');
	});
});

// --- getModelById ---
describe('getModelById', () => {
	it('calls GET /api/v1/models/model?id=<id>', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: () => Promise.resolve({ id: 'm1', name: 'Model 1' }) });

		const result = await getModelById('token', 'm1');
		expect(fetchMock).toHaveBeenCalledWith('/api/v1/models/model?id=m1', expect.any(Object));
		expect(result.id).toBe('m1');
	});
});

// --- toggleModelById ---
describe('toggleModelById', () => {
	it('calls POST /api/v1/models/model/toggle?id=<id>', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: () => Promise.resolve({ id: 'm1', is_active: false }) });

		await toggleModelById('token', 'm1');
		expect(fetchMock).toHaveBeenCalledWith('/api/v1/models/model/toggle?id=m1', expect.objectContaining({ method: 'POST' }));
	});
});

// --- updateModelById ---
describe('updateModelById', () => {
	it('calls POST /api/v1/models/model/update?id=<id> with body', async () => {
		const updateData = { name: 'Updated', meta: {}, params: {} };
		fetchMock.mockResolvedValue({ ok: true, json: () => Promise.resolve({ id: 'm1', ...updateData }) });

		await updateModelById('token', 'm1', updateData);
		expect(fetchMock).toHaveBeenCalledWith('/api/v1/models/model/update?id=m1', expect.objectContaining({
			method: 'POST',
			headers: expect.objectContaining({ authorization: 'Bearer token' }),
			body: JSON.stringify(updateData)
		}));
	});
});

// --- deleteModelById ---
describe('deleteModelById', () => {
	it('calls DELETE /api/v1/models/model/delete?id=<id>', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: () => Promise.resolve(true) });

		const result = await deleteModelById('token', 'm1');
		expect(fetchMock).toHaveBeenCalledWith('/api/v1/models/model/delete?id=m1', expect.objectContaining({
			method: 'DELETE',
			headers: expect.objectContaining({ authorization: 'Bearer token' })
		}));
		expect(result).toBe(true);
	});

	it('throws err.detail string on error', async () => {
		fetchMock.mockResolvedValue({ ok: false, json: () => Promise.resolve({ detail: 'NOT_FOUND' }) });

		await expect(deleteModelById('token', 'm1')).rejects.toBe('NOT_FOUND');
	});
});

// --- deleteAllModels ---
describe('deleteAllModels', () => {
	it('calls DELETE /api/v1/models/delete/all', async () => {
		fetchMock.mockResolvedValue({ ok: true, json: () => Promise.resolve(true) });

		await deleteAllModels('token');
		expect(fetchMock).toHaveBeenCalledWith('/api/v1/models/delete/all', expect.objectContaining({
			method: 'DELETE',
			headers: expect.objectContaining({ authorization: 'Bearer token' })
		}));
	});
});
