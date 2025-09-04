<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user, settings, theme } from '$lib/stores';
	import { getGroups, getGroupById } from '$lib/apis/groups';
	import { toast } from 'svelte-sonner';
	import { WEBUI_BASE_URL, WEBUI_API_BASE_URL } from '$lib/constants';

	let selectedGroup = '';
	let loading = false;
	let loadingGroups = true;
	let groups = [];
	let helpText =
		"Your experience has been customized by your group's admin, and you can switch groups anytime later under Settings > General.";

	// Reactive logo source
	$: logoSrc = `${WEBUI_BASE_URL}/static/flower-violet.png`;

	onMount(async () => {
		// Apply theme on mount
		if (typeof window !== 'undefined' && window.applyTheme) {
			window.applyTheme();
		}

		// Check if user is authenticated
		if (!$user) {
			goto('/auth');
			return;
		}

		// Load available groups from API
		try {
			loadingGroups = true;
			const groupsData = await getGroups(localStorage.token);
			groups = groupsData.map((group) => ({
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
					Authorization: `Bearer ${localStorage.token}`
				},
				body: JSON.stringify({ group_id: selectedGroup })
			});

			if (!response.ok) {
				const error = await response.json();
				throw new Error(error.detail || 'Failed to save group selection');
			}

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
		localStorage.removeItem('token');
		window.location.replace('/auth');
	}
</script>

<svelte:head>
	<title>Select Group - Welcome</title>
</svelte:head>

<!-- <div
	class="min-h-screen bg-black/85 dark:bg-black/90 backdrop-blur-md flex items-center justify-center p-4"
> -->
<!-- <main class="bg-white dark:bg-gray-800 rounded-xl p-8 w-full max-w-md shadow-2xl"> -->
<div class="min-h-screen bg-[#330662] flex items-center justify-center p-4">
	<main class="bg-white p-8 w-full max-w-md">
		<header class="flex items-center gap-3 mb-5">
			<div class="shrink-0">
				<div class="w-10 h-10 flex items-center justify-center">
					<img src={logoSrc} alt="Company logo" class="w-10 h-10" />
				</div>
			</div>
			<h1 class="text-2xl font-semibold text-gray-900">
				Welcome, {$user?.name || 'User Name'}!
			</h1>
		</header>

		<section>
			<form on:submit|preventDefault={handleContinue}>
				<div class="mb-5">
					<label for="groupSelect" class="block text-sm font-medium text-gray-700">
						Select your group
					</label>
					{#if loadingGroups}
						<div
							class="w-full px-4 py-3 border border-gray-300 rounded-lg bg-white text-gray-500"
							role="status"
							aria-live="polite"
						>
							Loading groups...
						</div>
					{:else}
						<select
							id="groupSelect"
							bind:value={selectedGroup}
							required
							aria-describedby="group-help-text"
							class="w-full px-4 py-3 border border-gray-300 rounded-lg bg-white text-gray-900"
						>
							<option value="">Choose a group...</option>
							{#each groups as group}
								<option value={group.value}>{group.label}</option>
							{/each}
						</select>
					{/if}
				</div>

				<p id="group-help-text" class="text-sm text-gray-600 mb-6">
					{helpText}
				</p>

				<button
					type="submit"
					disabled={loading || loadingGroups || !selectedGroup}
					class="w-full py-3 px-4 bg-white text-[#57068C] font-medium rounded-lg border border-[#57068C] hover:bg-[#57068C] hover:text-white focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
				>
					{loading ? 'Saving...' : 'Continue'}
				</button>
			</form>
		</section>

		<footer class="mt-3">
			<button
				type="button"
				on:click={handleLogout}
				class="w-full text-black hover:text-[#57068C] text-sm font-medium transition-colors"
			>
				Log out
			</button>
		</footer>
	</main>
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
