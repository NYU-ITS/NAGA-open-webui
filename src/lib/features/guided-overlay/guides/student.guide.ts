import { GUIDE_VERSION, STUDENT_GUIDE_ID } from '../config/guide.constants';
import type { GuideDefinition } from '../types/guide.types';

export const studentGuide: GuideDefinition = {
	id: STUDENT_GUIDE_ID,
	version: GUIDE_VERSION,
	role: 'student',
	steps: [
		{
			id: 'student-side-navigation',
			targetId: 'sidebar-toggle',
			title: 'Open the side panel.',
			description: 'Use the three-line menu button to expand or collapse your navigation.',
			placement: 'right',
			targetPolicy: 'required'
		},
		{
			id: 'student-your-group',
			title: 'Your Group',
			description: (context) => {
				const groupNames = context.groups.map((group) => group.name);

				return groupNames.length === 1
					? `You are assigned to ${groupNames[0]}. Your available models and course tools are set by this group.`
					: `You are assigned to: ${groupNames.join(', ')}. Your available models and course tools depend on the group you select.`;
			},
			condition: {
				requiresAssignedGroups: true
			}
		},
		{
			id: 'student-new-chat',
			targetId: 'new-chat',
			title: 'Start a new chat.',
			description: 'Click New Chat when you want a clean conversation with your AI assistant.',
			placement: 'bottom',
			targetPolicy: 'required'
		},
		{
			id: 'student-model-selector',
			targetId: 'model-selector',
			title: 'Select an AI model.',
			description: 'Choose a model from the top menu before you begin your study task.',
			placement: 'bottom',
			targetPolicy: 'required'
		},
		{
			id: 'student-message-input',
			targetId: 'message-input',
			title: "You're all set to chat!",
			description: 'Type your message in the input box at the bottom, then hit Enter to send it.',
			placement: 'top',
			targetPolicy: 'required'
		},
		{
			id: 'student-add-content',
			targetId: 'file-upload',
			title: 'Add course content.',
			description: 'Upload files or open extra input options when you need to share material.',
			placement: 'top',
			targetPolicy: 'optional',
			condition: {
				requiredFeatures: ['fileUpload']
			}
		},
		{
			id: 'student-tools-menu',
			targetId: 'chat-tools-menu',
			title: 'Open course tools.',
			description: 'Use this menu for Research Facilities, Practice Questions, and other helpers.',
			placement: 'top',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'student-web-search',
			targetId: 'web-search',
			title: 'Turn on Web Search.',
			description: 'Use Web Search when you need current information or outside sources.',
			placement: 'top',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'student-code-interpreter',
			targetId: 'code-interpreter',
			title: 'Use Code Interpreter.',
			description: 'Run calculations, analyze data, or work through code-based problems here.',
			placement: 'top',
			targetPolicy: 'optional',
			condition: {
				requiredFeatures: ['codeInterpreter']
			}
		},
		{
			id: 'student-voice-input',
			targetId: 'voice-input',
			title: 'Record your voice.',
			description: 'Use the mic button when speaking feels easier than typing.',
			placement: 'top',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'student-call',
			targetId: 'call-button',
			title: 'Start a call.',
			description: 'Talk with the chatbot in real time when you want to work through a question.',
			placement: 'top',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'student-chat-controls',
			targetId: 'chat-controls',
			title: 'Adjust chat controls.',
			description: 'Find chat settings and extra panels in the top-right corner.',
			placement: 'bottom',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'student-help-menu',
			targetId: 'help-menu',
			title: 'Need help later?',
			description: 'Open Help to restart this guided tour whenever you want a quick refresher.',
			placement: 'top',
			targetPolicy: 'optional'
		},
		{
			id: 'student-summary',
			title: "You're ready to start.",
			description:
				'You can now choose a model, start a chat, add course content, and use tools when you need them.',
			summary: true
		}
	]
};
