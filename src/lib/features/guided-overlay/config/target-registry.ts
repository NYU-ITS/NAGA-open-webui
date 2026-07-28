export const targetRegistry = {
	'user-menu': '[data-guide="user-menu"]',
	'sidebar-toggle': '[data-guide="sidebar-toggle"]',
	sidebar: '[data-guide="sidebar-toggle"], [data-guide="sidebar"], #sidebar',
	'new-chat': '[data-guide="new-chat"], #sidebar-new-chat-button, #new-chat-button',
	workspace:
		'[data-guide="workspace-input"], [data-guide="main-workspace"], #chat-container, #workspace-container, main',
	'model-selector':
		'[data-guide="model-selector"], #model-selector-0-button, [aria-label="Select a model"]',
	'message-input': '[data-guide="message-input"], #chat-input, [data-guide="workspace-input"]',
	'file-upload': '[data-guide="file-upload"], #dropzone, [aria-label="Drag and Drop Container"]',
	'chat-tools-menu': '[data-guide="chat-tools-menu"], [aria-label="Tools"]',
	'web-search': '[data-guide="web-search"]',
	'code-interpreter': '[data-guide="code-interpreter"]',
	'voice-input': '[data-guide="voice-input"], #voice-input-button, [aria-label="Voice Input"]',
	'call-button': '[data-guide="call-button"], [aria-label="Call"]',
	'chat-controls': '[data-guide="chat-controls"], [aria-label="Controls"]',
	'student-knowledge': '[data-guide="student-knowledge"], a[href="/workspace/knowledge"]',
	'conversation-history': '[data-guide="conversation-history"], #sidebar .chat-item',
	'help-menu': '[data-guide="help-menu"], #show-shortcuts-button',
		'admin-panel-menu-item': '[data-guide="admin-panel-menu-item"]',
		'sidebar-workspace': '[data-guide="sidebar-workspace"], a[href="/workspace"]',
		'sidebar-ai-tutor-dashboard':
			'[data-guide="sidebar-ai-tutor-dashboard"], a[href="/aitutordashboard"]',
		'admin-group-selector':
			'[data-guide="ai-tutor-group-selector-trigger"], [data-guide="ai-tutor-group-selector"]',
		'admin-panel': '[data-guide="admin-panel"], a[href="/admin"], a[href="/admin/users"]',
		'group-management': '[data-guide="group-management"], #users-tabs-container',
	'admin-functions':
		'[data-guide="admin-functions-section"], [data-guide="admin-functions"], a[href="/admin/functions"]',
	'admin-documents-tab': '[data-guide="admin-documents-tab"]',
	'admin-documents-settings':
		'[data-guide="admin-documents-section"], [data-guide="admin-documents-tab"]',
		'admin-models':
			'[data-guide="admin-models"], a[href="/workspace/models"], [data-guide="admin-models-section"]',
		'admin-knowledge':
			'[data-guide="admin-knowledge"], a[href="/workspace/knowledge"], [data-guide="admin-knowledge-section"]',
	'admin-tools':
		'[data-guide="admin-tools-section"], [data-guide="admin-tools"], a[href="/admin/functions"], a[href="/workspace/tools"]',
	'admin-modules':
		'[data-guide="admin-modules-section"], [data-guide="admin-modules"], a[href="/admin/settings"]',
	'create-knowledge':
		'[data-guide="create-knowledge"], button[aria-label="Create Knowledge"], a[href="/workspace/knowledge/create"]',
	'create-model': '[data-guide="create-model"], a[href="/workspace/models/create"]',
	'admin-usage': '[data-guide="admin-usage"]',
	'platform-navigation': '[data-guide="platform-navigation"], a[href="/admin"]'
} as const;

export type GuideTargetId = keyof typeof targetRegistry;

const prioritizedTargetRegistry: Partial<Record<GuideTargetId, string[]>> = {
	'admin-group-selector': [
		'[data-guide="ai-tutor-group-selector-trigger"]',
		'[data-guide="ai-tutor-group-selector"]'
	],
	'admin-models': [
		'[data-guide="admin-models"], a[href="/workspace/models"]',
		'[data-guide="admin-models-section"]'
	],
	'admin-knowledge': [
		'[data-guide="admin-knowledge"], a[href="/workspace/knowledge"]',
		'[data-guide="admin-knowledge-section"]'
	],
	'admin-tools': [
		'[data-guide="admin-tools-section"]',
		'[data-guide="admin-tools"], a[href="/admin/functions"], a[href="/workspace/tools"]'
	],
	'admin-functions': [
		'[data-guide="admin-functions-section"]',
		'[data-guide="admin-functions"], a[href="/admin/functions"]'
	],
	'admin-documents-settings': [
		'[data-guide="admin-documents-section"]',
		'[data-guide="admin-documents-tab"]'
	],
	'admin-modules': [
		'[data-guide="admin-modules-section"]',
		'[data-guide="admin-modules"], a[href="/admin/settings"]'
	]
};

export const getTargetSelector = (targetId: string): string | undefined => {
	return targetRegistry[targetId as GuideTargetId];
};

export const getTargetSelectors = (targetId: string): string[] => {
	const guideTargetId = targetId as GuideTargetId;
	const prioritizedSelectors = prioritizedTargetRegistry[guideTargetId];
	const selector = targetRegistry[guideTargetId];

	return prioritizedSelectors ?? (selector ? [selector] : []);
};
