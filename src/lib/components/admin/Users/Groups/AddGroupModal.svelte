<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { user } from '$lib/stores';

	import Modal from '$lib/components/common/Modal.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import {
		CATEGORY_OPTIONS,
		SCHOOL_OPTIONS,
		SEMESTER_OPTIONS,
		TOOL_TYPE_OPTIONS,
		generateGroupName,
		yearOptions
	} from './naming';

	export let onSubmit: Function = () => {};
	export let show = false;
	export let existingGroups: { name?: string }[] = [];

	const OTHER = '__other__';
	const years = yearOptions();

	let category = '';
	let semester = '';
	let year = '';
	let school = '';
	let customSchool = '';
	let department = '';
	let toolType = '';
	let customToolType = '';
	let toolName = '';
	let owner = '';
	let customName = '';
	let nameDirty = false;
	let description = '';

	let loading = false;

	let wasShown = false;
	$: if (show && !wasShown) {
		resetFields();
		wasShown = true;
	} else if (!show) {
		wasShown = false;
	}

	const resetFields = () => {
		category = '';
		semester = '';
		year = '';
		school = '';
		customSchool = '';
		department = '';
		toolType = '';
		customToolType = '';
		toolName = '';
		owner = $user?.name ?? '';
		customName = '';
		nameDirty = false;
		description = '';
	};

	$: effectiveSchool = school === OTHER ? customSchool.trim() : school;
	$: effectiveToolType = toolType === OTHER ? customToolType.trim() : toolType;

	$: generatedName = generateGroupName({
		category,
		semester,
		year,
		school: effectiveSchool,
		department,
		toolType: effectiveToolType,
		toolName,
		owner
	});

	// The name field is prefilled with the generated name and kept in sync until
	// the user edits it, so they can tweak from a filled starting point (Reset
	// restores this link). generatedName does not depend on customName, so this
	// never loops.
	$: if (!nameDirty) customName = generatedName;

	$: displayName = customName.trim();
	$: isCustom = nameDirty && customName.trim() !== generatedName.trim();

	$: isDuplicate =
		displayName !== '' &&
		existingGroups.some((group) => group?.name?.toLowerCase() === displayName.toLowerCase());

	const submitHandler = async () => {
		if (semester !== '' && year === '') {
			toast.error($i18n.t('Select a year for the chosen semester.'));
			return;
		}
		if (displayName === '') {
			toast.error(
				$i18n.t('Enter a group name, or fill in the classification fields to generate one.')
			);
			return;
		}

		loading = true;

		const group = {
			name: displayName,
			description,
			meta: {
				naming: {
					category,
					semester,
					year,
					school: effectiveSchool,
					department: department.trim(),
					tool_type: effectiveToolType,
					tool_name: toolName.trim(),
					owner: owner.trim() || ($user?.name ?? ''),
					custom: isCustom
				}
			}
		};

		await onSubmit(group);

		loading = false;
		show = false;

		resetFields();
	};
</script>

<Modal size="md" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-100 px-5 pt-4 mb-1.5">
			<div class=" text-lg font-medium self-center font-primary">
				{$i18n.t('Add User Group')}
			</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-4 pb-4 md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit={(e) => {
						e.preventDefault();
						submitHandler();
					}}
				>
					<div class="px-1 flex flex-col w-full">
						<div class="text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase mb-1.5">
							{$i18n.t('Classification')}
						</div>

						<div class="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2">
							<div class="flex flex-col w-full">
								<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-400">
									{$i18n.t('Category')} <span class="text-gray-600 dark:text-gray-400">*</span>
								</div>
								<select
									class="w-full text-sm bg-transparent dark:bg-gray-900 outline-hidden py-0.5 {category ===
									''
										? 'text-gray-500 dark:text-gray-500'
										: ''}"
									bind:value={category}
									aria-label={$i18n.t('Category')}
								>
									<option value="" disabled>{$i18n.t('Select a category')}</option>
									{#each CATEGORY_OPTIONS as option}
										<option value={option.value}>{option.value}</option>
									{/each}
								</select>
							</div>

							<div class="flex flex-col w-full">
								<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-400">
									{$i18n.t('School / Unit')}
									<span class="text-gray-600 dark:text-gray-400">*</span>
								</div>
								<select
									class="w-full text-sm bg-transparent dark:bg-gray-900 outline-hidden py-0.5 {school ===
									''
										? 'text-gray-500 dark:text-gray-500'
										: ''}"
									bind:value={school}
									aria-label={$i18n.t('School / Unit')}
								>
									<option value="" disabled>{$i18n.t('Select a school or unit')}</option>
									{#each SCHOOL_OPTIONS as option}
										<option value={option.value}>{option.value}</option>
									{/each}
									<option value={OTHER}>{$i18n.t('Other (enter below)')}</option>
								</select>
								{#if school === OTHER}
									<input
										class="w-full text-sm bg-transparent placeholder:text-gray-500 dark:placeholder:text-gray-500 outline-hidden py-0.5 mt-1"
										type="text"
										bind:value={customSchool}
										placeholder={$i18n.t('School or unit name')}
										autocomplete="off"
									/>
								{/if}
							</div>

							<div class="flex flex-col w-full">
								<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-400">
									{$i18n.t('Semester')}
								</div>
								<select
									class="w-full text-sm bg-transparent dark:bg-gray-900 outline-hidden py-0.5 {semester ===
									''
										? 'text-gray-500 dark:text-gray-500'
										: ''}"
									bind:value={semester}
									aria-label={$i18n.t('Semester')}
								>
									<option value="">{$i18n.t('None')}</option>
									{#each SEMESTER_OPTIONS as option}
										<option value={option}>{option}</option>
									{/each}
								</select>
							</div>

							<div class="flex flex-col w-full">
								<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-400">
									{$i18n.t('Year')}
									{#if semester !== ''}
										<span class="text-gray-600 dark:text-gray-400">*</span>
									{/if}
								</div>
								<select
									class="w-full text-sm bg-transparent dark:bg-gray-900 outline-hidden py-0.5 {year ===
									''
										? 'text-gray-500 dark:text-gray-500'
										: ''}"
									bind:value={year}
									aria-label={$i18n.t('Year')}
								>
									<option value="">{$i18n.t('None')}</option>
									{#each years as y}
										<option value={String(y)}>{y}</option>
									{/each}
								</select>
								{#if semester !== '' && year === ''}
									<div class="mt-0.5 text-xs text-amber-600 dark:text-amber-400">
										{$i18n.t('Select a year for the chosen semester.')}
									</div>
								{/if}
							</div>

							<div class="flex flex-col w-full">
								<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-400">
									{$i18n.t('Department')}
								</div>
								<input
									class="w-full text-sm bg-transparent placeholder:text-gray-500 dark:placeholder:text-gray-500 outline-hidden py-0.5"
									type="text"
									bind:value={department}
									placeholder={$i18n.t('e.g. Computer Science (optional)')}
									autocomplete="off"
								/>
							</div>

							<div class="flex flex-col w-full">
								<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-400">
									{$i18n.t('Tool Type')} <span class="text-gray-600 dark:text-gray-400">*</span>
								</div>
								<select
									class="w-full text-sm bg-transparent dark:bg-gray-900 outline-hidden py-0.5 {toolType ===
									''
										? 'text-gray-500 dark:text-gray-500'
										: ''}"
									bind:value={toolType}
									aria-label={$i18n.t('Tool Type')}
								>
									<option value="" disabled>{$i18n.t('Select a tool type')}</option>
									{#each TOOL_TYPE_OPTIONS as option}
										<option value={option}>{option}</option>
									{/each}
									<option value={OTHER}>{$i18n.t('Other (enter below)')}</option>
								</select>
								{#if toolType === OTHER}
									<input
										class="w-full text-sm bg-transparent placeholder:text-gray-500 dark:placeholder:text-gray-500 outline-hidden py-0.5 mt-1"
										type="text"
										bind:value={customToolType}
										placeholder={$i18n.t('Tool type')}
										autocomplete="off"
									/>
								{/if}
							</div>

							<div class="flex flex-col w-full">
								<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-400">
									{$i18n.t('Tool Name / Course Name')}
								</div>
								<input
									class="w-full text-sm bg-transparent placeholder:text-gray-500 dark:placeholder:text-gray-500 outline-hidden py-0.5"
									type="text"
									bind:value={toolName}
									placeholder={$i18n.t('e.g. Calculus AI Tutor (optional)')}
									autocomplete="off"
								/>
							</div>

							<div class="flex flex-col w-full">
								<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-400">
									{$i18n.t('Group Owner / Admin')}
									<span class="text-gray-600 dark:text-gray-400">*</span>
								</div>
								<input
									class="w-full text-sm bg-transparent placeholder:text-gray-500 dark:placeholder:text-gray-500 outline-hidden py-0.5"
									type="text"
									bind:value={owner}
									placeholder={$i18n.t('Owner name')}
									autocomplete="off"
								/>
							</div>
						</div>

						<hr class="my-3 border-gray-100 dark:border-gray-850" />

						<div class="text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase mb-1.5">
							{$i18n.t('Naming')}
						</div>

						<div class="flex flex-col w-full">
							<div class="mb-0.5 flex items-center justify-between">
								<div class="text-xs text-gray-600 dark:text-gray-400">
									{$i18n.t('Group Name')}
								</div>
								{#if isCustom}
									<button
										type="button"
										class="text-xs text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 hover:underline transition"
										on:click={() => {
											customName = generatedName;
											nameDirty = false;
										}}
									>
										{$i18n.t('Reset to generated name')}
									</button>
								{/if}
							</div>
							<input
								class="w-full text-sm bg-transparent placeholder:text-gray-500 dark:placeholder:text-gray-500 outline-hidden py-0.5"
								type="text"
								bind:value={customName}
								on:input={() => {
									nameDirty = true;
								}}
								placeholder={$i18n.t('Group Name')}
								autocomplete="off"
							/>
							<div class="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
								{$i18n.t(
									'Prefilled from the classification fields above. Edit for a custom name, or Reset to restore.'
								)}
							</div>
						</div>

						<div
							class="mt-2 px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800"
						>
							<div class="flex items-center justify-between">
								<div class="text-xs text-gray-600 dark:text-gray-400">
									{$i18n.t('Group will be created as')}
								</div>
								<div
									class="text-[10px] px-1.5 py-0.5 rounded-full {isCustom
										? 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200'
										: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'}"
								>
									{isCustom ? $i18n.t('Custom name') : $i18n.t('Auto-generated')}
								</div>
							</div>
							<div class="mt-0.5 text-sm font-medium dark:text-gray-100 min-h-5">
								{#if displayName !== ''}
									{displayName}
								{:else}
									<span class="text-gray-600 dark:text-gray-400">
										{$i18n.t('Fill in the fields above to generate a name')}
									</span>
								{/if}
							</div>
							{#if isDuplicate}
								<div class="mt-1 text-xs text-amber-600 dark:text-amber-400">
									{$i18n.t('A group with this name already exists.')}
								</div>
							{/if}
						</div>

						<div class="flex flex-col w-full mt-2">
							<div class=" mb-1 text-xs text-gray-600 dark:text-gray-400">
								{$i18n.t('Description')}
							</div>

							<div class="flex-1">
								<Textarea
									className="w-full text-sm bg-transparent placeholder:text-gray-500 dark:placeholder:text-gray-500 outline-hidden resize-none"
									rows={2}
									bind:value={description}
									placeholder={$i18n.t('Group Description')}
								/>
							</div>
						</div>
					</div>

					<div class="flex justify-end pt-3 text-sm font-medium gap-1.5">
						<button
							class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full flex flex-row space-x-1 items-center {loading
								? ' cursor-not-allowed'
								: ''}"
							type="submit"
							disabled={loading}
						>
							{$i18n.t('Create')}

							{#if loading}
								<div class="ml-2 self-center">
									<svg
										class=" w-4 h-4"
										viewBox="0 0 24 24"
										fill="currentColor"
										xmlns="http://www.w3.org/2000/svg"
										><style>
											.spinner_ajPY {
												transform-origin: center;
												animation: spinner_AtaB 0.75s infinite linear;
											}
											@keyframes spinner_AtaB {
												100% {
													transform: rotate(360deg);
												}
											}
										</style><path
											d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z"
											opacity=".25"
										/><path
											d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z"
											class="spinner_ajPY"
										/></svg
									>
								</div>
							{/if}
						</button>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>
