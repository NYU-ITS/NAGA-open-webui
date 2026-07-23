export type GroupNaming = {
	category: string;
	semester: string;
	year: string;
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
	semester: '',
	year: '',
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
	{ value: 'Courant Institute School of Mathematics, Computing, and Data Science', abbreviation: 'Courant' },
	{ value: 'Gallatin School of Individualized Study', abbreviation: 'Gallatin' },
	{ value: 'Grossman School of Medicine', abbreviation: 'Grossman' },
	{ value: 'Institute of Fine Arts', abbreviation: 'IFA' },
	{ value: 'Institute for the Study of the Ancient World', abbreviation: 'ISAW' },
	{ value: 'NYU Abu Dhabi', abbreviation: 'NYUAD' },
	{ value: 'NYU Shanghai', abbreviation: 'NYUSH' },
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
	{ value: 'Tandon School of Engineering', abbreviation: 'Tandon' },
	{ value: 'Tisch School of the Arts', abbreviation: 'Tisch' },
];

export const TOOL_TYPE_OPTIONS = ['AI Tutor', 'AI Chatbot', 'Data Pipeline'];

export const SEMESTER_OPTIONS = ['Fall', 'Summer', 'Spring'];

// Years span three back through five ahead of the current year (e.g. 2023–2031
// in 2026), covering historical groups and pre-created future terms.
export const yearOptions = (): number[] => {
	const current = new Date().getFullYear();
	const years: number[] = [];
	for (let y = current - 3; y <= current + 5; y++) years.push(y);
	return years;
};

// A term renders as e.g. FALL2026. Year alone renders as just the year; a
// semester with no year contributes nothing (the UI requires a year when a
// semester is chosen).
export const termToken = (semester?: string, year?: string): string => {
	if (year && semester) return `${semester.toUpperCase()}${year}`;
	if (year) return `${year}`;
	return '';
};

const abbreviate = (options: { value: string; abbreviation: string }[], value: string) =>
	options.find((option) => option.value === value)?.abbreviation ?? value;

export const schoolAbbreviation = (school: string) => abbreviate(SCHOOL_OPTIONS, school);

// [Category] - [Term] - [School] - [Department] - [Tool Type] - [Tool Name] - [Owner],
// skipping any part that is empty. Tool Type and Tool Name appear side by side
// rather than one replacing the other.
export const generateGroupName = (fields: {
	category?: string;
	semester?: string;
	year?: string;
	school?: string;
	department?: string;
	toolType?: string;
	toolName?: string;
	owner?: string;
}): string => {
	const parts = [
		fields.category ? abbreviate(CATEGORY_OPTIONS, fields.category) : '',
		termToken(fields.semester, fields.year),
		fields.school ? abbreviate(SCHOOL_OPTIONS, fields.school) : '',
		fields.department?.trim() ?? '',
		fields.toolType?.trim() ?? '',
		fields.toolName?.trim() ?? '',
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
		termToken(naming.semester, naming.year),
		naming.semester,
		naming.year,
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
