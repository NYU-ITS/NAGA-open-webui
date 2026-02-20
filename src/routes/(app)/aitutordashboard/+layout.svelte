<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { WEBUI_NAME, showSidebar, user, mobile } from '$lib/stores';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { checkIfSuperAdmin } from '$lib/apis/users';
	import { getGroups } from '$lib/apis/groups';

	import MenuLines from '$lib/components/icons/MenuLines.svelte';

	const i18n = getContext('i18n');

	let loaded = false;
	let showIdentityPopover = false;
	let showGroupDropdown = false;
	let isSuperAdmin = false;
	let groups = [];
	let createdGroups = [];
	let memberGroups = [];
	let allUserGroups = []; // All groups with identity (Admin/Member)

	onMount(async () => {
		loaded = true;

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
					allUserGroups = [
						...createdGroups.map(g => ({ ...g, identity: 'Admin' })),
						...memberGroups.map(g => ({ ...g, identity: 'Member' }))
					];
				}
			} catch (error) {
				console.error('Error loading groups:', error);
			}
		}
	});

	function toggleIdentityPopover() {
		showIdentityPopover = !showIdentityPopover;
	}

	function closeIdentityPopover() {
		showIdentityPopover = false;
	}

	function toggleGroupDropdown() {
		showGroupDropdown = !showGroupDropdown;
	}

	function closeGroupDropdown() {
		showGroupDropdown = false;
	}
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
						<!-- Course Title Dropdown -->
						<div class="relative">
							<button
								on:click={toggleGroupDropdown}
								class="flex items-center gap-2 text-lg font-semibold text-gray-800 dark:text-gray-200 hover:text-gray-600 dark:hover:text-gray-400 transition"
							>
								<span>MATH-I – InstructorName – CourseCode - Section - Course Name Spring 2026</span>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2"
									stroke="currentColor"
									class="w-5 h-5"
								>
									<path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
								</svg>
							</button>

							<!-- Group Dropdown -->
							{#if showGroupDropdown}
								<div
									class="absolute left-0 mt-2 w-96 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-3"
									style="z-index: 9999;"
									on:mouseleave={closeGroupDropdown}
								>
									<h3 class="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
										Your Groups
									</h3>
									{#if allUserGroups.length > 0}
										<div class="space-y-1 max-h-64 overflow-y-auto">
											{#each allUserGroups as group}
												<div class="flex items-center justify-between py-2 px-3 bg-gray-50 dark:bg-gray-800 rounded hover:bg-gray-100 dark:hover:bg-gray-700 transition">
													<span class="text-sm text-gray-900 dark:text-gray-100 font-medium">
														{group.name}
													</span>
													<span class="px-2 py-1 text-xs font-medium rounded {group.identity === 'Admin'
														? 'bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200'
														: 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200'}">
														{group.identity}
													</span>
												</div>
											{/each}
										</div>
									{:else}
										<p class="text-sm text-gray-500 dark:text-gray-400 py-2">
											You are not a member of any groups
										</p>
									{/if}
								</div>
							{/if}
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
							class="min-w-fit rounded-full p-1.5 {$page.url.pathname === '/aitutordashboard' ||
							$page.url.pathname === '/aitutordashboard/'
								? 'text-[#57068c] dark:text-white'
								: 'text-gray-600 dark:text-gray-600 hover:text-[#57068c] dark:hover:text-white'} transition"
							href="/aitutordashboard"
						>
							Summary
						</a>

						<a
							class="min-w-fit rounded-full p-1.5 {$page.url.pathname.includes(
								'/aitutordashboard/topicanalysis'
							)
								? 'text-[#57068c] dark:text-white'
								: 'text-gray-600 dark:text-gray-600 hover:text-[#57068c] dark:hover:text-white'} transition"
							href="/aitutordashboard/topicanalysis"
						>
							Topic Analysis
						</a>

						<a
							class="min-w-fit rounded-full p-1.5 {$page.url.pathname.includes(
								'/aitutordashboard/studentanalysis'
							)
								? 'text-[#57068c] dark:text-white'
								: 'text-gray-600 dark:text-gray-600 hover:text-[#57068c] dark:hover:text-white'} transition"
							href="/aitutordashboard/studentanalysis"
						>
							Student Analysis
						</a>
					</div>
				</div>
			</div>
		</nav>

		<div class="pb-1 px-[18px] flex-1 max-h-full overflow-y-auto" id="aitutordashboard-container">
			<slot />
		</div>
	</div>
{/if}
