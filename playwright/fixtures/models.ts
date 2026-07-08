import { APIRequestContext } from '@playwright/test';
import { authHeaders, requireOk, retryApiRequest } from './auth';

export type ModelPayloadOverrides = Partial<ReturnType<typeof generateModelPayload>>;

const RUN_PREFIX = `test-custom-models-${Date.now()}`;

export function uniqueId(suffix: string) {
  return `${RUN_PREFIX}-${suffix}-${Math.random().toString(36).slice(2, 8)}`;
}

export function generateModelPayload(overrides: ModelPayloadOverrides = {}) {
  const id = overrides.id || uniqueId('e2e-model');

  return {
    id,
    base_model_id: overrides.base_model_id || 'gpt-4o-mini',
    name: overrides.name || `E2E Model ${id}`,
    meta: {
      profile_image_url: '/static/favicon.png',
      description: `E2E description ${id}`,
      suggestion_prompts: null,
      tags: [],
      capabilities: { vision: true, citations: true }
    },
    params: {
      system: `E2E system prompt ${id}`
    },
    access_control: {
      read: { group_ids: [], user_ids: [] },
      write: { group_ids: [], user_ids: [] }
    },
    ...overrides
  };
}

export async function createModelViaAPI(request: APIRequestContext, token: string, overrides: ModelPayloadOverrides = {}) {
  const payload = generateModelPayload(overrides);
  const response = await retryApiRequest(
    async () => request.post('/api/v1/models/create', {
      headers: await authHeaders(token),
      data: payload
    }),
    `create model ${payload.id}`
  ).catch(async (error) => {
    if (await modelExists(request, token, payload.id)) return null;
    throw error;
  });
  if (!response) return payload;
  if (!response.ok()) {
    if ([400, 409].includes(response.status()) && await modelExists(request, token, payload.id)) return payload;
    await requireOk(response, `create model ${payload.id}`);
  }
  return payload;
}

export async function deleteModelViaAPI(request: APIRequestContext, token: string, id: string) {
  const response = await retryApiRequest(
    async () => request.delete(`/api/v1/models/model/delete?id=${encodeURIComponent(id)}`, {
      headers: await authHeaders(token)
    }),
    `delete model ${id}`
  );
  if (response.status() === 404 || response.status() === 401) return;
  await requireOk(response, `delete model ${id}`);
}

export async function getModelsViaAPI(request: APIRequestContext, token: string) {
  const response = await retryApiRequest(
    async () => request.get('/api/v1/models/', { headers: await authHeaders(token) }),
    'get models'
  );
  await requireOk(response, 'get models');
  return response.json();
}

async function modelExists(request: APIRequestContext, token: string, id: string) {
  const models = await getModelsViaAPI(request, token).catch(() => []);
  const list = Array.isArray(models) ? models : Object.values(models ?? {});
  return list.some((model: any) => model?.id === id);
}
