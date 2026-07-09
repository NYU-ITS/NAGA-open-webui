import { APIRequestContext, Page, test } from '@playwright/test';
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
    base_model_id: overrides.base_model_id || `e2e-base-${id}`,
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
    if ([400, 401, 409].includes(response.status()) && await modelExists(request, token, payload.id)) return payload;
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

export async function waitForModelViaAPI(
  request: APIRequestContext,
  token: string,
  id: string,
  options: { timeoutMs?: number; intervalMs?: number; name?: string } = {}
) {
  const timeoutMs = options.timeoutMs ?? 30_000;
  const intervalMs = options.intervalMs ?? 1_000;
  const startedAt = Date.now();
  let lastModels: any[] = [];
  let lastError: unknown;
  let lastTarget: any = null;

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const models = await getModelsViaAPI(request, token);
      lastModels = normalizeModels(models);
      const model = lastModels.find((item: any) => item?.id === id);
      lastTarget = model ?? null;
      if (model && (!options.name || model.name === options.name)) return model;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  await attachModelDiagnostics(`api-models-${id}`, {
    id,
    expectedName: options.name ?? null,
    lastTarget: summarizeModel(lastTarget),
    lastError: stringifyError(lastError),
    visibleTestModels: summarizeModels(lastModels.filter((model: any) => String(model?.id ?? '').startsWith('test-custom-models-'))),
    visibleModelCount: lastModels.length
  });

  throw new Error(
    `model ${id} did not reach expected API state after ${timeoutMs}ms. ` +
      `Expected name: ${options.name ?? '(any)'}. Last target: ${JSON.stringify(summarizeModel(lastTarget))}. ` +
      `Visible test models: ${lastModels
        .filter((model: any) => String(model?.id ?? '').startsWith('test-custom-models-'))
        .map((model: any) => model.id)
        .join(', ')}. Last API error: ${stringifyError(lastError)}`
  );
}

export async function attachModelPageDiagnostics(page: Page, id: string, token: string) {
  const diagnostics = await page.evaluate(async ({ id, token }) => {
    const summarize = (model: any) => model ? ({
      id: model.id,
      name: model.name,
      base_model_id: model.base_model_id,
      user_id: model.user_id,
      user_email: model.user?.email,
      access_control: model.access_control
    }) : null;

    const response = await fetch('/api/v1/models/', {
      headers: {
        accept: 'application/json',
        authorization: `Bearer ${token}`
      }
    }).catch((error) => ({ error: String(error) }));

    const body = 'json' in response ? await response.json().catch((error) => ({ parseError: String(error) })) : response;
    const list = Array.isArray(body) ? body : Object.values(body ?? {});
    const target = list.find((model: any) => model?.id === id) ?? null;
    const escapedId = CSS.escape(id);

    return {
      url: location.href,
      localStorageTokenPresent: Boolean(localStorage.getItem('token')),
      modelItemPresent: Boolean(document.querySelector(`#model-item-${escapedId}`)),
      modelItemText: document.querySelector(`#model-item-${escapedId}`)?.textContent?.slice(0, 500) ?? null,
      workspaceModelResponseStatus: 'status' in response ? response.status : null,
      targetModel: summarize(target),
      visibleTestModels: list.filter((model: any) => String(model?.id ?? '').startsWith('test-custom-models-')).map(summarize),
      bodyShape: Array.isArray(body) ? 'array' : typeof body
    };
  }, { id, token });

  await attachModelDiagnostics(`page-model-${id}`, diagnostics);
}

function normalizeModels(models: any) {
  return Array.isArray(models) ? models : Object.values(models ?? {});
}

function summarizeModel(model: any) {
  if (!model) return null;
  return {
    id: model.id,
    name: model.name,
    base_model_id: model.base_model_id,
    user_id: model.user_id,
    user_email: model.user?.email,
    access_control: model.access_control
  };
}

function summarizeModels(models: any[]) {
  return models.map(summarizeModel);
}

async function attachModelDiagnostics(name: string, diagnostics: unknown) {
  await test.info().attach(name, {
    body: JSON.stringify(diagnostics, null, 2),
    contentType: 'application/json'
  });
}

function stringifyError(error: unknown) {
  if (!error) return null;
  return error instanceof Error ? `${error.name}: ${error.message}` : String(error);
}

async function modelExists(request: APIRequestContext, token: string, id: string) {
  const models = await getModelsViaAPI(request, token).catch(() => []);
  return normalizeModels(models).some((model: any) => model?.id === id);
}
