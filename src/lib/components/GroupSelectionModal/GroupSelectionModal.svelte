<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user, settings } from '$lib/stores';
	import { getGroups, getGroupById } from '$lib/apis/groups';
	import { toast } from 'svelte-sonner';
	import { WEBUI_BASE_URL, WEBUI_API_BASE_URL  } from '$lib/constants';

	let selectedGroup = '';
	let loading = false;
	let loadingGroups = true;
	let groups = [];
	let helpText = 'Your experience has been customized by your group\'s admin, and you can switch groups anytime later under Settings > General.';

	onMount(async () => {
		// Check if user is authenticated
		if (!$user) {
			goto('/auth');
			return;
		}

		// Check if user already has a selected group for this session
		try {
			const response = await fetch(`${WEBUI_API_BASE_URL}/users/selected-group`, {
				headers: { 'Authorization': `Bearer ${localStorage.token}` }
			});
			
			if (response.ok) {
				const data = await response.json();
				if (data.selected_group_id) {
					// User already selected a group, redirect to main app
					goto('/');
					return;
				}
			}
		} catch (error) {
			console.error('Error checking existing group selection:', error);
		}

		// Load available groups from API
		try {
			loadingGroups = true;
			const groupsData = await getGroups(localStorage.token);
			groups = groupsData.map(group => ({
				value: group.id || group.name,
				label: group.name
			}));
		} catch (error) {
			console.error('Failed to load groups:', error);
			toast.error('Failed to load groups');
		} finally {
			loadingGroups = false;
		}
	});
	
	async function handleContinue() {
		if (!selectedGroup) {
			toast.error('Please select a group before continuing');
			return;
		}
		
		loading = true;
		
		try {
			// Send group selection to backend
			const response = await fetch(`${WEBUI_API_BASE_URL}/users/select-group`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'Authorization': `Bearer ${localStorage.token}`
				},
				body: JSON.stringify({ group_id: selectedGroup })
			});
			
			if (!response.ok) {
				const error = await response.json();
				throw new Error(error.detail || 'Failed to save group selection');
			}
			
			// Store in localStorage for frontend reference
			localStorage.setItem('selectedUserGroup', selectedGroup);
			
			// Update user store
			user.update(u => u ? { ...u, selectedUserGroupId: selectedGroup } : u);
			
			toast.success('Group selected successfully!');
			
			// Redirect to main chat
			await goto('/');
		} catch (error) {
			console.error('Error selecting group:', error);
			toast.error('Failed to save group selection: ' + error.message);
		} finally {
			loading = false;
		}
	}

	function handleLogout() {
		localStorage.removeItem('selectedUserGroup');
		localStorage.removeItem('token');
		window.location.replace('/auth');
	}
</script>

<div class="fixed inset-0 bg-black/85 backdrop-blur-md flex items-center justify-center z-50">
	<div class="bg-white dark:bg-gray-800 rounded-xl p-8 w-full max-w-md shadow-2xl">
		<div class="flex items-center gap-3 mb-5">
			<div class="shrink-0">
				<div class="w-10 h-10 flex items-center justify-center">
					<img 
						src={WEBUI_BASE_URL + '/static/flower-violet.png'}
						alt="Logo" 
						class="w-10 h-10"
					/>
				</div>
			</div>
			<h2 class="text-2xl font-semibold text-gray-900 dark:text-white">
				Welcome, {$user?.name || 'User Name'}!
			</h2>
		</div>
		
		<div class="mb-5">
			<label for="groupSelect" class="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">
				Select your group
			</label>
			{#if loadingGroups}
				<div class="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-500 dark:text-gray-400">
					Loading groups...
				</div>
			{:else}
				<select
					id="groupSelect"
					bind:value={selectedGroup}
					class="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-purple-600 focus:border-transparent transition-colors"
				>
					<option value="">Choose a group...</option>
					{#each groups as group}
						<option value={group.value}>{group.label}</option>
					{/each}
				</select>
			{/if}
		</div>

		<p class="text-sm text-gray-600 dark:text-gray-400 mb-6">
			{helpText}
		</p>

		<button
			on:click={handleContinue}
			disabled={loading || loadingGroups || !selectedGroup}
			class="w-full py-3 px-4 bg-white dark:bg-purple-700 text-[#57068C] dark:text-white font-medium rounded-lg border border-[#57068C] dark:border-transparent hover:bg-[#57068C] hover:text-white dark:hover:bg-purple-800 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
		>
			{loading ? 'Saving...' : 'Continue'}
		</button>

		<button
			on:click={handleLogout}
			class="w-full mt-3 text-black dark:text-gray-400 hover:text-[#57068C] dark:hover:text-gray-300 text-sm font-medium transition-colors"
		>
			Log out
		</button>
	</div>
</div>

<style>
	select {
		background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e");
		background-position: right 0.7rem center;
		background-repeat: no-repeat;
		background-size: 1.5em 1.5em;
		padding-right: 2.5rem;
		-webkit-appearance: none;
		-moz-appearance: none;
		appearance: none;
	}
</style>