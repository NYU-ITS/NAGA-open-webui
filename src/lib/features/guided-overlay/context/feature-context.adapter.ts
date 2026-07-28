const getNestedBoolean = (
	source: Record<string, unknown> | undefined,
	path: string[],
	fallback = false
): boolean => {
	let current: unknown = source;

	for (const part of path) {
		if (!current || typeof current !== 'object') {
			return fallback;
		}

		current = (current as Record<string, unknown>)[part];
	}

	return typeof current === 'boolean' ? current : fallback;
};

export const flattenEnabledPermissions = (
	source: Record<string, unknown> | undefined,
	prefix = ''
): string[] => {
	if (!source) {
		return [];
	}

	return Object.entries(source).flatMap(([key, value]) => {
		const permissionKey = prefix ? `${prefix}.${key}` : key;

		if (typeof value === 'boolean') {
			return value ? [permissionKey] : [];
		}

		if (value && typeof value === 'object') {
			return flattenEnabledPermissions(value as Record<string, unknown>, permissionKey);
		}

		return [];
	});
};

export const resolveFeatureFlags = (
	config: Record<string, unknown> | undefined,
	permissions: Record<string, unknown> | undefined,
	isAdminRole: boolean
): Record<string, boolean> => {
	const configFeatures = config?.features as Record<string, unknown> | undefined;

	return {
		adminPanel: isAdminRole,
		groupManagement: isAdminRole,
		models: isAdminRole || getNestedBoolean(permissions, ['workspace', 'models']),
		knowledge: isAdminRole || getNestedBoolean(permissions, ['workspace', 'knowledge']),
		prompts: isAdminRole || getNestedBoolean(permissions, ['workspace', 'prompts']),
		tools: isAdminRole || getNestedBoolean(permissions, ['workspace', 'tools']),
		functions: isAdminRole,
		modules: isAdminRole,
		usage: isAdminRole,
		fileUpload: isAdminRole || getNestedBoolean(permissions, ['chat', 'file_upload'], true),
		webSearch:
			getNestedBoolean(permissions, ['features', 'web_search']) ||
			getNestedBoolean(configFeatures, ['enable_web_search']),
		imageGeneration:
			getNestedBoolean(permissions, ['features', 'image_generation']) ||
			getNestedBoolean(configFeatures, ['enable_image_generation']),
		codeInterpreter: getNestedBoolean(permissions, ['features', 'code_interpreter'])
	};
};
