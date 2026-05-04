<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { WEBUI_NAME, showSidebar, user, mobile } from '$lib/stores';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { checkIfSuperAdmin } from '$lib/apis/users';
	import { getGroups } from '$lib/apis/groups';
	import { showAITutorTestToast } from '$lib/utils/aiTutorTesting';
	import { loadWorkspaceModels } from '$lib/stores/aiTutorWorkspaceModels';

	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';

	type GroupOption = {
		id: string;
		name: string;
		user_id?: string;
		user_ids?: string[];
		identity?: 'Admin' | 'Member' | 'View' | 'Super Admin';
	};

	const i18n: any = getContext('i18n');

	let loaded = false;
	let showIdentityPopover = false;
	let groupDropdownOpen = false;
	let groupSearchValue = '';
	let showHomeworkDropdown = false;
	let isSuperAdmin = false;
	let groups: GroupOption[] = [];
	let createdGroups: GroupOption[] = [];
	let memberGroups: GroupOption[] = [];
	let allUserGroups: GroupOption[] = [];
	let lastSelectedGroupId = '';
	let selectedGroup: GroupOption | null = null;
	let searchTopic = '';
	const LAST_SELECTED_GROUP_KEY = 'student_dashboard_last_selected_group_id';

	function getPersistedGroupId() {
		if (typeof localStorage === 'undefined') return '';
		return localStorage.getItem(LAST_SELECTED_GROUP_KEY) || '';
	}

	function persistGroupId(groupId: string) {
		if (typeof localStorage === 'undefined') return;
		if (!groupId) {
			localStorage.removeItem(LAST_SELECTED_GROUP_KEY);
			return;
		}
		localStorage.setItem(LAST_SELECTED_GROUP_KEY, groupId);
	}

	function sortGroupsForDefaultSelection(items: GroupOption[]) {
		return [...items].sort((a, b) => {
			const aHasClass = a.name.toLowerCase().includes('class');
			const bHasClass = b.name.toLowerCase().includes('class');
			if (aHasClass !== bHasClass) return aHasClass ? -1 : 1;
			return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
		});
	}

	let selectedHomework = 'All';
	// TODO(student-dashboard-backend): Replace the static homework/topic filter model with
	// student-scoped homework metadata from the AI Tutor backend once the student APIs exist.
	const homeworkOptions = [
		'All',
		'Homework 1',
		'Homework 2',
		'Homework 3',
		'Homework 4',
		'Homework 5',
		'Homework 6',
		'Homework 7'
	];
	const homeworkTopicMap: Record<string, string[]> = {
		'Homework 1': ['Linear Algebra', 'Differentiation', 'Integration', 'Limit Definition'],
		'Homework 2': ['Quadratic Equations', 'Polynomials', 'Factoring', 'Complex Numbers'],
		'Homework 3': ['Trigonometry', 'Unit Circle', 'Trigonometric Identities', 'Inverse Functions'],
		'Homework 4': ['Derivatives', 'Chain Rule', 'Product Rule', 'Quotient Rule'],
		'Homework 5': ['Integrals', 'Substitution', 'Integration by Parts', 'Partial Fractions'],
		'Homework 6': ['Matrices', 'Determinants', 'Vectors'],
		'Homework 7': ['Sequences', 'Series', 'Convergence']
	};

	$: filteredHomeworkOptions = homeworkOptions.filter((option) => {
		if (option === 'All' || searchTopic.trim() === '') {
			return true;
		}

		const query = searchTopic.trim().toLowerCase();
		return (homeworkTopicMap[option] ?? []).some((topic) => topic.toLowerCase().includes(query));
	});

	$: selectedGroupId = lastSelectedGroupId || $page.url.searchParams.get('group_id') || getPersistedGroupId() || '';
	$: selectedGroup =
		allUserGroups.find((group) => group.id === selectedGroupId) || allUserGroups[0] || null;

	$: if ($page.url.searchParams.get('group_id')) {
		persistGroupId($page.url.searchParams.get('group_id') || '');
	}

	$: filteredGroups = groupSearchValue
		? allUserGroups.filter((g) => g.name.toLowerCase().includes(groupSearchValue.toLowerCase()))
		: allUserGroups;

	onMount(async () => {
		loaded = true;
		showAITutorTestToast('loading studentdashboard - Layout');

		// Load user identity information
		if ($user && localStorage.token) {
			// Check if super admin
			try {
				isSuperAdmin = await checkIfSuperAdmin(localStorage.token, $user.email);
			} catch (error) {
				console.error('Error checking super admin status:', error);
			}

			// Load groups
			try {
				groups = await getGroups(localStorage.token);
				if (groups && Array.isArray(groups)) {
					// Separate created vs member groups
					createdGroups = groups.filter(g => g.user_id === $user.id);
					memberGroups = groups.filter(g => g.user_id !== $user.id && g.user_ids?.includes($user.id));

					// Combine all groups with identity
					// Super admins see every group the API returns, labelled as Super Admin.
					if (isSuperAdmin) {
						allUserGroups = sortGroupsForDefaultSelection(
							groups.map(g => ({
								...g,
								identity: 'Super Admin' as const
							}))
						);
					} else {
						allUserGroups = sortGroupsForDefaultSelection([
							...createdGroups.map((g) => ({ ...g, identity: 'Admin' as const })),
							...memberGroups.map((g) => ({ ...g, identity: 'Member' as const }))
						]);
					}

					if (!$page.url.searchParams.get('group_id') && allUserGroups.length > 0) {
						const persistedGroup = allUserGroups.find((group) => group.id === getPersistedGroupId());
						await selectGroup(persistedGroup ?? allUserGroups[0]);
					}
				}
			} catch (error) {
				console.error('Error loading groups:', error);
			}

			// Load workspace models for unified homework filtering
			try {
				await loadWorkspaceModels(localStorage.token);
			} catch (error) {
				console.error('Error loading workspace models:', error);
			}
		}

		selectedHomework = $page.url.searchParams.get('homework') || 'All';
		searchTopic = $page.url.searchParams.get('topic') || '';
	});

	function toggleIdentityPopover() {
		showIdentityPopover = !showIdentityPopover;
	}

	function closeIdentityPopover() {
		showIdentityPopover = false;
	}

	async function selectGroup(group: GroupOption) {
		lastSelectedGroupId = group.id;
		persistGroupId(group.id);
		groupDropdownOpen = false;
		groupSearchValue = '';
		const params = new URLSearchParams($page.url.searchParams);
		params.set('group_id', group.id);
		await goto(`${$page.url.pathname}?${params.toString()}`, {
			keepFocus: true,
			noScroll: true,
			replaceState: true
		});
	}

	function toggleHomeworkDropdown() {
		showHomeworkDropdown = !showHomeworkDropdown;
	}

	function closeHomeworkDropdown() {
		showHomeworkDropdown = false;
	}

	async function updateDashboardFilters(nextHomework = selectedHomework, nextTopic = searchTopic) {
		const params = new URLSearchParams($page.url.searchParams);

		if (!nextHomework || nextHomework === 'All') {
			params.delete('homework');
		} else {
			params.set('homework', nextHomework);
		}

		if (!nextTopic || nextTopic.trim() === '') {
			params.delete('topic');
		} else {
			params.set('topic', nextTopic.trim());
		}

		const query = params.toString();
		await goto(`${$page.url.pathname}${query ? `?${query}` : ''}`, {
			keepFocus: true,
			noScroll: true,
			replaceState: true
		});
	}
</script>

<svelte:head>
	<title>
		{$i18n.t('Student Dashboard')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div
		class="relative flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-260px)]'
			: ''} max-w-full"
	>
		<nav class="px-2.5 pt-1 backdrop-blur-xl drag-region relative" style="z-index: 1000;">
			<div class="flex items-center gap-1">
				<div class="{$showSidebar ? 'md:hidden' : ''} self-center flex flex-none items-center">
					<button
						id="sidebar-toggle-button"
						class="cursor-pointer p-1.5 flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click={() => {
							showSidebar.set(!$showSidebar);
						}}
						aria-label="Toggle Sidebar"
					>
						<div class="m-auto self-center">
							<MenuLines />
						</div>
					</button>
				</div>

				<div class="flex-1">
					<!-- Course Title with Info Button -->
					<div class="px-2 py-2 flex items-center justify-between">
						<!-- Group Dropdown (bits-ui) -->
						<div class="relative">
							<DropdownMenu.Root bind:open={groupDropdownOpen} closeFocus={false}>
								<DropdownMenu.Trigger class="relative w-full font-primary" aria-label="Select group">
									<div class="flex w-full text-left text-lg font-semibold text-gray-800 dark:text-gray-200 justify-between items-center gap-2">
										<div class="flex flex-col">
											<span>{$user?.name || 'Student Name'}</span>
											<div class="flex items-center gap-1 text-sm font-medium text-gray-500 dark:text-gray-400">
												<span>
													{#if selectedGroup}
														{selectedGroup.name} - {$user?.role === 'admin' ? 'Instructor View' : 'Student View'}
													{:else if loaded}
														No Group Selected
													{:else}
														Loading group...
													{/if}
												</span>
												<ChevronDown className="self-center size-3" strokeWidth="2.5" />
											</div>
										</div>
									</div>
								</DropdownMenu.Trigger>
								<DropdownMenu.Content
									class="z-40 w-[22rem] rounded-xl border border-gray-200 bg-white px-0 py-2 shadow-xl dark:border-gray-700 dark:bg-gray-850"
									sideOffset={8}
									transition={flyAndScale}
								>
									<div class="flex items-center gap-2.5 px-5 mt-3.5 mb-3">
										<Search className="size-4" strokeWidth="2.5" />
										<input
											id="group-search-input"
											type="text"
											bind:value={groupSearchValue}
											class="w-full text-sm bg-transparent outline-hidden text-gray-800 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-500"
											placeholder="Search groups"
											autocomplete="off"
											on:keydown={(e) => e.code === 'Enter' && filteredGroups.length > 0 && selectGroup(filteredGroups[0])}
										/>
									</div>
									<hr class="border-gray-100 dark:border-gray-700" />
									<div class="px-3 my-2 max-h-64 overflow-y-auto scrollbar-hidden group">
										{#each filteredGroups as group}
											<button
												on:click={() => selectGroup(group)}
												class="flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-sm text-gray-700 transition hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700"
											>
												<span class="truncate">{group.name}</span>
												<span class="shrink-0 px-2 py-0.5 text-xs font-medium rounded {group.identity === 'Admin'
													? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200'
													: group.identity === 'Member'
													? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
													: group.identity === 'Super Admin'
													? 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200'
													: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'}">
													{group.identity}
												</span>
												{#if selectedGroupId === group.id}
													<Check className="ml-2 size-4 text-[#57068C]" strokeWidth="2.5" />
												{/if}
											</button>
										{/each}
									</div>
								</DropdownMenu.Content>
							</DropdownMenu.Root>
						</div>

						<!-- Info Button (temporarily hidden) -->
						{#if false}
						<div class="relative">
							<button
								on:click={toggleIdentityPopover}
								class="p-2 rounded-full hover:bg-gray-100 dark:hover:bg-gray-800 transition"
								aria-label="Account Information"
							>
								<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-gray-600 dark:text-gray-400">
									<path stroke-linecap="round" stroke-linejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
								</svg>
							</button>

							<!-- Identity Popover -->
							{#if showIdentityPopover}
								<div
									class="absolute right-0 mt-2 w-80 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-4"
									style="z-index: 9999;"
									on:mouseleave={closeIdentityPopover}
								>
									<!-- User Info -->
									<div class="mb-4">
										<h3 class="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
											Account Information
										</h3>
										<div class="space-y-1 text-sm">
											<div class="flex items-center gap-2">
												<span class="text-gray-600 dark:text-gray-400">Name:</span>
												<span class="text-gray-900 dark:text-gray-100 font-medium">{$user?.name || 'N/A'}</span>
											</div>
											<div class="flex items-center gap-2">
												<span class="text-gray-600 dark:text-gray-400">Email:</span>
												<span class="text-gray-900 dark:text-gray-100">{$user?.email || 'N/A'}</span>
											</div>
										</div>
									</div>

									<!-- Identity/Role -->
									<div class="mb-4 border-t border-gray-200 dark:border-gray-700 pt-3">
										<h3 class="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
											Identity
										</h3>
										<div class="flex flex-wrap gap-2">
											{#if isSuperAdmin}
												<span class="px-2 py-1 text-xs font-medium bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 rounded">
													Super Admin
												</span>
											{/if}
											{#if $user?.role === 'admin'}
												<span class="px-2 py-1 text-xs font-medium bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 rounded">
													Admin
												</span>
											{:else if $user?.role === 'user'}
												<span class="px-2 py-1 text-xs font-medium bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 rounded">
													User
												</span>
											{:else if $user?.role === 'pending'}
												<span class="px-2 py-1 text-xs font-medium bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200 rounded">
													Pending
												</span>
											{/if}
										</div>
									</div>

									<!-- Groups Created -->
									{#if createdGroups.length > 0}
										<div class="mb-4 border-t border-gray-200 dark:border-gray-700 pt-3">
											<h3 class="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
												Groups Created ({createdGroups.length})
											</h3>
											<div class="space-y-1 max-h-32 overflow-y-auto">
												{#each createdGroups as group}
													<div class="text-sm text-gray-700 dark:text-gray-300 py-1 px-2 bg-gray-50 dark:bg-gray-800 rounded">
														{group.name}
													</div>
												{/each}
											</div>
										</div>
									{/if}

									<!-- Groups Member Of -->
									{#if memberGroups.length > 0}
										<div class="border-t border-gray-200 dark:border-gray-700 pt-3">
											<h3 class="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
												Member of Groups ({memberGroups.length})
											</h3>
											<div class="space-y-1 max-h-32 overflow-y-auto">
												{#each memberGroups as group}
													<div class="text-sm text-gray-700 dark:text-gray-300 py-1 px-2 bg-gray-50 dark:bg-gray-800 rounded">
														{group.name}
													</div>
												{/each}
											</div>
										</div>
									{/if}

									{#if createdGroups.length === 0 && memberGroups.length === 0}
										<div class="border-t border-gray-200 dark:border-gray-700 pt-3">
											<p class="text-sm text-gray-500 dark:text-gray-400">
												Not a member of any groups
											</p>
										</div>
									{/if}
								</div>
							{/if}
						</div>
						{/if}
					</div>
				</div>
			</div>
		</nav>

		<div class="pb-1 px-[18px] flex-1 max-h-full overflow-y-auto" style="scrollbar-gutter: stable" id="studentdashboard-container">
			<slot />
		</div>
	</div>
{/if}
