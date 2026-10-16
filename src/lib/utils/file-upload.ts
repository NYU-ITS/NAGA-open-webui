const IMAGE_FILE_EXTENSIONS = new Set([
	'png',
	'jpg',
	'jpeg',
	'jpe',
	'jfif',
	'gif',
	'webp',
	'avif',
	'bmp',
	'svg',
	'heic',
	'heif',
	'apng',
	'ico',
	'cur',
	'jp2',
	'j2k',
	'jpf',
	'jpm',
	'jpx',
	'jxl',
	'psd',
	'raw',
	'dng',
	'cr2',
	'cr3',
	'nef',
	'arw',
	'orf',
	'rw2',
	'pbm',
	'pgm',
	'ppm',
	'pnm',
	'tif',
	'tiff'
]);

export const STANDALONE_IMAGE_ACCEPT = 'image/png,image/jpeg';

const getFileExtension = (name: string) => name.split('.').at(-1)?.toLowerCase() ?? '';

export const normalizeStandaloneImageUpload = (file: File) => {
	const declaredMimeType = (file.type || '').split(';')[0].trim().toLowerCase();
	const extension = getFileExtension(file.name);
	const isImageCandidate =
		declaredMimeType.startsWith('image/') || IMAGE_FILE_EXTENSIONS.has(extension);

	if (!isImageCandidate) {
		return {
			file,
			isStandaloneImage: false,
			mimeType: declaredMimeType || 'application/octet-stream',
			unsupported: false
		};
	}

	let mimeType: string | null = null;
	if (declaredMimeType === 'image/png' && (!extension || extension === 'png')) {
		mimeType = declaredMimeType;
	} else if (
		declaredMimeType === 'image/jpeg' &&
		(!extension || ['jpg', 'jpeg', 'jpe', 'jfif'].includes(extension))
	) {
		mimeType = declaredMimeType;
	} else if (
		['image/jpg', 'image/pjpeg'].includes(declaredMimeType) &&
		(!extension || ['jpg', 'jpeg', 'jpe', 'jfif'].includes(extension))
	) {
		mimeType = 'image/jpeg';
	} else if (declaredMimeType === 'image/x-png' && (!extension || extension === 'png')) {
		mimeType = 'image/png';
	} else if (!declaredMimeType || declaredMimeType === 'application/octet-stream') {
		if (extension === 'png') {
			mimeType = 'image/png';
		} else if (['jpg', 'jpeg', 'jpe', 'jfif'].includes(extension)) {
			mimeType = 'image/jpeg';
		}
	}

	if (!mimeType) {
		return {
			file,
			isStandaloneImage: true,
			mimeType: declaredMimeType,
			unsupported: true
		};
	}

	return {
		file:
			file.type === mimeType
				? file
				: new File([file], file.name, { type: mimeType, lastModified: file.lastModified }),
		isStandaloneImage: true,
		mimeType,
		unsupported: false
	};
};

type PublicVisualSummary = {
	figure_count: number;
	table_image_count: number;
	image_chunk_count: number;
	text_chunk_count: number;
};

export type StandaloneImageDescriptor = {
	type: 'image';
	id: string;
	name: string;
	mime_type: 'image/png' | 'image/jpeg';
	size: number;
	status: string;
	processing_status: string;
	collection_name: string;
	context?: string;
	processing_warnings?: string[];
	visual_summary?: PublicVisualSummary;
};

const normalizeCount = (value: unknown) => {
	const count = Number(value);
	return Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
};

const normalizeVisualSummary = (value: unknown): PublicVisualSummary | null => {
	if (!value || typeof value !== 'object' || Array.isArray(value)) {
		return null;
	}

	const summary = value as Record<string, unknown>;
	return {
		figure_count: normalizeCount(summary.figure_count),
		table_image_count: normalizeCount(summary.table_image_count),
		image_chunk_count: normalizeCount(summary.image_chunk_count),
		text_chunk_count: normalizeCount(summary.text_chunk_count)
	};
};

export const serializeStandaloneImageDescriptor = (
	attachment: any
): StandaloneImageDescriptor | null => {
	const id = String(attachment?.id ?? '').trim();
	if (attachment?.type !== 'image' || !id) {
		return null;
	}

	const metadata = attachment.meta ?? {};
	const name =
		String(attachment.name ?? attachment.filename ?? metadata.name ?? '').trim() || 'Image';
	const extension = getFileExtension(name);
	const dataUrlMimeType =
		typeof attachment.url === 'string'
			? (attachment.url.match(/^data:(image\/[^;,]+)/i)?.[1] ?? '')
			: '';
	const inferredMimeType =
		extension === 'png'
			? 'image/png'
			: ['jpg', 'jpeg', 'jpe', 'jfif'].includes(extension)
				? 'image/jpeg'
				: '';
	const declaredMimeType = String(
		attachment.mime_type || attachment.mime || metadata.content_type || metadata.mime_type || ''
	)
		.split(';', 1)[0]
		.trim()
		.toLowerCase();
	const rawMimeType = String(
		declaredMimeType && declaredMimeType !== 'application/octet-stream'
			? declaredMimeType
			: dataUrlMimeType || inferredMimeType
	)
		.split(';', 1)[0]
		.trim()
		.toLowerCase();
	const mimeType = ['image/jpg', 'image/pjpeg'].includes(rawMimeType)
		? 'image/jpeg'
		: rawMimeType === 'image/x-png'
			? 'image/png'
			: rawMimeType;
	if (mimeType !== 'image/png' && mimeType !== 'image/jpeg') {
		return null;
	}

	const warnings = attachment.processing_warnings ?? metadata.processing_warnings;
	const processingWarnings = Array.isArray(warnings)
		? [
				...new Set(
					warnings
						.filter((warning: unknown): warning is string => typeof warning === 'string')
						.map((warning) => warning.trim())
						.filter(Boolean)
				)
			]
		: [];
	const visualSummary = normalizeVisualSummary(
		attachment.visual_summary ?? metadata.visual_summary
	);
	const rawProcessingStatus =
		String(
			attachment.processing_status ??
				metadata.processing_status ??
				attachment.status ??
				'completed'
		).trim() || 'completed';
	const processingStatus = ['uploaded', 'ready'].includes(rawProcessingStatus)
		? 'completed'
		: rawProcessingStatus;
	const rawSize = Number(attachment.size ?? metadata.size ?? 0);
	const status =
		processingStatus === 'completed'
			? 'uploaded'
			: processingStatus === 'error'
				? 'error'
				: ['not_started', 'pending', 'processing'].includes(processingStatus)
					? 'processing'
					: String(attachment.status ?? '').trim() || processingStatus;

	return {
		type: 'image',
		id,
		name,
		mime_type: mimeType,
		size: Number.isFinite(rawSize) && rawSize > 0 ? Math.floor(rawSize) : 0,
		status,
		processing_status: processingStatus,
		collection_name: String(attachment.collection_name ?? metadata.collection_name ?? ''),
		...(attachment.context ? { context: attachment.context } : {}),
		...(processingWarnings.length ? { processing_warnings: processingWarnings } : {}),
		...(visualSummary ? { visual_summary: visualSummary } : {})
	};
};
