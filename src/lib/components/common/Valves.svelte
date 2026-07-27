<script>
	import { onMount, getContext, createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	import Switch from './Switch.svelte';
	import SensitiveInput from './SensitiveInput.svelte';
	import { WORKSPACE_SETTINGS_PATH } from '$lib/constants';

	export let valvesSpec = null;
	export let valves = {};
	export let syncedFields = new Set();
	// Live values from Workspace Settings, e.g. { PORTKEY_API_KEY: '...', PORTKEY_API_BASE_URL: '...' }.
	export let workspaceValues = {};

	// These two fields are managed by the Workspace Settings cascade. "Default"
	// for them means "tracking the workspace value" - shown read-only, not an
	// editable empty string like every other valve's Default state.
	const PORTKEY_FIELDS = ['PORTKEY_API_KEY', 'PORTKEY_API_BASE_URL'];

	// Per-field Switch state for the Portkey fields, kept in sync with `valves`.
	let customToggles = {};
	$: if (valvesSpec) {
		for (const property of Object.keys(valvesSpec.properties ?? {})) {
			if (PORTKEY_FIELDS.includes(property) && !(property in customToggles)) {
				const _v = valves[property] ?? null;
				const _ws = workspaceValues[property] ?? null;
				// Custom only when non-null, non-empty, AND differs from the workspace value.
				// A cascaded valve holds the workspace key directly — that should read as Workspace.
				customToggles[property] = _v !== null && _v !== '' && _v !== _ws;
				// Sync the two representations of "Workspace state" in the same tick so the
				// SensitiveInput read-only block renders immediately on open (not after a
				// toggle cycle). The renderer uses null as the signal for masked workspace view;
				// without this, a cascaded non-null value causes the plain editable input to
				// render first before Switch's reactive dispatch can correct it.
				if (!customToggles[property]) {
					valves[property] = null;
				}
			}
			// Pre-populate non-Portkey null fields from the Pydantic default so the
			// editable input always renders (no Default/Custom toggle needed).
			if (!PORTKEY_FIELDS.includes(property) && (valves[property] ?? null) === null) {
				valves[property] = valvesSpec.properties[property]?.default ?? '';
			}
		}
	}
</script>

{#if valvesSpec && Object.keys(valvesSpec?.properties ?? {}).length}
	{#each Object.keys(valvesSpec.properties) as property, idx}
		<div class=" py-0.5 w-full justify-between">
			<div class="flex w-full justify-between gap-2">
				<div class="min-w-0 self-center text-xs font-medium">
					{valvesSpec.properties[property].title}

					{#if (valvesSpec?.required ?? []).includes(property)}
						<span class=" text-gray-500">*required</span>
					{/if}

					{#if syncedFields.has(property) && !customToggles[property]}
						<span class="ml-1.5 text-[10px] font-normal text-[#57068c] dark:text-purple-400">
							{$i18n.t('Synced with Workspace Settings')}
						</span>
					{/if}
				</div>

				{#if PORTKEY_FIELDS.includes(property)}
					<div class="flex shrink-0 items-center gap-1.5">
						<span
							class="text-xs whitespace-nowrap transition-colors {!customToggles[property]
								? 'text-gray-900 dark:text-gray-100 font-medium'
								: 'text-gray-400 dark:text-gray-500'}"
						>
							{$i18n.t('Workspace')}
						</span>
						<Switch
							bind:state={customToggles[property]}
							on:change={() => {
								valves[property] = customToggles[property]
									? (valvesSpec.properties[property]?.default ?? '')
									: null;
								dispatch('change');
							}}
						/>
						<span
							class="text-xs whitespace-nowrap transition-colors {customToggles[property]
								? 'text-gray-900 dark:text-gray-100 font-medium'
								: 'text-gray-400 dark:text-gray-500'}"
						>
							{$i18n.t('Custom')}
						</span>
					</div>
				{/if}
			</div>

			{#if (valves[property] ?? null) !== null}
				<!-- {valves[property]} -->
				<div class="flex mt-0.5 mb-1.5 space-x-2">
					<div class=" flex-1">
						{#if valvesSpec.properties[property]?.enum ?? null}
							<select
								class="w-full rounded-lg py-2 px-4 text-sm dark:text-gray-300 dark:bg-gray-850 outline-hidden border border-gray-100 dark:border-gray-850"
								bind:value={valves[property]}
								on:change={() => {
									dispatch('change');
								}}
							>
								{#each valvesSpec.properties[property].enum as option}
									<option value={option} selected={option === valves[property]}>
										{option}
									</option>
								{/each}
							</select>
						{:else if (valvesSpec.properties[property]?.type ?? null) === 'boolean'}
							<div class="flex justify-between items-center">
								<div class="text-xs text-gray-600 dark:text-gray-500">
									{valves[property] ? 'Enabled' : 'Disabled'}
								</div>

								<div class=" pr-2">
									<Switch
										bind:state={valves[property]}
										on:change={() => {
											dispatch('change');
										}}
									/>
								</div>
							</div>
						{:else}
							<input
								class="w-full rounded-lg py-2 px-4 text-sm dark:text-gray-300 dark:bg-gray-850 outline-hidden border border-gray-100 dark:border-gray-850"
								type="text"
								placeholder={valvesSpec.properties[property].title}
								bind:value={valves[property]}
								autocomplete="off"
								required
								on:change={() => {
									dispatch('change');
								}}
							/>
						{/if}
					</div>
				</div>
			{:else if PORTKEY_FIELDS.includes(property)}
				<div class="flex mt-0.5 mb-1.5 space-x-2">
					<div class=" flex-1">
						<SensitiveInput
							value={workspaceValues[property] ?? ''}
							readOnly={true}
							masked={property === 'PORTKEY_API_KEY'}
							editHref={WORKSPACE_SETTINGS_PATH}
							editTooltip={property === 'PORTKEY_API_KEY'
								? $i18n.t('API key is managed via Workspace Settings')
								: $i18n.t('URL is managed via Workspace Settings')}
						/>
					</div>
				</div>
			{/if}

			{#if (valvesSpec.properties[property]?.description ?? null) !== null}
				<div class="text-xs text-gray-600 dark:text-gray-500">
					{valvesSpec.properties[property].description}
				</div>
			{/if}
		</div>
	{/each}
{:else}
	<div class="text-xs">No valves</div>
{/if}
