import { test as setup } from '@playwright/test';
import { ensureTestAccounts } from '../helpers/accounts';

setup('provision admin and student accounts', async ({ request }) => {
	await ensureTestAccounts(request);
});
