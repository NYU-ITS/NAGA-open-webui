<script>
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';

	import { WEBUI_NAME, config, user, showSidebar, knowledge } from '$lib/stores';
	import { WEBUI_BASE_URL } from '$lib/constants';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import UsersSolid from '$lib/components/icons/UsersSolid.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import User from '$lib/components/icons/User.svelte';
	import UserCircleSolid from '$lib/components/icons/UserCircleSolid.svelte';
	import GroupModal from './Groups/EditGroupModal.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import GroupItem from './Groups/GroupItem.svelte';
	import AddGroupModal from './Groups/AddGroupModal.svelte';
	import { createNewGroup, getGroups } from '$lib/apis/groups';
	import { getUserDefaultPermissions, updateUserDefaultPermissions } from '$lib/apis/users';
	import { groupSearchText } from './Groups/naming';

	const i18n = getContext('i18n');

	let loaded = false;

	export let users = [];

	let groups = [];
	let filteredGroups;

	let search = '';
	let categoryFilter = '';
	let schoolFilter = '';
	let toolFilter = '';
	let ownerFilter = '';

	const distinctNamingValues = (groups, key) =>
		[...new Set(groups.map((group) => group?.meta?.naming?.[key]).filter(Boolean))].sort();

	$: categoryOptions = distinctNamingValues(groups, 'category');
	$: schoolOptions = distinctNamingValues(groups, 'school');
	$: toolOptions = [
		...new Set(
			groups
				.map((group) => {
					const naming = group?.meta?.naming;
					return naming?.tool_name || naming?.tool_type;
				})
				.filter(Boolean)
		)
	].sort();
	$: ownerOptions = distinctNamingValues(groups, 'owner');

	$: hasNamingMetadata = groups.some((group) => {
		const naming = group?.meta?.naming ?? {};
		return (
			naming.category || naming.school || naming.tool_type || naming.tool_name || naming.owner
		);
	});

	$: filteredGroups = groups.filter((group) => {
		if (search !== '' && !groupSearchText(group).includes(search.toLowerCase())) {
			return false;
		}

		const naming = group?.meta?.naming ?? {};
		if (categoryFilter !== '' && naming.category !== categoryFilter) {
			return false;
		}
		if (schoolFilter !== '' && naming.school !== schoolFilter) {
			return false;
		}
		if (toolFilter !== '' && (naming.tool_name || naming.tool_type) !== toolFilter) {
			return false;
		}
		if (ownerFilter !== '' && naming.owner !== ownerFilter) {
			return false;
		}

		return true;
	});
	let defaultPermissions = {
		workspace: {
			models: false,
			knowledge: false,
			prompts: false,
			tools: false
		},
		chat: {
			controls: true,
			file_upload: true,
			delete: true,
			edit: true,
			temporary: true
		},
		features: {
			web_search: true,
			image_generation: true,
			code_interpreter: true
		}
	};

	let showCreateGroupModal = false;
	let showDefaultPermissionsModal = false;

	const setGroups = async () => {
		groups = await getGroups(localStorage.token);
	};

	const addGroupHandler = async (group) => {
		const res = await createNewGroup(localStorage.token, group).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Group created successfully'));
			groups = await getGroups(localStorage.token);
		}
	};

	const updateDefaultPermissionsHandler = async (group) => {
		console.log(group.permissions);

		const res = await updateUserDefaultPermissions(localStorage.token, group.permissions).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);

		if (res) {
			toast.success($i18n.t('Default permissions updated successfully'));
			defaultPermissions = await getUserDefaultPermissions(localStorage.token);
		}
	};

	onMount(async () => {
		if ($user?.role !== 'admin') {
			await goto('/');
		} else {
			await setGroups();
			defaultPermissions = await getUserDefaultPermissions(localStorage.token);
		}
		loaded = true;
	});
</script>

{#if loaded}
	<AddGroupModal bind:show={showCreateGroupModal} onSubmit={addGroupHandler} existingGroups={groups} />
	<div class="mt-0.5 mb-2 gap-1 flex flex-col md:flex-row justify-between">
		<div class="flex md:self-center text-lg font-medium px-0.5">
			{$i18n.t('Groups')}
			<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />

			<span class="text-lg font-medium text-gray-600 dark:text-gray-300">
				{#if filteredGroups.length !== groups.length}
					{filteredGroups.length} / {groups.length}
				{:else}
					{groups.length}
				{/if}
			</span>
		</div>

		<div class="flex gap-1">
			<div class=" flex w-full space-x-2">
				<div class="flex flex-1">
					<div class=" self-center ml-1 mr-3">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 20 20"
							fill="currentColor"
							class="w-4 h-4"
						>
							<path
								fill-rule="evenodd"
								d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z"
								clip-rule="evenodd"
							/>
						</svg>
					</div>
					<input
						class=" w-full text-sm pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
						bind:value={search}
						placeholder={$i18n.t('Search')}
					/>
				</div>

				<div>
					<Tooltip content={$i18n.t('Create Group')}>
						<button
							aria-label="Create Group"
							class=" p-2 rounded-xl hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 transition font-medium text-sm flex items-center space-x-1"
							on:click={() => {
								showCreateGroupModal = !showCreateGroupModal;
							}}
						>
							<Plus className="size-3.5" />
						</button>
					</Tooltip>
				</div>
			</div>
		</div>
	</div>

	{#if hasNamingMetadata}
		<div class="mb-2 flex flex-wrap items-center gap-1.5 px-0.5 text-xs">
			<select
				class="max-w-40 pl-2 pr-6 py-0.5 rounded-lg text-xs bg-gray-50 dark:bg-gray-850 outline-hidden {categoryFilter ===
				''
					? 'text-gray-600 dark:text-gray-400'
					: ''}"
				bind:value={categoryFilter}
				aria-label={$i18n.t('Filter by category')}
			>
				<option value="">{$i18n.t('All categories')}</option>
				{#each categoryOptions as option}
					<option value={option}>{option}</option>
				{/each}
			</select>

			<select
				class="max-w-48 pl-2 pr-6 py-0.5 rounded-lg text-xs bg-gray-50 dark:bg-gray-850 outline-hidden {schoolFilter ===
				''
					? 'text-gray-600 dark:text-gray-400'
					: ''}"
				bind:value={schoolFilter}
				aria-label={$i18n.t('Filter by school')}
			>
				<option value="">{$i18n.t('All schools')}</option>
				{#each schoolOptions as option}
					<option value={option}>{option}</option>
				{/each}
			</select>

			<select
				class="max-w-40 pl-2 pr-6 py-0.5 rounded-lg text-xs bg-gray-50 dark:bg-gray-850 outline-hidden {toolFilter ===
				''
					? 'text-gray-600 dark:text-gray-400'
					: ''}"
				bind:value={toolFilter}
				aria-label={$i18n.t('Filter by tool')}
			>
				<option value="">{$i18n.t('All tools')}</option>
				{#each toolOptions as option}
					<option value={option}>{option}</option>
				{/each}
			</select>

			<select
				class="max-w-40 pl-2 pr-6 py-0.5 rounded-lg text-xs bg-gray-50 dark:bg-gray-850 outline-hidden {ownerFilter ===
				''
					? 'text-gray-600 dark:text-gray-400'
					: ''}"
				bind:value={ownerFilter}
				aria-label={$i18n.t('Filter by owner')}
			>
				<option value="">{$i18n.t('All owners')}</option>
				{#each ownerOptions as option}
					<option value={option}>{option}</option>
				{/each}
			</select>

			{#if categoryFilter !== '' || schoolFilter !== '' || toolFilter !== '' || ownerFilter !== ''}
				<button
					class="px-2 py-0.5 rounded-lg text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click={() => {
						categoryFilter = '';
						schoolFilter = '';
						toolFilter = '';
						ownerFilter = '';
					}}
				>
					{$i18n.t('Clear filters')}
				</button>
			{/if}
		</div>
	{/if}

	<div>
		{#if filteredGroups.length === 0}
			<div class="flex flex-col items-center justify-center h-40">
				<div class=" text-xl font-medium">
					{$i18n.t('Organize your users')}
				</div>

				<div class="mt-1 text-sm dark:text-gray-300">
					{$i18n.t('Use groups to group your users and assign permissions.')}
				</div>

				<div class="mt-3">
					<button
						class=" px-4 py-1.5 text-sm rounded-full bg-black hover:bg-gray-800 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition font-medium flex items-center space-x-1"
						aria-label={$i18n.t('Create Group')}
						on:click={() => {
							showCreateGroupModal = true;
						}}
					>
						{$i18n.t('Create Group')}
					</button>
				</div>
			</div>
		{:else}
			<div>
				<div class=" flex items-center gap-3 text-xs uppercase px-1 font-bold">
					<div class="flex-1 min-w-0">Group</div>

					<div class="w-16 shrink-0">Users</div>

					<div class="w-24 shrink-0">Last Active</div>

					<div class="w-24 shrink-0">Created At</div>
					<div class="w-[320px] shrink-0 text-right">Actions</div>
				</div>

				<hr class="mt-1.5 border-gray-100 dark:border-gray-850" />

				{#each filteredGroups as group}
					<div class="my-2">
						<GroupItem {group} {users} {setGroups} />
					</div>
				{/each}
			</div>
		{/if}

		<hr class="mb-2 border-gray-100 dark:border-gray-850" />

		<GroupModal
			bind:show={showDefaultPermissionsModal}
			tabs={['permissions']}
			bind:permissions={defaultPermissions}
			custom={false}
			onSubmit={updateDefaultPermissionsHandler}
		/>

		<button
			class="flex items-center justify-between rounded-lg w-full transition pt-1"
			on:click={() => {
				showDefaultPermissionsModal = true;
			}}
		>
			<div class="flex items-center gap-2.5">
				<div class="p-1.5 bg-black/5 dark:bg-white/10 rounded-full">
					<UsersSolid className="size-4" />
				</div>

				<div class="text-left">
					<div class=" text-sm font-medium">{$i18n.t('Default permissions')}</div>

					<div class="flex text-xs mt-0.5">
						{$i18n.t('applies to all users with the "user" role')}
					</div>
				</div>
			</div>

			<div>
				<ChevronRight strokeWidth="2.5" />
			</div>
		</button>
	</div>
{/if}
