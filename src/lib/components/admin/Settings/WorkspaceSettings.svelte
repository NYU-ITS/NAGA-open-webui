<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';

	import { user } from '$lib/stores';
	import { getEmbeddingConfig, updateEmbeddingConfig, updateRAGConfig } from '$lib/apis/retrieval';
	import { getAudioConfig, updateAudioConfig } from '$lib/apis/audio';
	import { getFunctions, getFunctionValvesById, updateFunctionValvesById } from '$lib/apis/functions';
	import { verifyOpenAIConnection } from '$lib/apis/openai';
	import { WORKSPACE_CASCADED_FUNCTIONS_KEY } from '$lib/constants';

	import Modal from '$lib/components/common/Modal.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';

	const i18n = getContext('i18n');

	// ── Form state ────────────────────────────────────────────────────────────
	let modelEngineUrl = 'https://ai-gateway.apps.cloud.rt.nyu.edu/v1';
	let apiKey = '';

	let embeddingsEnabled = true;
	let embeddingModel = '';

	let audioEnabled = false;
	let sttModel = '';
	let ttsModel = '';
	let language = 'English';

	// ── Model engine edit modal ───────────────────────────────────────────────
	let showModelEngineModal = false;
	let pendingModelEngineUrl = '';

	const openModelEngineModal = () => {
		pendingModelEngineUrl = modelEngineUrl;
		showModelEngineModal = true;
	};

	const confirmModelEngineUpdate = () => {
		modelEngineUrl = pendingModelEngineUrl;
		showModelEngineModal = false;
	};

	// ── Preserved full configs (for non-workspace fields on save) ─────────────
	let fullEmbeddingConfig: Record<string, any> | null = null;
	let fullAudioConfig: Record<string, any> | null = null;

	// Snapshot of the API key as loaded on mount, used to detect which functions
	// are tracking the workspace key vs. managing their own independently.
	let originalApiKey = '';

	let isSaving = false;

	// ── Test connection ───────────────────────────────────────────────────────
	let testingConnection = false;

	const testConnectionHandler = async () => {
		testingConnection = true;

		const res = await verifyOpenAIConnection(localStorage.token, modelEngineUrl, apiKey).catch(
			(error) => {
				toast.error($i18n.t('Could not verify key — check value. ({{error}})', { error: `${error}` }));
				return null;
			}
		);

		if (res) {
			toast.success($i18n.t('Connection OK'));
		}

		testingConnection = false;
	};

	const languageOptions = [
		'Afrikaans', 'Arabic', 'Armenian', 'Azerbaijani', 'Belarusian', 'Bosnian', 'Bulgarian',
		'Catalan', 'Chinese', 'Croatian', 'Czech', 'Danish', 'Dutch', 'English', 'Estonian',
		'Finnish', 'French', 'Galician', 'German', 'Greek', 'Hebrew', 'Hindi', 'Hungarian',
		'Icelandic', 'Indonesian', 'Italian', 'Japanese', 'Kannada', 'Kazakh', 'Korean',
		'Latvian', 'Lithuanian', 'Macedonian', 'Malay', 'Marathi', 'Maori', 'Nepali',
		'Norwegian', 'Persian', 'Polish', 'Portuguese', 'Romanian', 'Russian', 'Serbian',
		'Slovak', 'Slovenian', 'Spanish', 'Swahili', 'Swedish', 'Tagalog', 'Tamil', 'Thai',
		'Turkish', 'Ukrainian', 'Urdu', 'Vietnamese', 'Welsh'
	];

	// ── Save: cascade key + URL to embeddings and audio ──────────────────────
	const saveHandler = async () => {
		isSaving = true;
		try {
			// 1. Embeddings — always cascade key + URL; toggle controls active model + BYPASS flag
			await updateEmbeddingConfig(localStorage.token, {
				email: $user.email,
				embedding_engine: 'portkey',
				embedding_model: embeddingsEnabled ? embeddingModel : '',
				embedding_batch_size: fullEmbeddingConfig?.embedding_batch_size ?? 1,
				openai_config: { key: apiKey, url: modelEngineUrl },
				ollama_config: fullEmbeddingConfig?.ollama_config || { key: '', url: '' }
			});

			// Set BYPASS flag so toggling Embeddings off actually disables embedding functionality
			await (updateRAGConfig as any)(localStorage.token, {
				email: $user.email,
				BYPASS_EMBEDDING_AND_RETRIEVAL: !embeddingsEnabled
			});

			// 2. Audio — always cascade key + URL; toggle enables/disables portkey engine
			const baseTts = fullAudioConfig?.tts ?? {};
			const baseStt = fullAudioConfig?.stt ?? {};

			await updateAudioConfig(localStorage.token, {
				tts: {
					OPENAI_API_BASE_URL: baseTts.OPENAI_API_BASE_URL ?? '',
					OPENAI_API_KEY: baseTts.OPENAI_API_KEY ?? '',
					API_KEY: baseTts.API_KEY ?? '',
					VOICE: baseTts.VOICE ?? '',
					AUDIO_VOICE: baseTts.AUDIO_VOICE ?? 'alloy',
					SPLIT_ON: baseTts.SPLIT_ON ?? 'punctuation',
					AZURE_SPEECH_REGION: baseTts.AZURE_SPEECH_REGION ?? '',
					AZURE_SPEECH_OUTPUT_FORMAT: baseTts.AZURE_SPEECH_OUTPUT_FORMAT ?? '',
					// workspace-controlled fields
					PORTKEY_API_BASE_URL: modelEngineUrl,
					PORTKEY_API_KEY: apiKey,
					ENGINE: audioEnabled ? 'portkey' : (baseTts.ENGINE === 'portkey' ? '' : (baseTts.ENGINE ?? '')),
					MODEL: audioEnabled ? ttsModel : (baseTts.MODEL ?? ''),
					LANGUAGE: audioEnabled ? language : (baseTts.LANGUAGE ?? 'English')
				},
				stt: {
					OPENAI_API_BASE_URL: baseStt.OPENAI_API_BASE_URL ?? '',
					OPENAI_API_KEY: baseStt.OPENAI_API_KEY ?? '',
					WHISPER_MODEL: baseStt.WHISPER_MODEL ?? '',
					DEEPGRAM_API_KEY: baseStt.DEEPGRAM_API_KEY ?? '',
					PROMPT: baseStt.PROMPT ?? '',
					// workspace-controlled fields
					PORTKEY_API_BASE_URL: modelEngineUrl,
					PORTKEY_API_KEY: apiKey,
					ENGINE: audioEnabled ? 'portkey' : (baseStt.ENGINE === 'portkey' ? '' : (baseStt.ENGINE ?? '')),
					MODEL: audioEnabled ? sttModel : (baseStt.MODEL ?? ''),
					LANGUAGE: audioEnabled ? language : (baseStt.LANGUAGE ?? 'English')
				}
			});

			// 3. Functions — cascade key + URL to functions whose PORTKEY_API_KEY valve
			// was tracking the previous workspace key (old key -> new key match), or
			// whose key was never set (empty - nothing yet to protect). Functions with
			// a genuinely different, deliberately-set key are left untouched.
			const functions = await getFunctions(localStorage.token);
			const cascadedFunctionIds: string[] = [];
			const failedFunctionNames: string[] = [];
			await Promise.allSettled(
				(functions ?? []).map(async (fn: any) => {
					try {
						const currentValves = await getFunctionValvesById(localStorage.token, fn.id);
						if (!currentValves || !('PORTKEY_API_KEY' in currentValves)) return;
						const currentKey = currentValves['PORTKEY_API_KEY'];
						if (currentKey !== originalApiKey && currentKey !== '') return;

						const updatedValves: Record<string, any> = { ...currentValves };
						updatedValves['PORTKEY_API_KEY'] = apiKey;
						if ('PORTKEY_API_BASE_URL' in updatedValves) {
							updatedValves['PORTKEY_API_BASE_URL'] = modelEngineUrl;
						}
						await updateFunctionValvesById(localStorage.token, fn.id, updatedValves);
						cascadedFunctionIds.push(fn.id);
					} catch (_) {
						failedFunctionNames.push(fn.name ?? fn.id);
					}
				})
			);
			localStorage.setItem(WORKSPACE_CASCADED_FUNCTIONS_KEY, JSON.stringify(cascadedFunctionIds));

			// Update the snapshot so subsequent saves in this session compare against the
			// key that is now live, not the one loaded on initial mount.
			originalApiKey = apiKey;

			toast.success($i18n.t('Workspace settings saved successfully!'));

			if (failedFunctionNames.length > 0) {
				toast.warning(
					$i18n.t('Could not sync the API key to: {{names}}', {
						names: failedFunctionNames.join(', ')
					})
				);
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			isSaving = false;
		}
	};

	// ── onMount: load existing configs ───────────────────────────────────────
	onMount(async () => {
		try {
			fullEmbeddingConfig = await getEmbeddingConfig(localStorage.token, $user.email);
			if (fullEmbeddingConfig) {
				embeddingsEnabled = fullEmbeddingConfig.embedding_engine === 'portkey';
				embeddingModel = fullEmbeddingConfig.embedding_model || '';
				if (fullEmbeddingConfig.embedding_engine === 'portkey') {
					modelEngineUrl = fullEmbeddingConfig.openai_config?.url || modelEngineUrl;
					apiKey = fullEmbeddingConfig.openai_config?.key || '';
				}
			}
		} catch (e) {
			console.error('Failed to load embedding config:', e);
		}

		try {
			fullAudioConfig = await getAudioConfig(localStorage.token);
			if (fullAudioConfig) {
				const sttPortkey = fullAudioConfig.stt?.ENGINE === 'portkey';
				const ttsPortkey = fullAudioConfig.tts?.ENGINE === 'portkey';
				audioEnabled = sttPortkey || ttsPortkey;

				sttModel = fullAudioConfig.stt?.MODEL || '';
				ttsModel = fullAudioConfig.tts?.MODEL || '';
				language = fullAudioConfig.stt?.LANGUAGE || fullAudioConfig.tts?.LANGUAGE || 'English';

				// If embedding config didn't have the key, try audio
				if (!apiKey) {
					apiKey =
						fullAudioConfig.stt?.PORTKEY_API_KEY ||
						fullAudioConfig.tts?.PORTKEY_API_KEY ||
						'';
				}
			}
		} catch (e) {
			console.error('Failed to load audio config:', e);
		}

		// Snapshot the resolved API key so saveHandler can detect which functions
		// were tracking the workspace key prior to this edit.
		originalApiKey = apiKey;
	});
</script>

<!-- Model engine confirmation modal -->
<Modal bind:show={showModelEngineModal} size="sm">
	<div class="p-6 flex flex-col gap-4">
		<div class="flex items-start gap-3">
			<div class="text-yellow-500 mt-0.5 shrink-0">
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-6 h-6">
					<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
				</svg>
			</div>
			<div>
				<p class="text-sm font-semibold dark:text-white">{$i18n.t('Are you sure you want to update the Portkey URL?')}</p>
				<p class="text-xs text-gray-500 dark:text-gray-400 mt-1">{$i18n.t('This URL is used for embeddings, audio (STT/TTS), and the default LLM function. Changing it updates all three on Save.')}</p>
			</div>
		</div>

		<div>
			<div class="text-xs font-medium mb-1 dark:text-gray-300">{$i18n.t('Portkey URL')}</div>
			<input
				class="w-full rounded-lg py-1.5 px-3 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden border border-gray-200 dark:border-gray-700"
				bind:value={pendingModelEngineUrl}
				placeholder="https://ai-gateway.apps.cloud.rt.nyu.edu/v1"
			/>
		</div>

		<div class="flex justify-end gap-2 pt-1">
			<button
				class="px-4 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
				on:click={() => (showModelEngineModal = false)}
			>
				{$i18n.t('Cancel')}
			</button>
			<button
				class="px-4 py-1.5 text-sm rounded-lg bg-gray-900 dark:bg-white text-white dark:text-black hover:bg-gray-700 dark:hover:bg-gray-100 transition"
				on:click={confirmModelEngineUpdate}
			>
				{$i18n.t('Save')}
			</button>
		</div>
	</div>
</Modal>

<!-- Main form -->
<form class="flex flex-col space-y-3 text-sm" on:submit|preventDefault={saveHandler}>
	<div class="space-y-4 pr-1.5">

		<div class="mb-1">
			<div class="text-xl font-semibold dark:text-white">{$i18n.t('Workspace settings')}</div>
		</div>

		<hr class="border-gray-100 dark:border-gray-850" />

		<!-- Model engine -->
		<div class="space-y-1.5">
			<div class="text-xs font-medium dark:text-gray-300">{$i18n.t('Portkey URL')}</div>
			<div class="flex items-center gap-2">
				<input
					class="flex-1 rounded-lg py-1.5 px-3 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					value={modelEngineUrl}
					readonly
				/>
				<button
					type="button"
					class="px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-900 dark:bg-white text-white dark:text-black hover:bg-gray-700 dark:hover:bg-gray-100 transition shrink-0"
					on:click={openModelEngineModal}
				>
					{$i18n.t('Edit')}
				</button>
			</div>
		</div>

		<!-- API key -->
		<div class="space-y-1.5">
			<div class="text-xs font-medium dark:text-gray-300">{$i18n.t('API key')}</div>
			<SensitiveInput
				placeholder={$i18n.t('Please enter Portkey API key here')}
				bind:value={apiKey}
				required={false}
			/>
			<div class="flex justify-end">
				<button
					type="button"
					class="text-xs text-[#57068c] dark:text-purple-400 hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
					on:click={testConnectionHandler}
					disabled={testingConnection || !apiKey}
				>
					{testingConnection ? $i18n.t('Testing...') : $i18n.t('Test Connection')}
				</button>
			</div>
		</div>

		<hr class="border-gray-100 dark:border-gray-850" />

		<!-- Embeddings toggle -->
		<div class="space-y-2">
			<div class="flex w-full items-center justify-between">
				<div class="text-sm font-medium dark:text-gray-200">{$i18n.t('Embeddings')}</div>
				<Switch bind:state={embeddingsEnabled} />
			</div>

			{#if embeddingsEnabled}
				<div class="pl-1 space-y-1.5">
					<div class="text-xs font-medium dark:text-gray-300">{$i18n.t('Model name')}</div>
					<input
						class="w-full rounded-lg py-1.5 px-3 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						placeholder={$i18n.t('Embedding model name. Eg. openai: text-embedding-small3')}
						bind:value={embeddingModel}
					/>
					<div class="flex justify-end">
						<a
							href="/admin/settings?tab=documents"
							class="text-xs text-[#57068c] dark:text-purple-400 hover:underline"
						>
							{$i18n.t('Advanced settings')}
						</a>
					</div>
				</div>
			{/if}
		</div>

		<hr class="border-gray-100 dark:border-gray-850" />

		<!-- Audio toggle -->
		<div class="space-y-2">
			<div class="flex w-full items-center justify-between">
				<div class="text-sm font-medium dark:text-gray-200">{$i18n.t('Audio')}</div>
				<Switch bind:state={audioEnabled} />
			</div>

			{#if audioEnabled}
				<div class="pl-1 space-y-3">

					<!-- Speech-to-Text -->
					<div class="space-y-1.5">
						<div class="text-xs font-semibold text-gray-700 dark:text-gray-300">{$i18n.t('Speech-to-Text')}</div>
						<div class="text-xs font-medium dark:text-gray-400">{$i18n.t('Model name')}</div>
						<input
							class="w-full rounded-lg py-1.5 px-3 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							placeholder="@gpt-4o-mini-transcribe/gpt-4o-mini-transcribe"
							bind:value={sttModel}
						/>
					</div>

					<!-- Text-to-Speech -->
					<div class="space-y-1.5">
						<div class="text-xs font-semibold text-gray-700 dark:text-gray-300">{$i18n.t('Text-to-Speech')}</div>
						<div class="text-xs font-medium dark:text-gray-400">{$i18n.t('Model name')}</div>
						<input
							class="w-full rounded-lg py-1.5 px-3 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							placeholder="@gpt-4o-mini-tts/gpt-4o-mini-tts"
							bind:value={ttsModel}
						/>
					</div>

					<!-- Language -->
					<div class="space-y-1.5">
						<div class="text-xs font-medium dark:text-gray-300">{$i18n.t('Language')}</div>
						<select
							class="w-full rounded-lg py-1.5 px-3 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={language}
							aria-label="Language"
						>
							{#each languageOptions as lang}
								<option value={lang}>{lang}</option>
							{/each}
						</select>
					</div>

					<div class="flex justify-end">
						<a
							href="/admin/settings?tab=audio"
							class="text-xs text-[#57068c] dark:text-purple-400 hover:underline"
						>
							{$i18n.t('Advanced settings')}
						</a>
					</div>
				</div>
			{/if}
		</div>

	</div>

	<!-- Save button -->
	<div class="pt-3">
		<button
			type="submit"
			class="w-full py-2 text-sm font-medium bg-[#57068c] hover:bg-[#6b0baa] text-white transition rounded-lg disabled:opacity-60"
			disabled={isSaving}
		>
			{isSaving ? $i18n.t('Saving...') : $i18n.t('Save')}
		</button>
	</div>
</form>
