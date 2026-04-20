<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { WEBUI_NAME, showSidebar, user, mobile, aiTutorSelectedGroupId } from '$lib/stores';
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

	const i18n = getContext('i18n');
	const LAST_AI_TUTOR_GROUP_STORAGE_KEY = 'ai_tutor_last_selected_group_id';

	let loaded = false;
	let showIdentityPopover = false;
	let groupDropdownOpen = false;
	let groupSearchValue = '';
	let isSwitchingGroup = false;
	let isSuperAdmin = false;
	let groups = [];
	let createdGroups = [];
	let memberGroups = [];
	let allUserGroups = []; // All groups with identity (Admin/Member)
	let selectedGroupId = '';
	let selectedGroup = null;

	function sortGroupsForDefaultSelection(groups) {
		return [...groups].sort((a, b) => {
			const aName = String(a?.name ?? '');
			const bName = String(b?.name ?? '');
			const aHasClass = aName.toLowerCase().includes('class');
			const bHasClass = bName.toLowerCase().includes('class');
			if (aHasClass !== bHasClass) return aHasClass ? -1 : 1;
			return aName.localeCompare(bName, undefined, { numeric: true, sensitivity: 'base' });
		});
	}

	function buildDashboardHref(pathname: string) {
		const url = new URL($page.url);
		url.pathname = pathname;
		return url.toString();
	}

	function getPersistedGroupId() {
		if (typeof localStorage === 'undefined') return '';
		return localStorage.getItem(LAST_AI_TUTOR_GROUP_STORAGE_KEY) || '';
	}

	let lastSelectedGroupId = '';
	$: selectedGroupId = lastSelectedGroupId || $page.url.searchParams.get('group_id') || getPersistedGroupId();

	// Sync URL group_id to store (single source of truth for child pages)
	$: {
		const urlGroup = $page.url.searchParams.get('group_id');
		if (urlGroup && urlGroup !== $aiTutorSelectedGroupId) {
			aiTutorSelectedGroupId.set(urlGroup);
			if (typeof localStorage !== 'undefined') {
				localStorage.setItem(LAST_AI_TUTOR_GROUP_STORAGE_KEY, urlGroup);
			}
		}
	}
	$: selectedGroup =
		allUserGroups.find((group) => group.id === selectedGroupId) || allUserGroups[0] || null;

	onMount(async () => {
		loaded = true;
		showAITutorTestToast('loading aitutordashboard - Layout');
		console.log('[aitutordashboard]-[Layout]-[Mount]:', {
			pathname: $page.url.pathname,
			groupIdFromUrl: $page.url.searchParams.get('group_id') || '',
			persistedGroupId: getPersistedGroupId()
		});

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
				// TODO: Wire to API: GET /api/v1/groups
				groups = await getGroups(localStorage.token);
				showAITutorTestToast('aitutordashboard layout loaded groups');
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
								identity: 'Super Admin'
							}))
						);
					} else {
						allUserGroups = sortGroupsForDefaultSelection([
							...createdGroups.map(g => ({ ...g, identity: 'Admin' })),
							...memberGroups.map(g => ({ ...g, identity: 'Member' }))
						]);
					}
					console.log('[aitutordashboard]-[Layout]-[GroupsResolved]:', {
						selectedGroupId,
						selectedGroupName: selectedGroup?.name ?? '',
						groupCount: allUserGroups.length,
						groups: allUserGroups.map((group) => ({
							id: group.id,
							name: group.name,
							identity: group.identity
						}))
					});

					if (!$page.url.searchParams.get('group_id') && allUserGroups.length > 0) {
						const persistedGroup = allUserGroups.find((group) => group.id === getPersistedGroupId());
						await selectGroup(persistedGroup ?? allUserGroups[0]);
					}
				}
			} catch (error) {
				showAITutorTestToast('aitutordashboard layout failed loading groups');
				console.error('Error loading groups:', error);
			}

			// Load workspace models for unified homework filtering across all tabs
			try {
				await loadWorkspaceModels(localStorage.token);
			} catch (error) {
				console.error('Error loading workspace models:', error);
			}
		}
	});

	function toggleIdentityPopover() {
		showIdentityPopover = !showIdentityPopover;
	}

	function closeIdentityPopover() {
		showIdentityPopover = false;
	}

	async function selectGroup(group) {
		lastSelectedGroupId = group.id;
		aiTutorSelectedGroupId.set(group.id);
		if (typeof localStorage !== 'undefined') {
			localStorage.setItem(LAST_AI_TUTOR_GROUP_STORAGE_KEY, group.id);
		}
		isSwitchingGroup = true;
		const params = new URLSearchParams($page.url.searchParams);
		params.set('group_id', group.id);
		await goto(`${$page.url.pathname}?${params.toString()}`, {
			keepFocus: true,
			noScroll: true,
			replaceState: true
		});
		isSwitchingGroup = false;
	}

	async function selectGroupAndClose(group) {
		await selectGroup(group);
		groupDropdownOpen = false;
		groupSearchValue = '';
	}

	$: filteredGroups = groupSearchValue
		? allUserGroups.filter((g) =>
				g.name.toLowerCase().includes(groupSearchValue.toLowerCase())
			)
		: allUserGroups;
</script>

<svelte:head>
	<title>
		{$i18n.t('AI Tutor Dashboard')} | {$WEBUI_NAME}
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
						<!-- [Group Select] Course Title Dropdown -->
						<div class="relative">
							<DropdownMenu.Root bind:open={groupDropdownOpen} closeFocus={false}>
								<DropdownMenu.Trigger
									class="relative w-full font-primary"
									aria-label="Select group"
								>
									<div
										class="flex w-full text-left px-0.5 outline-hidden bg-transparent truncate text-lg justify-between font-medium placeholder-gray-400 focus:outline-hidden text-gray-800 dark:text-gray-200 hover:text-gray-600 dark:hover:text-gray-400 transition"
									>
										{#if selectedGroup}
											{selectedGroup.name}
										{:else if loaded}
											No Group
										{:else}
											Loading...
										{/if}
										<ChevronDown className="self-center ml-2 size-3" strokeWidth="2.5" />
									</div>
								</DropdownMenu.Trigger>

								<DropdownMenu.Content
									class="z-[1001] w-[22rem] rounded-xl border border-gray-200 bg-white px-0 py-2 shadow-xl dark:border-gray-700 dark:bg-gray-850"
									transition={flyAndScale}
									sideOffset={8}
								>
									<div class="flex items-center gap-2.5 px-5 mt-3.5 mb-3" style="background-color: white !important;">
										<Search className="size-4" strokeWidth="2.5" />

										<input
											id="group-search-input"
											type="text"
											bind:value={groupSearchValue}
											class="w-full text-sm outline-hidden text-gray-800 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-500" style="background-color: white !important; color: black !important; border: 1px solid #d1d5db !important; padding: 4px 8px !important; border-radius: 6px !important;"
											placeholder="Search groups"
											autocomplete="off"
											on:keydown={(e) => {
												if (e.code === 'Enter' && filteredGroups.length > 0) {
													selectGroupAndClose(filteredGroups[0]);
												}
											}}
										/>
									</div>

									<hr class="border-gray-100 dark:border-gray-700" />

									<div class="px-3 my-2 max-h-64 overflow-y-auto scrollbar-hidden group">
										{#each filteredGroups as group}
											<button
												type="button"
												class="flex w-full text-left font-medium line-clamp-1 select-none items-center rounded-button py-2 pl-3 pr-1.5 text-sm text-gray-700 dark:text-gray-100 outline-hidden transition-all duration-75 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg cursor-pointer data-highlighted:bg-muted"
												on:click={() => selectGroupAndClose(group)}
											>
												<div class="flex flex-1 items-center justify-between min-w-0 gap-2">
													<span class="truncate">
														{group.name}
													</span>
													<span
														class="shrink-0 px-2 py-0.5 text-xs font-medium rounded {group.identity === 'Super Admin'
															? 'bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200'
															: group.identity === 'Admin'
															? 'bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200'
															: group.identity === 'Member'
															? 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200'
															: 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'}"
													>
														{group.identity}
													</span>
												</div>

												{#if selectedGroupId === group.id}
													<div class="ml-2 pl-2 pr-2 md:pr-0 shrink-0">
														<Check />
													</div>
												{/if}
											</button>
										{:else}
											<div class="block px-3 py-2 text-sm text-gray-700 dark:text-gray-100">
												No groups found
											</div>
										{/each}
									</div>
								</DropdownMenu.Content>
							</DropdownMenu.Root>
						</div>

						<!-- Info Button -->
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
									role="region"
									aria-label="Your account information"
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
					</div>

					<!-- Tabs -->
					<div
						class="flex gap-1 scrollbar-none overflow-x-auto w-fit text-center text-sm font-medium rounded-full bg-transparent py-1 touch-auto pointer-events-auto"
					>
						<a
							class="w-[130px] text-center rounded-full p-1.5 {$page.url.pathname.includes(
								'/aitutordashboard/instructorsetup'
							)
								? 'font-semibold text-[#57068c] dark:text-white'
								: 'text-gray-600 dark:text-gray-600 hover:text-[#57068c] dark:hover:text-white'} transition"
							href={buildDashboardHref('/aitutordashboard/instructorsetup')}
							on:click|preventDefault={() => goto(buildDashboardHref('/aitutordashboard/instructorsetup'))}
						>
							Instructor Setup
						</a>

						<!-- Divider -->
						<div class="w-px h-5 self-center bg-gray-300 dark:bg-gray-600 mx-1"></div>

						{#each [
							{ path: '/aitutordashboard', label: 'Summary', exact: true },
							{ path: '/aitutordashboard/topicanalysis', label: 'Topic Analysis', exclude: '/aitutordashboard/topicanalysis/reviewquestionset' },
							{ path: '/aitutordashboard/studentanalysis', label: 'Student Analysis' },
							{ path: '/aitutordashboard/topicanalysis/reviewquestionset', label: 'Practice Question' }
						] as tab, i (tab.path)}
							{#if i === 3}
								<!-- Divider -->
								<div class="w-px h-5 self-center bg-gray-300 dark:bg-gray-600 mx-1"></div>
							{/if}
							{@const active = tab.exact
								? $page.url.pathname === tab.path || $page.url.pathname === `${tab.path}/`
								: tab.exclude
									? $page.url.pathname.includes(tab.path) && !$page.url.pathname.includes(tab.exclude)
									: $page.url.pathname.includes(tab.path)}
							<a
								class="{tab.path === '/aitutordashboard' ? 'min-w-fit' : tab.path === '/aitutordashboard/topicanalysis/reviewquestionset' ? 'w-[140px]' : 'w-[130px]'} text-center rounded-full p-1.5 {active
									? 'font-semibold text-[#57068c] dark:text-white'
									: 'text-gray-600 dark:text-gray-600 hover:text-[#57068c] dark:hover:text-white'} transition"
								href={buildDashboardHref(tab.path)}
								on:click|preventDefault={() => goto(buildDashboardHref(tab.path))}
							>
								{tab.label}
							</a>
						{/each}
					</div>
				</div>
			</div>
		</nav>

		<div class="relative pb-1 px-[18px] flex-1 max-h-full overflow-y-auto" style="scrollbar-gutter: stable" id="aitutordashboard-container">
			{#if isSwitchingGroup}
				<div class="absolute inset-0 z-50 flex items-start justify-center pt-32 bg-white/60 dark:bg-gray-900/60">
					<div class="rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-lg dark:border-gray-700 dark:bg-gray-800">
						<div class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
							<svg class="h-4 w-4 animate-spin text-[#57068C]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
							Switching group…
						</div>
					</div>
				</div>
			{/if}
			<slot />
		</div>
	</div>
{/if}
