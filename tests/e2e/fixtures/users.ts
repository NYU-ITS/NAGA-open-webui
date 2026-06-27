import { APIRequestContext } from '@playwright/test';
import { authHeaders, requireOk } from './auth';

export async function getCurrentUser(request: APIRequestContext, token: string) {
  const response = await request.get('/api/v1/auths/', { headers: await authHeaders(token) });
  await requireOk(response, 'get current user');
  return response.json();
}

export async function createGroupViaAPI(request: APIRequestContext, token: string, name: string, userIds: string[]) {
  const response = await request.post('/api/v1/groups/create', {
    headers: await authHeaders(token),
    data: {
      name,
      description: `E2E group ${name}`,
      user_ids: userIds,
      permissions: {}
    }
  });
  await requireOk(response, `create group ${name}`);
  return response.json();
}

export async function deleteGroupViaAPI(request: APIRequestContext, token: string, id: string) {
  const response = await request.delete(`/api/v1/groups/id/${encodeURIComponent(id)}/delete`, {
    headers: await authHeaders(token)
  });
  if (response.status() === 404) return;
  await requireOk(response, `delete group ${id}`);
}
