import { ADMIN_GUIDE_ID, ADMIN_GUIDE_VERSION } from '../config/guide.constants';
import type { GuideDefinition } from '../types/guide.types';

export const adminGuide: GuideDefinition = {
	id: ADMIN_GUIDE_ID,
	version: ADMIN_GUIDE_VERSION,
	role: 'admin',
	steps: [
		{
			id: 'admin-menu-button',
			targetId: 'sidebar-toggle',
			title: 'Open the side panel.',
			description: 'Use the three-line menu button to expand or collapse your navigation.',
			placement: 'right',
			targetPolicy: 'required'
		},
		{
			id: 'admin-panel-entry',
			targetId: 'admin-panel-menu-item',
			title: 'Open Admin Panel',
			description:
				'Open the account menu and choose Admin Panel. This is where admin setup starts.',
			placement: 'right',
			actionLabel: 'Open Admin Panel',
			beforeTargetActions: [
				{
					type: 'click-target',
					targetId: 'sidebar-toggle',
					skipIfTargetVisible: 'user-menu',
					waitAfterMs: 250
				},
				{
					type: 'click-target',
					targetId: 'user-menu',
					skipIfTargetVisible: 'admin-panel-menu-item',
					waitAfterMs: 250
				}
			],
			targetPolicy: 'required',
			condition: {
				requiredFeatures: ['adminPanel']
			}
		},
		{
			id: 'admin-current-group',
			targetId: 'admin-group-selector',
			route: '/aitutordashboard',
			title: 'Check your admin group.',
			description:
				'This selector shows the group you are managing. Check it before you change settings or review student work.',
			placement: 'bottom',
			targetPolicy: 'required',
			condition: {
				requiresManagedGroups: true
			}
		},
		{
			id: 'admin-usage-monitoring',
			targetId: 'admin-usage',
			route: '/aitutordashboard',
			title: 'Usage / Monitoring',
			description: 'View token usage, cost estimates, and activity metrics where available.',
			placement: 'bottom',
			targetPolicy: 'optional',
			condition: {
				requiredFeatures: ['usage']
			}
		},
		{
			id: 'admin-functions',
			targetId: 'admin-functions',
			route: '/admin/functions',
			title: 'Functions',
			description:
				'Use Functions to manage API-backed tools. This is where API keys and function settings can be set when a tool needs them.',
			placement: 'bottom',
			targetPolicy: 'deferred',
			condition: {
				requiredFeatures: ['functions']
			}
		},
		{
			id: 'admin-documents-settings',
			targetId: 'admin-documents-settings',
			route: '/admin/settings',
			title: 'Documents',
			description:
				'Open Documents settings to review document options such as the embedding model name.',
			placement: 'bottom',
			beforeTargetActions: [
				{
					type: 'click-target',
					targetId: 'admin-documents-tab',
					waitAfterMs: 250
				}
			],
			targetPolicy: 'deferred',
			condition: {
				requiredFeatures: ['modules']
			}
		},
		{
			id: 'admin-workspace-entry',
			targetId: 'sidebar-workspace',
			route: '/workspace',
			title: 'Workspace',
			description:
				'Workspace is where admins manage what users can use, including Models, Knowledge, Prompts, and Tools.',
			placement: 'right',
			actionLabel: 'Open Workspace',
			beforeTargetActions: [
				{
					type: 'click-target',
					targetId: 'sidebar-toggle',
					skipIfTargetVisible: 'sidebar-workspace',
					waitAfterMs: 250
				}
			],
			targetPolicy: 'required',
			condition: {
				anyRequiredFeatures: ['models', 'knowledge', 'prompts', 'tools']
			}
		},
		{
			id: 'admin-knowledge',
			targetId: 'create-knowledge',
			highlightTargetIds: ['admin-knowledge', 'create-knowledge'],
			route: '/workspace/knowledge',
			title: 'Create a Knowledge Base',
			description:
				'Use the plus button to create a knowledge base for shared course or group content.',
			placement: 'left',
			targetPolicy: 'required',
			condition: {
				requiredFeatures: ['knowledge']
			}
		},
		{
			id: 'admin-models',
			targetId: 'create-model',
			highlightTargetIds: ['admin-models', 'create-model'],
			route: '/workspace/models',
			title: 'Create a Model',
			description: 'Use the plus button to create a model profile or configure model access.',
			placement: 'left',
			targetPolicy: 'required',
			condition: {
				requiredFeatures: ['models']
			}
		},
		{
			id: 'admin-new-chat',
			targetId: 'new-chat',
			route: '/',
			title: 'Start a New Chat',
			description: 'Use New Chat to start a clean test conversation after admin setup.',
			placement: 'right',
			targetPolicy: 'required'
		},
		{
			id: 'admin-model-selector',
			targetId: 'model-selector',
			title: 'Select an AI model.',
			description: 'Choose the model from the top menu before testing the chat experience.',
			placement: 'bottom',
			targetPolicy: 'required'
		},
		{
			id: 'admin-message-input',
			targetId: 'message-input',
			title: 'Type a query.',
			description: 'Type a question in the chat box, then press Enter to send it.',
			placement: 'top',
			targetPolicy: 'required'
		},
		{
			id: 'admin-add-content',
			targetId: 'file-upload',
			title: 'Add content.',
			description: 'Use this button to upload files or share extra content with the model.',
			placement: 'top',
			targetPolicy: 'optional',
			condition: {
				requiredFeatures: ['fileUpload']
			}
		},
		{
			id: 'admin-chat-tools-menu',
			targetId: 'chat-tools-menu',
			title: 'Open chat tools.',
			description: 'Use this menu to open extra tools available in the chat box.',
			placement: 'top',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'admin-web-search',
			targetId: 'web-search',
			title: 'Turn on Web Search.',
			description: 'Use Web Search when you want current information or outside sources.',
			placement: 'top',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'admin-code-interpreter',
			targetId: 'code-interpreter',
			title: 'Use Code Interpreter.',
			description: 'Use Code Interpreter for calculations, code, or data tasks inside chat.',
			placement: 'top',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'admin-voice-input',
			targetId: 'voice-input',
			title: 'Record your voice.',
			description: 'Use the mic button when speaking is easier than typing.',
			placement: 'top',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'admin-call',
			targetId: 'call-button',
			title: 'Start a call.',
			description: 'Use the call button to talk with the chatbot in real time.',
			placement: 'top',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'admin-chat-controls',
			targetId: 'chat-controls',
			title: 'Chat controls.',
			description: 'Use Controls to adjust chat settings and review extra chat options.',
			placement: 'bottom',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'admin-help-menu',
			targetId: 'help-menu',
			title: 'Need help later?',
			description: 'Open Help to restart this guided tour whenever you want a quick refresher.',
			placement: 'top',
			targetPolicy: 'optional'
		},
		{
			id: 'admin-summary',
			title: "You're ready to manage and test.",
			description:
				"You've seen the main admin setup areas and the chat tools you can use to test the user experience.",
			summary: true
		}
	]
};
