export type GroupNaming = {
	category: string;
	school: string;
	department: string;
	tool_type: string;
	tool_name: string;
	owner: string;
	custom: boolean;
};

export type GroupWithNaming = {
	name?: string;
	created_by?: string;
	meta?: { naming?: Partial<GroupNaming> } | null;
};

export const emptyNaming = (): GroupNaming => ({
	category: '',
	school: '',
	department: '',
	tool_type: '',
	tool_name: '',
	owner: '',
	custom: false
});

export const CATEGORY_OPTIONS = [
	{ value: 'Research', abbreviation: 'R' },
	{ value: 'Instruction', abbreviation: 'I' },
	{ value: 'Administration', abbreviation: 'A' }
];

export const SCHOOL_OPTIONS = [
	{ value: 'Arts & Science', abbreviation: 'A&S' },
	{ value: 'College of Dentistry', abbreviation: 'Dentistry' },
	{ value: 'Grossman School of Medicine', abbreviation: 'Grossman' },
	{ value: 'NYU IT', abbreviation: 'NYU IT' },
	{ value: 'Rory Meyers College of Nursing', abbreviation: 'Meyers' },
	{ value: 'School of Global Public Health', abbreviation: 'GPH' },
	{ value: 'School of Law', abbreviation: 'Law' },
	{ value: 'School of Professional Studies (SPS)', abbreviation: 'SPS' },
	{
		value: 'Steinhardt School of Culture, Education, and Human Development',
		abbreviation: 'Steinhardt'
	},
	{ value: 'Stern School of Business', abbreviation: 'Stern' },
	{ value: 'Tandon School of Engineering', abbreviation: 'Tandon' }
];

export const TOOL_TYPE_OPTIONS = [
	'AI Tutor',
	'AI Chatbot',
	'Research Assistant',
	'Administrative Assistant',
	'Data Pipeline',
	'Knowledge Base Assistant',
	'Document Assistant',
	'Analytics Assistant',
	'Workflow Automation',
	'Custom Tool'
];

const abbreviate = (options: { value: string; abbreviation: string }[], value: string) =>
	options.find((option) => option.value === value)?.abbreviation ?? value;

export const schoolAbbreviation = (school: string) => abbreviate(SCHOOL_OPTIONS, school);

// [Category] - [School] - [Department] - [Tool Name or Tool Type] - [Owner],
// skipping any part that is empty.
export const generateGroupName = (fields: {
	category?: string;
	school?: string;
	department?: string;
	toolType?: string;
	toolName?: string;
	owner?: string;
}): string => {
	const parts = [
		fields.category ? abbreviate(CATEGORY_OPTIONS, fields.category) : '',
		fields.school ? abbreviate(SCHOOL_OPTIONS, fields.school) : '',
		fields.department?.trim() ?? '',
		fields.toolName?.trim() || fields.toolType || '',
		fields.owner?.trim() ?? ''
	].filter((part) => part !== '');

	return parts.join(' - ');
};

// Free-text haystack for the group list search: display name plus every piece
// of structured metadata, so groups stay searchable by category, school,
// department, tool, and owner even when a custom display name is used.
export const groupSearchText = (group: GroupWithNaming): string => {
	const naming = group?.meta?.naming ?? {};

	return [
		group?.name,
		naming.category,
		naming.school,
		naming.school ? schoolAbbreviation(naming.school) : '',
		naming.department,
		naming.tool_type,
		naming.tool_name,
		naming.owner,
		group?.created_by
	]
		.filter(Boolean)
		.join(' ')
		.toLowerCase();
};
