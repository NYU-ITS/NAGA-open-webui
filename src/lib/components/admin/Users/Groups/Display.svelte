<script lang="ts">
	import { getContext } from 'svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import {
		CATEGORY_OPTIONS,
		SCHOOL_OPTIONS,
		TOOL_TYPE_OPTIONS,
		emptyNaming,
		generateGroupName
	} from './naming';

	const i18n = getContext('i18n');

	export let name = '';
	export let created_by = '';
	export let created_at = '';
	export let updated_at = '';
	export let description = '';
	export let naming = emptyNaming();
	export let co_admin_emails: string[] | undefined = undefined;

	$: generatedName = generateGroupName({
		category: naming.category,
		school: naming.school,
		department: naming.department,
		toolType: naming.tool_type,
		toolName: naming.tool_name,
		owner: naming.owner
	});

	// A group can carry a school that is not in the static dropdown list (typed
	// through the "Other" option at creation), so keep it selectable here.
	$: schoolChoices =
		naming.school && !SCHOOL_OPTIONS.some((option) => option.value === naming.school)
			? [...SCHOOL_OPTIONS, { value: naming.school, abbreviation: naming.school }]
			: SCHOOL_OPTIONS;
</script>

<div class="flex gap-2">
	<div class="flex flex-col w-full">
		<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-500">{$i18n.t('Name')}</div>

		<div class="flex-1">
			<input
				class="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-hidden"
				type="text"
				bind:value={name}
				placeholder={$i18n.t('Group Name')}
				autocomplete="off"
				required
			/>
		</div>

		{#if generatedName !== '' && generatedName !== name}
			<div class="mt-1 flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
				<span>{$i18n.t('Generated name')}: {generatedName}</span>
				<button
					class="px-1.5 py-0.5 rounded-full bg-gray-100 hover:bg-gray-200 text-gray-600 dark:bg-gray-800 dark:hover:bg-gray-700 dark:text-gray-400 transition"
					type="button"
					on:click={() => {
						name = generatedName;
					}}
				>
					{$i18n.t('Use')}
				</button>
			</div>
		{/if}
	</div>
</div>

<div class="flex flex-col w-full mt-2">
	<div class=" mb-1 text-xs text-gray-600 dark:text-gray-500">{$i18n.t('Description')}</div>

	<div class="flex-1">
		<Textarea
			className="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-hidden resize-none"
			rows={2}
			bind:value={description}
			placeholder={$i18n.t('Group Description')}
		/>
	</div>
</div>

<hr class="my-2 border-gray-100 dark:border-gray-850" />

<div class="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase mb-1.5">
	{$i18n.t('Classification')}
</div>

<div class="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2">
	<div class="flex flex-col w-full">
		<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-500">{$i18n.t('Category')}</div>
		<select
			class="w-full text-sm bg-transparent dark:bg-gray-900 outline-hidden py-0.5 {naming.category ===
			''
				? 'text-gray-400 dark:text-gray-500'
				: ''}"
			bind:value={naming.category}
			aria-label={$i18n.t('Category')}
		>
			<option value="">{$i18n.t('None')}</option>
			{#each CATEGORY_OPTIONS as option}
				<option value={option.value}>{option.value}</option>
			{/each}
		</select>
	</div>

	<div class="flex flex-col w-full">
		<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-500">{$i18n.t('School / Unit')}</div>
		<select
			class="w-full text-sm bg-transparent dark:bg-gray-900 outline-hidden py-0.5 {naming.school ===
			''
				? 'text-gray-400 dark:text-gray-500'
				: ''}"
			bind:value={naming.school}
			aria-label={$i18n.t('School / Unit')}
		>
			<option value="">{$i18n.t('None')}</option>
			{#each schoolChoices as option}
				<option value={option.value}>{option.value}</option>
			{/each}
		</select>
	</div>

	<div class="flex flex-col w-full">
		<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-500">{$i18n.t('Department')}</div>
		<input
			class="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-hidden py-0.5"
			type="text"
			bind:value={naming.department}
			placeholder={$i18n.t('e.g. Computer Science (optional)')}
			autocomplete="off"
		/>
	</div>

	<div class="flex flex-col w-full">
		<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-500">{$i18n.t('Tool Type')}</div>
		<select
			class="w-full text-sm bg-transparent dark:bg-gray-900 outline-hidden py-0.5 {naming.tool_type ===
			''
				? 'text-gray-400 dark:text-gray-500'
				: ''}"
			bind:value={naming.tool_type}
			aria-label={$i18n.t('Tool Type')}
		>
			<option value="">{$i18n.t('None')}</option>
			{#each TOOL_TYPE_OPTIONS as option}
				<option value={option}>{option}</option>
			{/each}
		</select>
	</div>

	<div class="flex flex-col w-full">
		<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-500">{$i18n.t('Tool Name')}</div>
		<input
			class="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-hidden py-0.5"
			type="text"
			bind:value={naming.tool_name}
			placeholder={$i18n.t('e.g. Calculus AI Tutor (optional)')}
			autocomplete="off"
		/>
	</div>

	<div class="flex flex-col w-full">
		<div class=" mb-0.5 text-xs text-gray-600 dark:text-gray-500">
			{$i18n.t('Group Owner / Admin')}
		</div>
		<input
			class="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-hidden py-0.5"
			type="text"
			bind:value={naming.owner}
			placeholder={$i18n.t('Owner name')}
			autocomplete="off"
		/>
	</div>
</div>

<hr class="my-2 border-gray-100 dark:border-gray-850" />

<div class="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase mb-1.5">
	{$i18n.t('Details')}
</div>

<div class="flex flex-col gap-1.5 text-sm">
	<div class="flex gap-2">
		<div class="w-24 shrink-0 text-xs text-gray-600 dark:text-gray-500 pt-0.5">
			{$i18n.t('Created by')}
		</div>
		<div class="dark:text-gray-300 break-all">{created_by}</div>
	</div>

	{#if co_admin_emails !== undefined}
		<div class="flex gap-2">
			<div class="w-24 shrink-0 text-xs text-gray-600 dark:text-gray-500 pt-0.5">
				{co_admin_emails.length > 1 ? $i18n.t('Co-admins') : $i18n.t('Co-admin')}
			</div>
			<div class="flex flex-wrap gap-1 dark:text-gray-300">
				{#if co_admin_emails.length > 0}
					{#each co_admin_emails as email}
						<div class="break-all">{email}</div>
					{/each}
				{:else}
					<div class="text-gray-500 dark:text-gray-600">{$i18n.t('None')}</div>
				{/if}
			</div>
		</div>
	{/if}

	<div class="flex gap-2">
		<div class="w-24 shrink-0 text-xs text-gray-600 dark:text-gray-500 pt-0.5">
			{$i18n.t('Created at')}
		</div>
		<div class="dark:text-gray-300">{created_at}</div>
	</div>

	<div class="flex gap-2">
		<div class="w-24 shrink-0 text-xs text-gray-600 dark:text-gray-500 pt-0.5">
			{$i18n.t('Updated at')}
		</div>
		<div class="dark:text-gray-300">{updated_at}</div>
	</div>
</div>
