import { APIRequestContext } from '@playwright/test';
import { authHeaders, requireOk, retryApiRequest } from './auth';

export async function getCurrentUser(request: APIRequestContext, token: string) {
  const response = await retryApiRequest(
    () => request.get('/api/v1/auths/', { headers: authHeaders(token) }),
    'get current user'
  );
  await requireOk(response, 'get current user');
  return response.json();
}

export async function createGroupViaAPI(request: APIRequestContext, token: string, name: string, userIds: string[]) {
  const response = await retryApiRequest(
    () => request.post('/api/v1/groups/create', {
      headers: authHeaders(token),
      data: {
        name,
        description: `E2E group ${name}`,
        user_ids: userIds,
        permissions: {}
      }
    }),
    `create group ${name}`
  );
  await requireOk(response, `create group ${name}`);
  return response.json();
}

export async function deleteGroupViaAPI(request: APIRequestContext, token: string, id: string) {
  const response = await retryApiRequest(
    () => request.delete(`/api/v1/groups/id/${encodeURIComponent(id)}/delete`, {
      headers: authHeaders(token)
    }),
    `delete group ${id}`
  );
  if (response.status() === 404) return;
  await requireOk(response, `delete group ${id}`);
}
