<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { v4 as uuidv4 } from 'uuid';
	import { createPicker } from '$lib/utils/google-drive-picker';
	import { pickAndDownloadFile } from '$lib/utils/onedrive-file-picker';

	import { onMount, tick, getContext, createEventDispatcher, onDestroy } from 'svelte';
	const dispatch = createEventDispatcher();

	import {
		type Model,
		mobile,
		settings,
		showSidebar,
		models,
		config,
		showCallOverlay,
		activeCallMode,
		tools,
		user as _user,
		showControls,
		TTSWorker
	} from '$lib/stores';

	import { createMessagesList, findWordIndices } from '$lib/utils';
	import { normalizeStandaloneImageUpload } from '$lib/utils/file-upload';
	import { uploadFile, getFileProcessingStatus } from '$lib/apis/files';
	import { processFile } from '$lib/apis/retrieval';
	import { generateAutoCompletion } from '$lib/apis';
	import { deleteFileById } from '$lib/apis/files';

	import { WEBUI_BASE_URL, WEBUI_API_BASE_URL, PASTED_TEXT_CHARACTER_LIMIT } from '$lib/constants';

	import InputMenu from './MessageInput/InputMenu.svelte';
	import VoiceRecording from './MessageInput/VoiceRecording.svelte';
	import FilesOverlay from './MessageInput/FilesOverlay.svelte';
	import Commands from './MessageInput/Commands.svelte';
	import CallModeModal from './MessageInput/CallModeModal.svelte';

	import RichTextInput from '../common/RichTextInput.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import FileItem from '../common/FileItem.svelte';
	import Image from '../common/Image.svelte';

	import XMark from '../icons/XMark.svelte';
	import Headphone from '../icons/Headphone.svelte';
	import GlobeAlt from '../icons/GlobeAlt.svelte';
	import Photo from '../icons/Photo.svelte';
	import CommandLine from '../icons/CommandLine.svelte';
	import { KokoroWorker } from '$lib/workers/KokoroWorker';

	const i18n = getContext('i18n');

	export let transparentBackground = false;

	export let onChange: Function = () => {};
	export let createMessagePair: Function;
	export let stopResponse: Function;

	export let autoScroll = false;

	export let atSelectedModel: Model | undefined = undefined;
	export let selectedModels: [''];

	let selectedModelIds = [];
	$: selectedModelIds = atSelectedModel !== undefined ? [atSelectedModel.id] : selectedModels;

	export let history;

	export let prompt = '';
	export let files = [];

	export let selectedToolIds = [];

	export let imageGenerationEnabled = false;
	export let webSearchEnabled = false;
	export let codeInterpreterEnabled = false;

	$: onChange({
		prompt,
		files,
		selectedToolIds,
		imageGenerationEnabled,
		webSearchEnabled
	});

	let loaded = false;
	let recording = false;
	let showCallModeModal = false;

	let chatInputContainerElement;
	let chatInputElement;

	let filesInputElement;
	let commandsElement;

	let inputFiles;
	let dragged = false;

	const FILE_PROCESSING_POLL_INTERVAL_MS = 2000;
	const FILE_PROCESSING_POLL_TIMEOUT_MS = 300000;

	const attachmentPreviewUrls = new Map<string, string>();
	const processingPollIntervals = new Map<string, number>();
	const processingPollTimeouts = new Map<string, number>();
	const statusRefreshes = new Set<string>();
	const removedAttachmentIds = new Set<string>();
	const transientImageUploads = new Set<string>();

	let attachmentSubmissionBlocked = false;
	let standaloneImageNeedsPrompt = false;
	let inputCanSubmit = false;

	$: attachmentSubmissionBlocked = files.some((file) =>
		(file?.type === 'image' && !file?.id) ||
		['uploading', 'not_started', 'pending', 'processing', 'error'].some(
			(status) => status === file?.status || status === file?.processing_status
		)
	);
	$: standaloneImageNeedsPrompt =
		files.some((file) => file?.type === 'image') && String(prompt ?? '').trim().length === 0;
	$: inputCanSubmit =
		(String(prompt ?? '').trim().length > 0 || files.length > 0) &&
		!attachmentSubmissionBlocked &&
		!standaloneImageNeedsPrompt;

	$: {
		const activeItemIds = new Set(files.map((file) => file?.itemId).filter(Boolean));
		for (const itemId of attachmentPreviewUrls.keys()) {
			if (!activeItemIds.has(itemId)) {
				releaseAttachmentPreview(itemId);
			}
		}
		for (const itemId of processingPollIntervals.keys()) {
			if (!activeItemIds.has(itemId)) clearProcessingPoll(itemId);
		}
	}

	export let placeholder = '';

	const startCallWithMode = async (mode: 'live_text' | 'transcript_at_end') => {
		if ($settings.audio?.tts?.engine === 'browser-kokoro') {
			if (!$TTSWorker) {
				await TTSWorker.set(
					new KokoroWorker({
						dtype: $settings.audio?.tts?.engineConfig?.dtype ?? 'fp32'
					})
				);
				await $TTSWorker.init();
			}
		}
		activeCallMode.set(mode);
		showCallOverlay.set(true);
		showControls.set(true);
	};

	const scrollToBottom = () => {
		const element = document.getElementById('messages-container');
		element.scrollTo({
			top: element.scrollHeight,
			behavior: 'smooth'
		});
	};

	function releaseAttachmentPreview(itemId: string) {
		const previewUrl = attachmentPreviewUrls.get(itemId);
		if (previewUrl) {
			URL.revokeObjectURL(previewUrl);
			attachmentPreviewUrls.delete(itemId);
		}
	}

	const getImagePreviewUrl = (file: { itemId?: string; id?: string; url?: string }) =>
		(file?.itemId ? attachmentPreviewUrls.get(file.itemId) : undefined) ??
		(file?.id
			? `${WEBUI_API_BASE_URL}/files/${encodeURIComponent(file.id)}/content`
			: (file?.url ?? ''));

	function clearProcessingPoll(itemId: string) {
		const interval = processingPollIntervals.get(itemId);
		if (interval !== undefined) {
			window.clearInterval(interval);
			processingPollIntervals.delete(itemId);
		}

		const timeout = processingPollTimeouts.get(itemId);
		if (timeout !== undefined) {
			window.clearTimeout(timeout);
			processingPollTimeouts.delete(itemId);
		}
	}

	const normalizeProcessingWarnings = (warnings: unknown): string[] =>
		Array.isArray(warnings)
			? warnings.filter(
					(warning: unknown): warning is string => typeof warning === 'string'
				)
			: [];

	const applyProcessingStatus = (fileItem, statusResponse) => {
		const processingStatus = statusResponse?.processing_status;
		fileItem.processing_status = processingStatus ?? fileItem.processing_status;
		fileItem.collection_name = statusResponse?.collection_name ?? fileItem.collection_name;
		fileItem.processing_error_code =
			statusResponse?.processing_error_code ?? fileItem.processing_error_code;
		fileItem.error = statusResponse?.processing_error ?? fileItem.error;

		if (Array.isArray(statusResponse?.processing_warnings)) {
			fileItem.processing_warnings = normalizeProcessingWarnings(
				statusResponse.processing_warnings
			);
		}
		if (statusResponse?.visual_summary) {
			fileItem.visual_summary = statusResponse.visual_summary;
		}

		if (processingStatus === 'completed') {
			fileItem.status = 'uploaded';
			fileItem.polling_timed_out = false;
			fileItem.error = '';
			fileItem.processing_error_code = null;
		} else if (processingStatus === 'error') {
			fileItem.status = 'error';
			fileItem.error = fileItem.error || 'Processing failed';
		} else if (['not_started', 'pending', 'processing'].includes(processingStatus)) {
			fileItem.status = 'processing';
		}

		files = files;
		return processingStatus;
	};

	const refreshFileStatus = async (fileItem, notify = true) => {
		if (!fileItem?.id || statusRefreshes.has(fileItem.itemId)) {
			return fileItem?.processing_status ?? null;
		}

		statusRefreshes.add(fileItem.itemId);
		fileItem.status_refreshing = true;
		files = files;
		try {
			const statusResponse = await getFileProcessingStatus(localStorage.token, fileItem.id);
			const processingStatus = applyProcessingStatus(fileItem, statusResponse);

			if (processingStatus === 'completed' || processingStatus === 'error') {
				clearProcessingPoll(fileItem.itemId);
			}

			if (notify) {
				if (processingStatus === 'completed') {
					toast.success($i18n.t('File processing completed and ready for queries'));
				} else if (processingStatus === 'error') {
					toast.error(
						$i18n.t('File processing failed: {{error}}', {
							error: fileItem.error || 'Unknown error'
						})
					);
				} else {
					toast.info($i18n.t('File is still processing.'));
				}
			}

			return processingStatus;
		} catch (error) {
			console.error('Error refreshing file processing status:', error);
			if (notify) {
				toast.error($i18n.t('Unable to refresh file processing status.'));
			}
			return null;
		} finally {
			statusRefreshes.delete(fileItem.itemId);
			fileItem.status_refreshing = false;
			files = files;
		}
	};

	const startProcessingPoll = (fileItem) => {
		clearProcessingPoll(fileItem.itemId);
		fileItem.status = 'processing';
		fileItem.polling_timed_out = false;
		files = files;

		const interval = window.setInterval(async () => {
			const previousStatus = fileItem.processing_status;
			const processingStatus = await refreshFileStatus(fileItem, false);
			if (processingStatus === 'completed' && previousStatus !== 'completed') {
				toast.success($i18n.t('File processing completed and ready for queries'));
			} else if (processingStatus === 'error' && previousStatus !== 'error') {
				toast.error(
					$i18n.t('File processing failed: {{error}}', {
						error: fileItem.error || 'Unknown error'
					})
				);
			}
		}, FILE_PROCESSING_POLL_INTERVAL_MS);
		processingPollIntervals.set(fileItem.itemId, interval);

		const timeout = window.setTimeout(() => {
			clearProcessingPoll(fileItem.itemId);
			if (fileItem.status === 'processing') {
				fileItem.polling_timed_out = true;
				files = files;
				toast.warning(
					$i18n.t('File is still processing. Refresh its status before submitting.')
				);
			}
		}, FILE_PROCESSING_POLL_TIMEOUT_MS);
		processingPollTimeouts.set(fileItem.itemId, timeout);
	};

	const retryFileProcessing = async (fileItem) => {
		if (!fileItem?.id) return;

		fileItem.status = 'processing';
		fileItem.processing_status = 'pending';
		fileItem.error = '';
		fileItem.processing_error_code = null;
		fileItem.polling_timed_out = false;
		files = files;

		try {
			const retryResult = await processFile(
				localStorage.token,
				fileItem.id,
				fileItem.collection_name || null
			);
			if (!retryResult || retryResult.status === 'error') {
				fileItem.status = 'error';
				fileItem.processing_status = 'error';
				fileItem.processing_error_code = retryResult?.processing_error_code ?? null;
				fileItem.error = retryResult?.error || $i18n.t('Unable to retry file processing.');
				files = files;
				toast.error(fileItem.error);
				return;
			}
			startProcessingPoll(fileItem);
			await refreshFileStatus(fileItem, false);
		} catch (error) {
			fileItem.status = 'error';
			fileItem.processing_status = 'error';
			fileItem.error = `${error}`;
			files = files;
			toast.error($i18n.t('Unable to retry file processing.'));
		}
	};

	const removeAttachment = async (fileItem) => {
		if (fileItem.itemId) removedAttachmentIds.add(fileItem.itemId);
		clearProcessingPoll(fileItem.itemId);
		releaseAttachmentPreview(fileItem.itemId);
		files = files.filter((item) => item !== fileItem);

		if (fileItem?.id && fileItem.type !== 'collection' && !fileItem?.collection) {
			await deleteFileById(localStorage.token, fileItem.id).catch((error) => {
				console.error('Error deleting attachment:', error);
				toast.error($i18n.t('Unable to delete the uploaded file.'));
			});
			if (fileItem.itemId) removedAttachmentIds.delete(fileItem.itemId);
		}
	};

	const formatVisualSummary = (summary) => {
		if (!summary) return '';

		return [
			`Figures: ${Number(summary.figure_count ?? 0)}`,
			`Image tables: ${Number(summary.table_image_count ?? 0)}`,
			`Image chunks: ${Number(summary.image_chunk_count ?? 0)}`,
			`Text chunks: ${Number(summary.text_chunk_count ?? 0)}`
		].join(', ');
	};
	const formatProcessingWarning = (warning: string) =>
		warning.includes('_')
			? warning.replaceAll('_', ' ').replace(/^./, (character) => character.toUpperCase())
			: warning;

	const screenCaptureHandler = async () => {
		let mediaStream: MediaStream | null = null;
		let video: HTMLVideoElement | null = null;
		try {
			const hasPermission =
				$_user?.role === 'admin' || ($_user?.permissions?.chat?.file_upload ?? true);
			if (!$_user || !hasPermission) {
				toast.error($i18n.t('You do not have permission to upload files.'));
				return;
			}

			mediaStream = await navigator.mediaDevices.getDisplayMedia({
				video: { cursor: 'never' },
				audio: false
			});
			video = document.createElement('video');
			video.srcObject = mediaStream;
			await video.play();

			const canvas = document.createElement('canvas');
			canvas.width = video.videoWidth;
			canvas.height = video.videoHeight;
			const context = canvas.getContext('2d');
			if (!context) throw new Error('Unable to create screen capture');
			context.drawImage(video, 0, 0, canvas.width, canvas.height);

			const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
			if (!blob) throw new Error('Unable to encode screen capture');

			window.focus();
			const timestamp = new Date().toISOString().replaceAll(':', '-');
			await uploadFileHandler(
				new File([blob], `Screen Capture ${timestamp}.png`, { type: 'image/png' })
			);
		} catch (error) {
			console.error('Error capturing screen:', error);
		} finally {
			mediaStream?.getTracks().forEach((track) => track.stop());
			if (video) video.srcObject = null;
		}
	};

	const uploadFileHandler = async (sourceFile: File, fullContext: boolean = false) => {
		// Check if user is loaded and has permissions
		if (!$_user) {
			toast.error($i18n.t('User not loaded. Please refresh the page.'));
			return null;
		}

		// Admin always has permission, otherwise check permissions
		const hasPermission = $_user.role === 'admin' || ($_user?.permissions?.chat?.file_upload ?? true);
		if (!hasPermission) {
			toast.error($i18n.t('You do not have permission to upload files.'));
			return null;
		}
		if (
			($config?.file?.max_size ?? null) !== null &&
			sourceFile.size > ($config?.file?.max_size ?? 0) * 1024 * 1024
		) {
			toast.error(
				$i18n.t('File size should not exceed {{maxSize}} MB.', {
					maxSize: $config?.file?.max_size
				})
			);
			return null;
		}

		const normalizedUpload = normalizeStandaloneImageUpload(sourceFile);
		if (normalizedUpload.unsupported) {
			toast.error($i18n.t('Only PNG and JPEG image uploads are supported.'));
			return null;
		}

		const file = normalizedUpload.file;
		const isStandaloneImage = normalizedUpload.isStandaloneImage;

		const tempItemId = uuidv4();
		const fileItem: any = {
			type: isStandaloneImage ? 'image' : 'file',
			id: null,
			url: '',
			name: file.name,
			mime_type: normalizedUpload.mimeType,
			collection_name: '',
			status: 'uploading',
			processing_status: 'uploading',
			size: file.size,
			error: '',
			itemId: tempItemId,
			...(fullContext ? { context: 'full' } : {})
		};
		if (!isStandaloneImage) {
			fileItem.file = '';
		} else {
			attachmentPreviewUrls.set(tempItemId, URL.createObjectURL(file));
		}

		if (fileItem.size == 0) {
			releaseAttachmentPreview(tempItemId);
			toast.error($i18n.t('You cannot upload an empty file.'));
			return null;
		}

		files = [...files, fileItem];

		try {
			// During the file upload, file content is automatically extracted.
			const uploadedFile = await uploadFile(localStorage.token, file);

			if (uploadedFile) {
				if (removedAttachmentIds.has(tempItemId)) {
					await deleteFileById(localStorage.token, uploadedFile.id).catch(() => null);
					return null;
				}

				if (uploadedFile.error) {
					toast.warning(uploadedFile.error);
				}

				const canonicalMimeType = String(
					uploadedFile?.meta?.content_type || fileItem.mime_type || ''
				)
					.split(';', 1)[0]
					.trim()
					.toLowerCase();
				const canonicalStandaloneImage = ['image/png', 'image/jpeg'].includes(
					canonicalMimeType
				);
				fileItem.type = canonicalStandaloneImage ? 'image' : 'file';
				if (canonicalStandaloneImage) {
					delete fileItem.file;
				} else {
					fileItem.file = uploadedFile;
					releaseAttachmentPreview(tempItemId);
				}
				fileItem.id = uploadedFile.id;
				fileItem.mime_type = canonicalMimeType || fileItem.mime_type;
				fileItem.size = uploadedFile?.meta?.size ?? fileItem.size;
				fileItem.collection_name =
					uploadedFile?.meta?.collection_name || uploadedFile?.collection_name;
				fileItem.url = `${WEBUI_API_BASE_URL}/files/${encodeURIComponent(uploadedFile.id)}${
					canonicalStandaloneImage ? '/content' : ''
				}`;
				fileItem.processing_error_code = uploadedFile?.meta?.processing_error_code ?? null;
				fileItem.processing_warnings = normalizeProcessingWarnings(
					uploadedFile?.meta?.processing_warnings
				);
				fileItem.visual_summary = uploadedFile?.meta?.visual_summary ?? null;

				// Check processing status from upload response
				const processingStatus = uploadedFile?.meta?.processing_status;
				fileItem.processing_status = processingStatus;

				// If processing is pending or in progress, keep showing processing state
				if (
					processingStatus === 'not_started' ||
					processingStatus === 'pending' ||
					processingStatus === 'processing'
				) {
					startProcessingPoll(fileItem);
				} else if (processingStatus === 'completed') {
					fileItem.status = 'uploaded';
				} else if (processingStatus === 'error') {
					fileItem.status = 'error';
					fileItem.error = uploadedFile?.meta?.processing_error || 'Processing failed';
					toast.error($i18n.t('File processing failed: {{error}}', { error: fileItem.error }));
				} else if (canonicalStandaloneImage) {
					// Standalone images must be indexed before they can be submitted.
					fileItem.processing_status = 'processing';
					startProcessingPoll(fileItem);
				} else {
					// No status or unknown - assume uploaded (legacy behavior)
					fileItem.status = 'uploaded';
				}

				files = files;
			} else {
				files = files.filter((item) => item?.itemId !== tempItemId);
				releaseAttachmentPreview(tempItemId);
			}
		} catch (e) {
			if (!removedAttachmentIds.has(tempItemId)) {
				toast.error(`${e}`);
			}
			files = files.filter((item) => item?.itemId !== tempItemId);
			releaseAttachmentPreview(tempItemId);
		} finally {
			removedAttachmentIds.delete(tempItemId);
		}
	};

	const uploadTransientImageAttachment = async (attachment: any) => {
		const sourceUrl = typeof attachment?.url === 'string' ? attachment.url : '';
		const normalizedSourceUrl = sourceUrl.toLowerCase();
		attachment.itemId = attachment.itemId || uuidv4();
		if (attachment?.id || transientImageUploads.has(attachment.itemId)) {
			return;
		}
		if (
			!(normalizedSourceUrl.startsWith('blob:') || normalizedSourceUrl.startsWith('data:image/'))
		) {
			if (attachment.status === 'error' && attachment.processing_status === 'error') {
				return;
			}
			attachment.status = 'error';
			attachment.processing_status = 'error';
			attachment.error = $i18n.t('Unable to upload the selected image.');
			attachment.url = '';
			files = files;
			return;
		}

		transientImageUploads.add(attachment.itemId);
		attachment.status = 'uploading';
		attachment.processing_status = 'uploading';
		files = files;

		try {
			const response = await fetch(sourceUrl);
			if (!response.ok) {
				throw new Error('Unable to read the selected image');
			}
			const blob = await response.blob();
			if (!files.includes(attachment)) {
				return;
			}

			const dataUrlMimeType = sourceUrl.match(/^data:(image\/[^;,]+)/i)?.[1] ?? '';
			const mimeType = (blob.type || dataUrlMimeType).split(';', 1)[0].toLowerCase();
			if (!mimeType.startsWith('image/')) {
				throw new Error('Unable to determine the selected image type');
			}
			const extension =
				mimeType === 'image/jpeg'
					? 'jpg'
					: mimeType === 'image/png'
						? 'png'
						: mimeType.split('/').at(-1) || 'img';
			files = files.filter((item) => item !== attachment);
			await uploadFileHandler(
				new File([blob], `Pasted Image ${Date.now()}.${extension}`, { type: mimeType })
			);
		} catch (error) {
			if (files.includes(attachment)) {
				attachment.status = 'error';
				attachment.processing_status = 'error';
				attachment.error = $i18n.t('Unable to upload the selected image.');
				attachment.url = '';
				files = files;
				toast.error(attachment.error);
			}
		} finally {
			if (normalizedSourceUrl.startsWith('blob:')) {
				URL.revokeObjectURL(sourceUrl);
			}
			transientImageUploads.delete(attachment.itemId);
		}
	};

	$: {
		for (const attachment of files) {
			if (attachment?.type === 'image' && !attachment?.id) {
				void uploadTransientImageAttachment(attachment);
			}
		}
	}

	const inputFilesHandler = async (inputFiles) => {
		inputFiles.forEach((file: File) => {
			void uploadFileHandler(file);
		});
	};

	const pasteHandler = async (event: ClipboardEvent) => {
		const clipboardData = event.clipboardData || (window as any).clipboardData;
		if (!clipboardData?.items) return;

		for (const item of clipboardData.items) {
			if (item.type.startsWith('image/')) {
				event.preventDefault();
				const blob = item.getAsFile();
				if (!blob) continue;

				const extension = blob.type === 'image/jpeg' ? 'jpg' : blob.type.split('/').at(-1) || 'png';
				const file =
					blob instanceof File && blob.name
						? blob
						: new File([blob], `Pasted Image ${Date.now()}.${extension}`, { type: blob.type });
				await uploadFileHandler(file);
			} else if (item.type === 'text/plain' && ($settings?.largeTextAsFile ?? false)) {
				const text = clipboardData.getData('text/plain');
				if (text.length > PASTED_TEXT_CHARACTER_LIMIT) {
					event.preventDefault();
					const blob = new Blob([text], { type: 'text/plain' });
					const file = new File([blob], `Pasted_Text_${Date.now()}.txt`, {
						type: 'text/plain'
					});
					await uploadFileHandler(file, true);
				}
			}
		}
	};

	const handleKeyDown = (event: KeyboardEvent) => {
		if (event.key === 'Escape') {
			dragged = false;
		}
	};

	const onDragOver = (e) => {
		e.preventDefault();

		// Check if a file is being dragged.
		if (e.dataTransfer?.types?.includes('Files')) {
			dragged = true;
		} else {
			dragged = false;
		}
	};

	const onDragLeave = () => {
		dragged = false;
	};

	const onDrop = async (e) => {
		e.preventDefault();

		if (e.dataTransfer?.files) {
			const inputFiles = Array.from(e.dataTransfer?.files);
			if (inputFiles && inputFiles.length > 0) {
				inputFilesHandler(inputFiles);
			}
		}

		dragged = false;
	};

	onMount(async () => {
		files = files.map((file) => (file?.itemId ? file : { ...file, itemId: uuidv4() }));
		loaded = true;

		window.setTimeout(() => {
			const chatInput = document.getElementById('chat-input');
			chatInput?.focus();
		}, 0);

		window.addEventListener('keydown', handleKeyDown);

		await tick();

		const dropzoneElement = document.getElementById('chat-container');

		dropzoneElement?.addEventListener('dragover', onDragOver);
		dropzoneElement?.addEventListener('drop', onDrop);
		dropzoneElement?.addEventListener('dragleave', onDragLeave);
	});

	onDestroy(() => {
		window.removeEventListener('keydown', handleKeyDown);
		for (const itemId of processingPollIntervals.keys()) {
			clearProcessingPoll(itemId);
		}
		for (const itemId of attachmentPreviewUrls.keys()) {
			releaseAttachmentPreview(itemId);
		}

		const dropzoneElement = document.getElementById('chat-container');

		if (dropzoneElement) {
			dropzoneElement?.removeEventListener('dragover', onDragOver);
			dropzoneElement?.removeEventListener('drop', onDrop);
			dropzoneElement?.removeEventListener('dragleave', onDragLeave);
		}
	});
</script>

<FilesOverlay show={dragged} />

<CallModeModal
	bind:show={showCallModeModal}
	on:start={async (e) => {
		await startCallWithMode(e.detail.mode);
	}}
/>

{#if loaded}
	<div class="w-full font-primary">
		<div class=" mx-auto inset-x-0 bg-transparent flex justify-center">
			<div
				class="flex flex-col px-3 {($settings?.widescreenMode ?? null)
					? 'max-w-full'
					: 'max-w-6xl'} w-full"
			>
				<div class="relative">
					{#if autoScroll === false && history?.currentId}
						<div
							class=" absolute -top-12 left-0 right-0 flex justify-center z-30 pointer-events-none"
						>
							<button
								class=" bg-white border border-gray-100 dark:border-none dark:bg-white/20 p-1.5 rounded-full pointer-events-auto"
								on:click={() => {
									autoScroll = true;
									scrollToBottom();
								}}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="currentColor"
									class="w-5 h-5"
								>
									<path
										fill-rule="evenodd"
										d="M10 3a.75.75 0 01.75.75v10.638l3.96-4.158a.75.75 0 111.08 1.04l-5.25 5.5a.75.75 0 01-1.08 0l-5.25-5.5a.75.75 0 111.08-1.04l3.96 4.158V3.75A.75.75 0 0110 3z"
										clip-rule="evenodd"
									/>
								</svg>
							</button>
						</div>
					{/if}
				</div>

				<div class="w-full relative">
					{#if atSelectedModel !== undefined || selectedToolIds.length > 0 || webSearchEnabled || ($settings?.webSearch ?? false) === 'always' || imageGenerationEnabled || codeInterpreterEnabled}
						<div
							class="px-3 pb-0.5 pt-1.5 text-left w-full flex flex-col absolute bottom-0 left-0 right-0 bg-linear-to-t from-white dark:from-gray-900 z-10"
						>
							{#if selectedToolIds.length > 0}
								<div class="flex items-center justify-between w-full">
									<div class="flex items-center gap-2.5 text-sm dark:text-gray-500">
										<div class="pl-1">
											<span class="relative flex size-2">
												<span
													class="animate-ping absolute inline-flex h-full w-full rounded-full bg-yellow-400 opacity-75"
												/>
												<span class="relative inline-flex rounded-full size-2 bg-yellow-500" />
											</span>
										</div>
										<div class="  text-ellipsis line-clamp-1 flex">
											{#each selectedToolIds.map((id) => {
												return $tools ? $tools.find((t) => t.id === id) : { id: id, name: id };
											}) as tool, toolIdx (toolIdx)}
												<Tooltip
													content={tool?.meta?.description ?? ''}
													className=" {toolIdx !== 0 ? 'pl-0.5' : ''} shrink-0"
													placement="top"
												>
													{tool.name}
												</Tooltip>

												{#if toolIdx !== selectedToolIds.length - 1}
													<span>, </span>
												{/if}
											{/each}
										</div>
									</div>
								</div>
							{/if}

							{#if webSearchEnabled || ($config?.features?.enable_web_search && ($settings?.webSearch ?? false)) === 'always'}
								<div class="flex items-center justify-between w-full">
									<div class="flex items-center gap-2.5 text-sm dark:text-gray-500">
										<div class="pl-1">
											<span class="relative flex size-2">
												<span
													class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"
												/>
												<span class="relative inline-flex rounded-full size-2 bg-blue-500" />
											</span>
										</div>
										<div class=" translate-y-[0.5px]">{$i18n.t('Search the internet')}</div>
									</div>
								</div>
							{/if}

							{#if imageGenerationEnabled}
								<div class="flex items-center justify-between w-full">
									<div class="flex items-center gap-2.5 text-sm dark:text-gray-500">
										<div class="pl-1">
											<span class="relative flex size-2">
												<span
													class="animate-ping absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-75"
												/>
												<span class="relative inline-flex rounded-full size-2 bg-teal-500" />
											</span>
										</div>
										<div class=" translate-y-[0.5px]">{$i18n.t('Generate an image')}</div>
									</div>
								</div>
							{/if}

							{#if codeInterpreterEnabled}
								<div class="flex items-center justify-between w-full">
									<div class="flex items-center gap-2.5 text-sm dark:text-gray-500">
										<div class="pl-1">
											<span class="relative flex size-2">
												<span
													class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"
												/>
												<span class="relative inline-flex rounded-full size-2 bg-green-500" />
											</span>
										</div>
										<div class=" translate-y-[0.5px]">{$i18n.t('Execute code for analysis')}</div>
									</div>
								</div>
							{/if}

							{#if atSelectedModel !== undefined}
								<div class="flex items-center justify-between w-full">
									<div class="pl-[1px] flex items-center gap-2 text-sm dark:text-gray-500">
										<img
											crossorigin="anonymous"
											alt="model profile"
											class="size-3.5 max-w-[28px] object-cover rounded-full"
											src={$models.find((model) => model.id === atSelectedModel.id)?.info?.meta
												?.profile_image_url ??
												($i18n.language === 'dg-DG'
													? `/doge.png`
													: `${WEBUI_BASE_URL}/static/favicon.png`)}
										/>
										<div class="translate-y-[0.5px]">
											Talking to <span class=" font-medium">{atSelectedModel.name}</span>
										</div>
									</div>
									<div>
										<button
											class="flex items-center dark:text-gray-500"
											on:click={() => {
												atSelectedModel = undefined;
											}}
										>
											<XMark />
										</button>
									</div>
								</div>
							{/if}
						</div>
					{/if}

					<Commands
						bind:this={commandsElement}
						bind:prompt
						bind:files
						on:upload={(e) => {
							dispatch('upload', e.detail);
						}}
						on:select={(e) => {
							const data = e.detail;

							if (data?.type === 'model') {
								atSelectedModel = data.data;
							}

							const chatInputElement = document.getElementById('chat-input');
							chatInputElement?.focus();
						}}
					/>
				</div>
			</div>
		</div>

		<div class="{transparentBackground ? 'bg-transparent' : 'bg-white dark:bg-gray-900'} ">
			<div
				class="{($settings?.widescreenMode ?? null)
					? 'max-w-full'
					: 'max-w-6xl'} px-2.5 mx-auto inset-x-0"
			>
				<div class="">
					<input
						bind:this={filesInputElement}
						bind:files={inputFiles}
						type="file"
						hidden
						multiple
						on:change={async () => {
							if (inputFiles && inputFiles.length > 0) {
								const _inputFiles = Array.from(inputFiles);
								inputFilesHandler(_inputFiles);
							} else {
								toast.error($i18n.t(`File not found.`));
							}

							filesInputElement.value = '';
						}}
					/>

					{#if recording}
						<VoiceRecording
							bind:recording
							on:cancel={async () => {
								recording = false;

								await tick();
								document.getElementById('chat-input')?.focus();
							}}
							on:confirm={async (e) => {
								const { text, filename } = e.detail;
								prompt = `${prompt}${text} `;

								recording = false;

								await tick();
								document.getElementById('chat-input')?.focus();

								if (($settings?.speechAutoSend ?? false) && inputCanSubmit) {
									dispatch('submit', prompt);
								}
							}}
						/>
					{:else}
						<form
							class="w-full flex gap-1.5"
							on:submit|preventDefault={() => {
								if (inputCanSubmit) dispatch('submit', prompt);
							}}
						>
							<div
								class="flex-1 flex flex-col relative w-full rounded-3xl px-1 bg-gray-600/5 dark:bg-gray-400/5 dark:text-gray-100"
								dir={$settings?.chatDirection ?? 'LTR'}
							>
								{#if files.length > 0}
									<div class="mx-2 mt-2.5 -mb-1 flex items-center flex-wrap gap-2">
										{#each files as file}
											<div class="flex flex-col gap-1">
												{#if file.type === 'image'}
													<div class="relative group w-fit">
														<div class="relative flex items-center">
															<Image
																src={getImagePreviewUrl(file)}
																alt="input"
																imageClassName=" size-14 rounded-xl object-cover"
															/>
															{#if file.status === 'uploading' || file.status === 'processing'}
																<div
																	class="absolute inset-0 flex items-center justify-center rounded-xl bg-black/55 px-1 text-center text-[10px] font-medium text-white pointer-events-none"
																>
																	{file.status === 'uploading'
																		? $i18n.t('Uploading')
																		: $i18n.t('Processing')}
																</div>
															{/if}
														</div>
														<div class=" absolute -top-1 -right-1">
															<button
																class=" bg-white text-black border border-white rounded-full group-hover:visible invisible transition"
																type="button"
																on:click={() => removeAttachment(file)}
															>
																<svg
																	xmlns="http://www.w3.org/2000/svg"
																	viewBox="0 0 20 20"
																	fill="currentColor"
																	class="size-4"
																>
																	<path
																		d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
																	/>
																</svg>
															</button>
														</div>
													</div>
												{:else}
													<FileItem
														item={file}
														name={file.name}
														type={file.type}
														size={file?.size}
														loading={file.status === 'uploading' || file.status === 'processing'}
														dismissible={true}
														edit={true}
														on:dismiss={() => removeAttachment(file)}
													/>
												{/if}

												{#if file.status === 'processing' || file.status === 'error' || file.processing_warnings?.length || file.visual_summary}
													<div class="max-w-60 px-1 text-xs text-gray-500 dark:text-gray-400">
														{#if file.status === 'processing'}
															<div>
																{file.polling_timed_out
																	? $i18n.t('Still processing; refresh for the latest status.')
																	: $i18n.t('Processing attachment…')}
															</div>
														{:else if file.status === 'error'}
															<div class="text-red-600 dark:text-red-400">
																{file.processing_error_code ? `${file.processing_error_code}: ` : ''}{file.error ||
																	$i18n.t('Processing failed')}
															</div>
														{/if}

														{#each file.processing_warnings ?? [] as warning}
															<div class="text-amber-600 dark:text-amber-400">
																{formatProcessingWarning(warning)}
															</div>
														{/each}
														{#if file.visual_summary && formatVisualSummary(file.visual_summary)}
															<div class="capitalize">{formatVisualSummary(file.visual_summary)}</div>
														{/if}

														{#if file.id && (file.status === 'processing' || file.status === 'error')}
															<div class="mt-0.5 flex gap-2">
																<button
																	type="button"
																	class="underline hover:text-gray-700 dark:hover:text-gray-200 disabled:opacity-50"
																	disabled={file.status_refreshing}
																	on:click={() => refreshFileStatus(file)}
																>
																	{$i18n.t('Refresh')}
																</button>
																{#if file.status === 'error' || file.polling_timed_out}
																	<button
																		type="button"
																		class="underline hover:text-gray-700 dark:hover:text-gray-200"
																		on:click={() => retryFileProcessing(file)}
																	>
																		{$i18n.t('Retry')}
																	</button>
																{/if}
															</div>
														{/if}
													</div>
												{/if}
											</div>
										{/each}
									</div>
								{/if}

								<div class="px-2.5">
									{#if $settings?.richTextInput ?? true}
										<div
											class="scrollbar-hidden text-left bg-transparent dark:text-gray-100 outline-hidden w-full pt-3 px-1 resize-none h-fit max-h-80 overflow-auto"
										>
											<RichTextInput
												bind:this={chatInputElement}
												bind:value={prompt}
												id="chat-input"
												messageInput={true}
												shiftEnter={!$mobile ||
													!(
														'ontouchstart' in window ||
														navigator.maxTouchPoints > 0 ||
														navigator.msMaxTouchPoints > 0
													)}
												placeholder={placeholder ? placeholder : $i18n.t('Send a Message')}
												largeTextAsFile={$settings?.largeTextAsFile ?? false}
												autocomplete={$config?.features.enable_autocomplete_generation}
												generateAutoCompletion={async (text) => {
													if (selectedModelIds.length === 0 || !selectedModelIds.at(0)) {
														toast.error($i18n.t('Please select a model first.'));
													}

													const res = await generateAutoCompletion(
														localStorage.token,
														selectedModelIds.at(0),
														text,
														history?.currentId
															? createMessagesList(history, history.currentId)
															: null
													).catch(() => {
														return null;
													});

													return res;
												}}
												on:keydown={async (e) => {
													e = e.detail.event;

													const isCtrlPressed = e.ctrlKey || e.metaKey; // metaKey is for Cmd key on Mac
													const commandsContainerElement =
														document.getElementById('commands-container');

													if (e.key === 'Escape') {
														stopResponse();
													}

													// Command/Ctrl + Shift + Enter to submit a message pair
													if (isCtrlPressed && e.key === 'Enter' && e.shiftKey) {
														e.preventDefault();
														createMessagePair(prompt);
													}

													// Check if Ctrl + R is pressed
													if (prompt === '' && isCtrlPressed && e.key.toLowerCase() === 'r') {
														e.preventDefault();

														const regenerateButton = [
															...document.getElementsByClassName('regenerate-response-button')
														]?.at(-1);

														regenerateButton?.click();
													}

													if (prompt === '' && e.key == 'ArrowUp') {
														e.preventDefault();

														const userMessageElement = [
															...document.getElementsByClassName('user-message')
														]?.at(-1);

														if (userMessageElement) {
															userMessageElement.scrollIntoView({ block: 'center' });
															const editButton = [
																...document.getElementsByClassName('edit-user-message-button')
															]?.at(-1);

															editButton?.click();
														}
													}

													if (commandsContainerElement) {
														if (commandsContainerElement && e.key === 'ArrowUp') {
															e.preventDefault();
															commandsElement.selectUp();

															const commandOptionButton = [
																...document.getElementsByClassName('selected-command-option-button')
															]?.at(-1);
															commandOptionButton.scrollIntoView({ block: 'center' });
														}

														if (commandsContainerElement && e.key === 'ArrowDown') {
															e.preventDefault();
															commandsElement.selectDown();

															const commandOptionButton = [
																...document.getElementsByClassName('selected-command-option-button')
															]?.at(-1);
															commandOptionButton.scrollIntoView({ block: 'center' });
														}

														if (commandsContainerElement && e.key === 'Tab') {
															e.preventDefault();

															const commandOptionButton = [
																...document.getElementsByClassName('selected-command-option-button')
															]?.at(-1);

															commandOptionButton?.click();
														}

														if (commandsContainerElement && e.key === 'Enter') {
															e.preventDefault();

															const commandOptionButton = [
																...document.getElementsByClassName('selected-command-option-button')
															]?.at(-1);

															if (commandOptionButton) {
																commandOptionButton?.click();
															} else {
																document.getElementById('send-message-button')?.click();
															}
														}
													} else {
														if (
															!$mobile ||
															!(
																'ontouchstart' in window ||
																navigator.maxTouchPoints > 0 ||
																navigator.msMaxTouchPoints > 0
															)
														) {
															// Prevent Enter key from creating a new line
															// Uses keyCode '13' for Enter key for chinese/japanese keyboards
															if (e.keyCode === 13 && !e.shiftKey) {
																e.preventDefault();
															}

															// Submit the prompt when Enter key is pressed
															if (
																inputCanSubmit &&
																e.keyCode === 13 &&
																!e.shiftKey
															) {
																dispatch('submit', prompt);
															}
														}
													}

													if (e.key === 'Escape') {
														atSelectedModel = undefined;
														selectedToolIds = [];
														webSearchEnabled = false;
														imageGenerationEnabled = false;
													}
												}}
												on:paste={async (e) => {
													await pasteHandler(e.detail.event);
												}}
											/>
										</div>
									{:else}
										<textarea
											id="chat-input"
											bind:this={chatInputElement}
											class="scrollbar-hidden bg-transparent dark:text-gray-100 outline-hidden w-full pt-3 px-1 resize-none"
											placeholder={placeholder ? placeholder : $i18n.t('Send a Message')}
											bind:value={prompt}
											on:keypress={(e) => {
												if (
													!$mobile ||
													!(
														'ontouchstart' in window ||
														navigator.maxTouchPoints > 0 ||
														navigator.msMaxTouchPoints > 0
													)
												) {
													// Prevent Enter key from creating a new line
													if (e.key === 'Enter' && !e.shiftKey) {
														e.preventDefault();
													}

													// Submit the prompt when Enter key is pressed
													if (
														inputCanSubmit &&
														e.key === 'Enter' &&
														!e.shiftKey
													) {
														dispatch('submit', prompt);
													}
												}
											}}
											on:keydown={async (e) => {
												const isCtrlPressed = e.ctrlKey || e.metaKey; // metaKey is for Cmd key on Mac
												const commandsContainerElement =
													document.getElementById('commands-container');

												if (e.key === 'Escape') {
													stopResponse();
												}
												// Command/Ctrl + Shift + Enter to submit a message pair
												if (isCtrlPressed && e.key === 'Enter' && e.shiftKey) {
													e.preventDefault();
													createMessagePair(prompt);
												}

												// Check if Ctrl + R is pressed
												if (prompt === '' && isCtrlPressed && e.key.toLowerCase() === 'r') {
													e.preventDefault();

													const regenerateButton = [
														...document.getElementsByClassName('regenerate-response-button')
													]?.at(-1);

													regenerateButton?.click();
												}

												if (prompt === '' && e.key == 'ArrowUp') {
													e.preventDefault();

													const userMessageElement = [
														...document.getElementsByClassName('user-message')
													]?.at(-1);

													const editButton = [
														...document.getElementsByClassName('edit-user-message-button')
													]?.at(-1);

													userMessageElement.scrollIntoView({ block: 'center' });
													editButton?.click();
												}

												if (commandsContainerElement && e.key === 'ArrowUp') {
													e.preventDefault();
													commandsElement.selectUp();

													const commandOptionButton = [
														...document.getElementsByClassName('selected-command-option-button')
													]?.at(-1);
													commandOptionButton.scrollIntoView({ block: 'center' });
												}

												if (commandsContainerElement && e.key === 'ArrowDown') {
													e.preventDefault();
													commandsElement.selectDown();

													const commandOptionButton = [
														...document.getElementsByClassName('selected-command-option-button')
													]?.at(-1);
													commandOptionButton.scrollIntoView({ block: 'center' });
												}

												if (commandsContainerElement && e.key === 'Enter') {
													e.preventDefault();

													const commandOptionButton = [
														...document.getElementsByClassName('selected-command-option-button')
													]?.at(-1);

													if (e.shiftKey) {
														prompt = `${prompt}\n`;
													} else if (commandOptionButton) {
														commandOptionButton?.click();
													} else {
														document.getElementById('send-message-button')?.click();
													}
												}

												if (commandsContainerElement && e.key === 'Tab') {
													e.preventDefault();

													const commandOptionButton = [
														...document.getElementsByClassName('selected-command-option-button')
													]?.at(-1);

													commandOptionButton?.click();
												} else if (e.key === 'Tab') {
													const words = findWordIndices(prompt);

													if (words.length > 0) {
														const word = words.at(0);
														const fullPrompt = prompt;

														prompt = prompt.substring(0, word?.endIndex + 1);
														await tick();

														e.target.scrollTop = e.target.scrollHeight;
														prompt = fullPrompt;
														await tick();

														e.preventDefault();
														e.target.setSelectionRange(word?.startIndex, word.endIndex + 1);
													}

													e.target.style.height = '';
													e.target.style.height = Math.min(e.target.scrollHeight, 320) + 'px';
												}

												if (e.key === 'Escape') {
													atSelectedModel = undefined;
													selectedToolIds = [];
													webSearchEnabled = false;
													imageGenerationEnabled = false;
												}
											}}
											rows="1"
											on:input={async (e) => {
												e.target.style.height = '';
												e.target.style.height = Math.min(e.target.scrollHeight, 320) + 'px';
											}}
											on:focus={async (e) => {
												e.target.style.height = '';
												e.target.style.height = Math.min(e.target.scrollHeight, 320) + 'px';
											}}
											on:paste={async (e) => {
												await pasteHandler(e);
											}}
										/>
									{/if}
								</div>

								<div class=" flex justify-between mt-1.5 mb-2.5 mx-0.5 max-w-full">
									<div class="ml-1 self-end gap-0.5 flex items-center flex-1 max-w-[80%]">
										<InputMenu
											bind:selectedToolIds
											{screenCaptureHandler}
											{inputFilesHandler}
											uploadFilesHandler={() => {
												filesInputElement.click();
											}}
											uploadGoogleDriveHandler={async () => {
												try {
													const fileData = await createPicker();
													if (fileData) {
														const file = new File([fileData.blob], fileData.name, {
															type: fileData.blob.type
														});
														await uploadFileHandler(file);
													}
												} catch (error) {
													console.error('Google Drive Error:', error);
													toast.error(
														$i18n.t('Error accessing Google Drive: {{error}}', {
															error: error.message
														})
													);
												}
											}}
											uploadOneDriveHandler={async () => {
												try {
													const fileData = await pickAndDownloadFile();
													if (fileData) {
														const file = new File([fileData.blob], fileData.name, {
															type: fileData.blob.type || 'application/octet-stream'
														});
														await uploadFileHandler(file);
													}
												} catch (error) {
													console.error('OneDrive Error:', error);
												}
											}}
											onClose={async () => {
												await tick();

												const chatInput = document.getElementById('chat-input');
												chatInput?.focus();
											}}
										>
											<button
												class="bg-transparent hover:bg-gray-100 text-gray-800 dark:text-white dark:hover:bg-gray-800 transition rounded-full p-1.5 outline-hidden focus:outline-hidden"
												type="button"
												aria-label="More"
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													viewBox="0 0 20 20"
													fill="currentColor"
													class="size-5"
												>
													<path
														d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z"
													/>
												</svg>
											</button>
										</InputMenu>

										<div class="flex gap-0.5 items-center overflow-x-auto scrollbar-none flex-1">
											<!-- WebSearch -->
											{#if $_user}
												<!-- {#if $config?.features?.enable_web_search && ($_user.role === 'admin' || $_user?.permissions?.features?.web_search)} -->
												<Tooltip content={$i18n.t('Search the internet')} placement="top">
													<button
														on:click|preventDefault={() => (webSearchEnabled = !webSearchEnabled)}
														type="button"
														class="px-1.5 @sm:px-2.5 py-1.5 flex gap-1.5 items-center text-sm rounded-full font-medium transition-colors duration-300 focus:outline-hidden max-w-full overflow-hidden {webSearchEnabled ||
														($settings?.webSearch ?? false) === 'always'
															? 'bg-blue-100 dark:bg-blue-500/20 text-blue-500 dark:text-blue-400'
															: 'bg-transparent text-gray-600 dark:text-gray-300 border-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800'}"
													>
														<GlobeAlt className="size-5" strokeWidth="1.75" />
														<span
															class="hidden @sm:block whitespace-nowrap overflow-hidden text-ellipsis translate-y-[0.5px] mr-0.5"
															>{$i18n.t('Web Search')}</span
														>
													</button>
												</Tooltip>
												<!-- {/if} -->

												{#if $config?.features?.enable_image_generation && ($_user.role === 'admin' || $_user?.permissions?.features?.image_generation)}
													<Tooltip content={$i18n.t('Generate an image')} placement="top">
														<button
															on:click|preventDefault={() =>
																(imageGenerationEnabled = !imageGenerationEnabled)}
															type="button"
															class="px-1.5 @sm:px-2.5 py-1.5 flex gap-1.5 items-center text-sm rounded-full font-medium transition-colors duration-300 focus:outline-hidden max-w-full overflow-hidden {imageGenerationEnabled
																? 'bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-400'
																: 'bg-transparent text-gray-600 dark:text-gray-300 border-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 '}"
														>
															<Photo className="size-5" strokeWidth="1.75" />
															<span
																class="hidden @sm:block whitespace-nowrap overflow-hidden text-ellipsis translate-y-[0.5px] mr-0.5"
																>{$i18n.t('Image')}</span
															>
														</button>
													</Tooltip>
												{/if}

												{#if $config?.features?.enable_code_interpreter && ($_user.role === 'admin' || $_user?.permissions?.features?.code_interpreter)}
													<Tooltip content={$i18n.t('Execute code for analysis')} placement="top">
														<button
															on:click|preventDefault={() =>
																(codeInterpreterEnabled = !codeInterpreterEnabled)}
															type="button"
															class="px-1.5 @sm:px-2.5 py-1.5 flex gap-1.5 items-center text-sm rounded-full font-medium transition-colors duration-300 focus:outline-hidden max-w-full overflow-hidden {codeInterpreterEnabled
																? 'bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-400'
																: 'bg-transparent text-gray-600 dark:text-gray-300 border-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 '}"
														>
															<CommandLine className="size-5" strokeWidth="1.75" />
															<span
																class="hidden @sm:block whitespace-nowrap overflow-hidden text-ellipsis translate-y-[0.5px] mr-0.5"
																>{$i18n.t('Code Interpreter')}</span
															>
														</button>
													</Tooltip>
												{/if}
											{/if}
										</div>
									</div>

									<div class="self-end flex space-x-1 mr-1 shrink-0">
										{#if !history?.currentId || history.messages[history.currentId]?.done == true}
											<Tooltip content={$i18n.t('Record voice')}>
												<button
													id="voice-input-button"
													class=" text-gray-600 dark:text-gray-300 hover:text-gray-700 dark:hover:text-gray-200 transition rounded-full p-1.5 mr-0.5 self-center"
													type="button"
													on:click={async () => {
														try {
															let stream = await navigator.mediaDevices
																.getUserMedia({ audio: true })
																.catch(function (err) {
																	toast.error(
																		$i18n.t(
																			`Permission denied when accessing microphone: {{error}}`,
																			{
																				error: err
																			}
																		)
																	);
																	return null;
																});

															if (stream) {
																recording = true;
																const tracks = stream.getTracks();
																tracks.forEach((track) => track.stop());
															}
															stream = null;
														} catch {
															toast.error($i18n.t('Permission denied when accessing microphone'));
														}
													}}
													aria-label="Voice Input"
												>
													<svg
														xmlns="http://www.w3.org/2000/svg"
														viewBox="0 0 20 20"
														fill="currentColor"
														class="w-5 h-5 translate-y-[0.5px]"
													>
														<path d="M7 4a3 3 0 016 0v6a3 3 0 11-6 0V4z" />
														<path
															d="M5.5 9.643a.75.75 0 00-1.5 0V10c0 3.06 2.29 5.585 5.25 5.954V17.5h-1.5a.75.75 0 000 1.5h4.5a.75.75 0 000-1.5h-1.5v-1.546A6.001 6.001 0 0016 10v-.357a.75.75 0 00-1.5 0V10a4.5 4.5 0 01-9 0v-.357z"
														/>
													</svg>
												</button>
											</Tooltip>
										{/if}

										{#if !history.currentId || history.messages[history.currentId]?.done == true}
											{#if prompt === '' && files.length === 0}
												<div class=" flex items-center">
													<Tooltip content={$i18n.t('Call')}>
														<button
															class=" {webSearchEnabled ||
															($settings?.webSearch ?? false) === 'always'
																? 'bg-blue-500 text-white hover:bg-blue-400 '
																: 'bg-black text-white hover:bg-gray-900 dark:bg-white dark:text-black dark:hover:bg-gray-100'} transition rounded-full p-1.5 self-center"
															type="button"
															on:click={async () => {
																if (selectedModels.length > 1) {
																	toast.error($i18n.t('Select only one model to call'));

																	return;
																}

																if ($config.audio.stt.engine === 'web') {
																	toast.error(
																		$i18n.t(
																			'Call feature is not supported when using Web STT engine'
																		)
																	);

																	return;
																}
																// check if user has access to getUserMedia
																try {
																	let stream = await navigator.mediaDevices.getUserMedia({
																		audio: true
																	});
																	// If the user grants the permission, proceed to show the call mode modal

																	if (stream) {
																		const tracks = stream.getTracks();
																		tracks.forEach((track) => track.stop());
																	}

																	stream = null;

																	if ($settings.callMode) {
																		await startCallWithMode($settings.callMode);
																	} else {
																		showCallModeModal = true;
																	}
																} catch (err) {
																	// If the user denies the permission or an error occurs, show an error message
																	toast.error(
																		$i18n.t('Permission denied when accessing media devices')
																	);
																}
															}}
															aria-label="Call"
														>
															<Headphone className="size-5" />
														</button>
													</Tooltip>
												</div>
											{:else}
												<div class=" flex items-center">
													<Tooltip content={$i18n.t('Send message')}>
														<button
															id="send-message-button"
															class="{inputCanSubmit
																? webSearchEnabled || ($settings?.webSearch ?? false) === 'always'
																	? 'bg-blue-500 text-white hover:bg-blue-400 '
																	: 'bg-black text-white hover:bg-gray-900 dark:bg-white dark:text-black dark:hover:bg-gray-100 '
																: 'text-white bg-gray-200 dark:text-gray-900 dark:bg-gray-700 disabled'} transition rounded-full p-1.5 self-center"
															type="submit"
															disabled={!inputCanSubmit}
														>
															<svg
																xmlns="http://www.w3.org/2000/svg"
																viewBox="0 0 16 16"
																fill="currentColor"
																class="size-5"
															>
																<path
																	fill-rule="evenodd"
																	d="M8 14a.75.75 0 0 1-.75-.75V4.56L4.03 7.78a.75.75 0 0 1-1.06-1.06l4.5-4.5a.75.75 0 0 1 1.06 0l4.5 4.5a.75.75 0 0 1-1.06 1.06L8.75 4.56v8.69A.75.75 0 0 1 8 14Z"
																	clip-rule="evenodd"
																/>
															</svg>
														</button>
													</Tooltip>
												</div>
											{/if}
										{:else}
											<div class=" flex items-center">
												<Tooltip content={$i18n.t('Stop')}>
													<button
														class="bg-white hover:bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-white dark:hover:bg-gray-800 transition rounded-full p-1.5"
														on:click={() => {
															stopResponse();
														}}
													>
														<svg
															xmlns="http://www.w3.org/2000/svg"
															viewBox="0 0 24 24"
															fill="currentColor"
															class="size-5"
														>
															<path
																fill-rule="evenodd"
																d="M2.25 12c0-5.385 4.365-9.75 9.75-9.75s9.75 4.365 9.75 9.75-4.365 9.75-9.75 9.75S2.25 17.385 2.25 12zm6-2.438c0-.724.588-1.312 1.313-1.312h4.874c.725 0 1.313.588 1.313 1.313v4.874c0 .725-.588 1.313-1.313 1.313H9.564a1.312 1.312 0 01-1.313-1.313V9.564z"
																clip-rule="evenodd"
															/>
														</svg>
													</button>
												</Tooltip>
											</div>
										{/if}
									</div>
								</div>
							</div>
						</form>
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}
