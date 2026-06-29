<script>
	import { onMount, getContext, createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	import Switch from './Switch.svelte';

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
				customToggles[property] = (valves[property] ?? null) !== null;
			}
		}
	}
</script>

{#if valvesSpec && Object.keys(valvesSpec?.properties ?? {}).length}
	{#each Object.keys(valvesSpec.properties) as property, idx}
		<div class=" py-0.5 w-full justify-between">
			<div class="flex w-full justify-between">
				<div class=" self-center text-xs font-medium">
					{valvesSpec.properties[property].title}

					{#if (valvesSpec?.required ?? []).includes(property)}
						<span class=" text-gray-500">*required</span>
					{/if}

					{#if syncedFields.has(property)}
						<span class="ml-1.5 text-[10px] font-normal text-[#57068c] dark:text-purple-400">
							{$i18n.t('Synced with Workspace Settings')}
						</span>
					{/if}
				</div>

				{#if PORTKEY_FIELDS.includes(property)}
					<Switch
						bind:state={customToggles[property]}
						on:change={() => {
							valves[property] = customToggles[property]
								? (valvesSpec.properties[property]?.default ?? '')
								: null;

							dispatch('change');
						}}
					/>
				{:else}
					<button
						class="p-1 px-3 text-xs flex rounded-sm transition"
						type="button"
						on:click={() => {
							valves[property] =
								(valves[property] ?? null) === null
									? (valvesSpec.properties[property]?.default ?? '')
									: null;

							dispatch('change');
						}}
					>
						{#if (valves[property] ?? null) === null}
							<span class="ml-2 self-center">
								{#if (valvesSpec?.required ?? []).includes(property)}
									{$i18n.t('None')}
								{:else}
									{$i18n.t('Default')}
								{/if}
							</span>
						{:else}
							<span class="ml-2 self-center"> {$i18n.t('Custom')} </span>
						{/if}
					</button>
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
						<input
							class="w-full rounded-lg py-2 px-4 text-sm text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-900 outline-hidden border border-gray-100 dark:border-gray-850 cursor-not-allowed"
							type="text"
							value={workspaceValues[property] ?? ''}
							disabled
							readonly
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
