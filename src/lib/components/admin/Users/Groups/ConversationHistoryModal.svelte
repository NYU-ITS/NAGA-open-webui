<!-- NAME:
 1. /api/v1/chats/filter/meta => rawChatData
 2. transformChatData(rawChatData) => memberStats
 3. filteredMemberStats (apply search/model filter) => filteredGroupedChats
 4. paginatedChats (apply pagination) => displayedChats (the final item)
 5. group = paginatedChats[selectedIndex]
 6. selectedMemberForQuestions = showQuestions(group)
 7. QuestionsAskedModal member is selectedMemberForQuestions
  -->

<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { getContext, onMount } from 'svelte';
	import { user } from '$lib/stores'; // This is how you get user data

	const i18n = getContext('i18n');

	import Modal from '$lib/components/common/Modal.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Cross from '$lib/components/icons/Cross.svelte';
	import Eye from '$lib/components/icons/Eye.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import QuestionsAskedModal from './QuestionsAskedModal.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';

	export let show = false;
	export let users = [];
	export let group = null;

	// Simplified API function for debugging
	const fetchGroupChatData = async (groupId) => {
		try {
			// Minimal filter to test what data exists
			const filterData = {
				group_id: groupId,
				skip: 0,
				limit: 0
			};

			const response = await fetch('/api/v1/chats/filter/meta', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${localStorage.token}`
				},
				body: JSON.stringify(filterData)
			});

			if (!response.ok) {
				throw new Error(`HTTP error! status: ${response.status}`);
			}

			const rawChatData = await response.json();

			return rawChatData;
		} catch (error) {
			console.error('💥 Error:', error);
			throw error;
		}
	};

	$: groupedChats = (() => {
		const map = new Map();
		for (const chat of filteredMemberStats) {
			const key = chat.name + '||' + chat.model;
			if (!map.has(key)) {
				map.set(key, {
					name: chat.name,
					model: chat.model,
					email: chat.email,
					ids: [],
					messageCount: 0,
					questionsCount: 0,
					lastUpdated: chat.lastUpdated,
					chats: []
				});
			}
			const group = map.get(key);
			group.ids.push(chat.id);
			group.messageCount += Number(chat.messageCount) || 0;

			const qCount = Array.isArray(chat.questionsCount)
				? chat.questionsCount.length
				: typeof chat.questionsCount === 'number'
					? chat.questionsCount
					: 0;
			group.questionsCount += qCount;

			if (new Date(chat.lastUpdated) > new Date(group.lastUpdated)) {
				group.lastUpdated = chat.lastUpdated;
			}
			group.chats.push(chat);
		}
		return Array.from(map.values());
	})();
	// Transform API response to match your data structure
	// Fixed transform function
	const transformChatData = (apiChats) => {
		return apiChats.map((chat, index) => {
			// Find user info from the users array
			const user = users.find((u) => u.id === chat.user_id) || {
				name: `User ${chat.user_id}`,
				email: `user${chat.user_id}@example.com`
			};

			// Extract questions properly from meta
			const questionsArray = chat.meta?.questions_asked || [];
			const questionsCount = Array.isArray(questionsArray) ? questionsArray.length : 0;
			return {
				id: String(chat.id),
				user_id: chat.user_id, // ← ADDED THIS LINE
				chatName: chat.title || `Chat ${index + 1}`,
				name: user.name || `User ${chat.user_id}`,
				email: user.email || `user${chat.user_id}@example.com`,
				model: chat.meta?.model_name || chat.meta?.base_model_name || 'Unknown',
				messageCount: chat.meta?.num_of_messages || 0,
				questionsCount: questionsCount, // This should be a number (count)
				questions: questionsArray, // This should be the array of question texts + timestamps
				createdAt: new Date(chat.created_at * 1000).toLocaleDateString(),
				lastUpdated: new Date(chat.updated_at * 1000).toLocaleDateString(),
				timeTaken: formatTimeTaken(chat.meta?.total_time_taken)
			};
		});
	};

	// Helper function to format time taken
	const formatTimeTaken = (timeInSeconds) => {
		if (!timeInSeconds) return '0min';
		const minutes = Math.floor(timeInSeconds / 60);
		return `${minutes}min`;
	};

	let loading = false;
	let memberStats = [];
	let selectedMembers = new Set();
	let selectAll = false;
	let actionDropdownOpen = false;
	let modelDropdownOpen = false;
	let availableModels = [];

	// Search functionality for Members
	let isSearching = false;
	let searchQuery = '';
	let searchInputRef;

	// Add chat search functionality
	let isChatSearching = false;
	let chatSearchQuery = '';
	let chatSearchInputRef;

	// Model filtering
	let filteredModel = null; // null means show all, string means show only this model

	let actionDropdownRef;
	let modelDropdownRef;
	/** Header "select all" checkbox: `indeterminate` must be set on the DOM in many browsers */
	let selectAllHeaderRef = null;

	// Sample math questions for placeholders
	const sampleQuestions = [
		'What is 2 + 2?',
		'Solve for x: 3x + 5 = 14',
		'What is the area of a circle with radius 5?',
		'Factor x² - 9',
		'What is the derivative of x²?',
		'Solve: 2x + 3y = 12, x - y = 1',
		'What is sin(30°)?',
		'Find the slope of y = 3x + 2',
		'What is 15% of 200?',
		'Simplify: √(16x⁴)'
	];

	// Pagination state
	let currentPage = 1;
	const itemsPerPage = 10;

	// Calculate pagination
	$: totalItems = filteredGroupedChats.length;
	$: totalPages = Math.ceil(totalItems / itemsPerPage);
	$: startIndex = (currentPage - 1) * itemsPerPage;
	$: endIndex = startIndex + itemsPerPage;
	$: paginatedChats = filteredGroupedChats.slice(startIndex, endIndex);

	// Reset to page 1 when filters change
	$: if (searchQuery || chatSearchQuery || filteredModel) {
		currentPage = 1;
	}

	// Pagination functions
	const goToPage = (page) => {
		if (page >= 1 && page <= totalPages) {
			currentPage = page;
		}
	};

	const nextPage = () => {
		if (currentPage < totalPages) {
			currentPage++;
		}
	};

	const prevPage = () => {
		if (currentPage > 1) {
			currentPage--;
		}
	};

	let lastFetchedGroupId = null;

	// Fetch chats for the currently selected group; one trigger path, dedups duplicate concurrent calls.
	const fetchConversationData = async () => {
		if (!group) {
			toast.warning('No group selected');
			return;
		}
		if (loading) return;

		const targetGroupId = group.id;
		loading = true;
		try {
			const rawChatData = await fetchGroupChatData(targetGroupId);
			if (group?.id !== targetGroupId) {
				return; // selection changed mid-flight; ignore stale response
			}
			memberStats = transformChatData(rawChatData);
			lastFetchedGroupId = targetGroupId;
		} catch (error) {
			console.error('Failed to fetch chat data:', error);
			toast.error('Failed to fetch conversation data.');
		} finally {
			loading = false;
		}
	};
	// Filtered member stats based on search and model filter
	$: filteredMemberStats = memberStats.filter((chat) => {
		// Apply member search filter
		const matchesSearch =
			!searchQuery || chat.name.toLowerCase().includes(searchQuery.toLowerCase());

		// Apply model filter
		const matchesModel = !filteredModel || chat.model === filteredModel;

		return matchesSearch && matchesModel;
	});

	$: filteredGroupedChats = (() => {
		const map = new Map();
		for (const chat of filteredMemberStats) {
			const key = chat.name + '||' + chat.model;
			if (!map.has(key)) {
				map.set(key, {
					name: chat.name,
					model: chat.model,
					email: chat.email,
					ids: [],
					messageCount: 0,
					questionsCount: 0, // This will be the total count
					questions: [], // This will be all questions combined
					lastUpdated: chat.lastUpdated,
					chats: []
				});
			}
			const group = map.get(key);

			// Add chat ID
			group.ids.push(chat.id);

			// Add message count
			group.messageCount += Number(chat.messageCount) || 0;

			// Add questions count (questionsCount should be a number)
			const chatQuestionsCount =
				typeof chat.questionsCount === 'number'
					? chat.questionsCount
					: Array.isArray(chat.questionsCount)
						? chat.questionsCount.length
						: 0;
			group.questionsCount += chatQuestionsCount;

			// Combine all questions from all chats (convert to [text, timestamp])
			if (Array.isArray(chat.questions)) {
				const ts = chat.createdAt && typeof chat.createdAt === 'string' ? chat.createdAt : '';
				//To correct the timestamp, now we use chat.createdAt which is in readable format
				//We will change it into the timestamp from /api/v1/chats/filter/meta later
				group.questions.push(...chat.questions.map((q) => [q, ts]));
			}

			// Update last updated time
			if (new Date(chat.lastUpdated) > new Date(group.lastUpdated)) {
				group.lastUpdated = chat.lastUpdated;
			}

			// Store the original chat for reference
			group.chats.push(chat);
		}
		return Array.from(map.values());
	})();

	// Update handleMemberSelect to work with grouped chats
	const handleMemberSelect = (groupIds) => {
		// Handle both single ID and array of IDs
		const ids = Array.isArray(groupIds) ? groupIds : [groupIds];
		if (ids.length === 0) return;

		// Check if all IDs in this group are currently selected
		const allSelected = ids.every((id) => selectedMembers.has(id));

		if (allSelected) {
			// Remove all IDs from selection
			ids.forEach((id) => selectedMembers.delete(id));
		} else {
			// Add all IDs to selection
			ids.forEach((id) => selectedMembers.add(id));
		}

		selectedMembers = selectedMembers; // Trigger reactivity
		updateSelectAllState();
	};

	// Fixed handleSelectAll function
	const handleSelectAll = () => {
		if (selectAll || isPartialSelection) {
			// Unselect all (across all pages)
			selectedMembers = new Set();
		} else {
			// Select all (across all pages)
			selectedMembers = new Set();
			filteredGroupedChats.forEach((group) => {
				group.ids.forEach((id) => selectedMembers.add(id));
			});
		}
		selectedMembers = selectedMembers;
		updateSelectAllState();
	};

	// Add partial selection state
	let isPartialSelection = false;

	function formatDate(dateString) {
		const date = new Date(dateString);
		return date.toLocaleDateString('en-US', {
			month: 'short',
			day: 'numeric',
			year: 'numeric'
		});
	}

	// Update selection functions to work with all items (not just current page)
	const updateSelectAllState = () => {
		const allGroupIds = filteredGroupedChats.flatMap((group) => group.ids); // All filtered items
		const selectedCount = allGroupIds.filter((id) => selectedMembers.has(id)).length;

		if (selectedCount === 0) {
			selectAll = false;
			isPartialSelection = false;
		} else if (selectedCount === allGroupIds.length) {
			selectAll = true;
			isPartialSelection = false;
		} else {
			selectAll = false;
			isPartialSelection = true;
		}
	};

	// Update reactivity
	$: if (filteredGroupedChats.length > 0) {
		updateSelectAllState();
	}

	// Also update when selectedMembers changes
	$: if (selectedMembers) {
		updateSelectAllState();
	}

	$: if (selectAllHeaderRef) {
		selectAllHeaderRef.indeterminate = isPartialSelection;
	}

	$: {
		const validIds = new Set(filteredGroupedChats.flatMap((g) => g.ids));
		const hasStale = [...selectedMembers].some((id) => !validIds.has(id));
		if (hasStale) {
			selectedMembers = new Set([...selectedMembers].filter((id) => validIds.has(id)));
			updateSelectAllState();
		}
	}

	// Search functionality
	const toggleSearch = () => {
		isSearching = !isSearching;
		if (isSearching) {
			// Focus the search input after a tick
			setTimeout(() => {
				if (searchInputRef) {
					searchInputRef.focus();
				}
			}, 0);
		} else {
			// Clear search when hiding
			searchQuery = '';
		}
	};

	const handleSearchKeydown = (event) => {
		if (event.key === 'Escape') {
			toggleSearch();
		}
	};

	// Chat search functionality
	const toggleChatSearch = () => {
		isChatSearching = !isChatSearching;
		if (isChatSearching) {
			// Focus the chat search input after a tick
			setTimeout(() => {
				if (chatSearchInputRef) {
					chatSearchInputRef.focus();
				}
			}, 0);
		} else {
			// Clear chat search when hiding
			chatSearchQuery = '';
		}
	};

	const handleChatSearchKeydown = (event) => {
		if (event.key === 'Escape') {
			toggleChatSearch();
		}
	};

	// Export functionality
	const handleExportPDF = async () => {
		if (selectedMembers.size === 0) {
			toast.error('Please select at least one conversation to export as PDF');
			return;
		}

		try {
			toast.info(`Preparing PDF export for ${selectedMembers.size} conversations...`);

			const response = await fetch('/api/v1/chats/export/zip', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${localStorage.token}`
				},
				body: JSON.stringify({
					group_id: group.id,
					chat_ids: Array.from(selectedMembers) // This now contains all selected chat IDs
				})
			});

			if (!response.ok) {
				throw new Error(`Export failed: ${response.status}`);
			}

			const blob = await response.blob();
			const url = URL.createObjectURL(blob);
			const link = document.createElement('a');
			link.href = url;

			// Create filename with timestamp
			const timestamp = new Date().toISOString().split('T')[0];
			link.download = `conversations_${group.id}_${timestamp}.zip`;

			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);
			URL.revokeObjectURL(url);

			toast.success(`Successfully exported ${selectedMembers.size} conversations`);
		} catch (error) {
			toast.error(`Failed to export PDF: ${error.message}`);
		}
	};

	const handleExportCSV = async () => {
		if (!group) {
			toast.error('No group selected');
			return;
		}

		if (selectedMembers.size === 0) {
			toast.error('Please select at least one conversation to export as CSV');
			return;
		}

		try {
			toast.info(`Preparing CSV export for ${selectedMembers.size} conversations...`);

			const filterData = {
				group_id: group.id,
				chat_ids: Array.from(selectedMembers),
				skip: 0,
				limit: 0
			};

			const response = await fetch('/api/v1/chats/export/csv', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${localStorage.token}`
				},
				body: JSON.stringify(filterData)
			});

			if (!response.ok) {
				const errorData = await response.json().catch(() => ({}));
				throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
			}

			// Get the CSV content and filename
			const csvContent = await response.text();
			const contentDisposition = response.headers.get('Content-Disposition');
			const filename = contentDisposition
				? contentDisposition.split('filename=')[1]?.replace(/"/g, '')
				: `group-${group.id}-conversations-filtered.csv`;

			// Create and download the CSV file
			const blob = new Blob([csvContent], { type: 'text/csv' });
			const url = URL.createObjectURL(blob);
			const link = document.createElement('a');
			link.href = url;
			link.download = filename;

			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);
			URL.revokeObjectURL(url);

			toast.success(`Successfully exported CSV: ${filename} (${selectedMembers.size} conversations)`);
		} catch (error) {
			console.error('CSV export failed:', error);
			toast.error(`Failed to export CSV: ${error.message}`);
		}
	};

	const handleExportJSON = async () => {
		if (!group) {
			toast.error('No group selected');
			return;
		}

		if (selectedMembers.size === 0) {
			toast.error('Please select at least one conversation to export as JSON');
			return;
		}

		try {
			toast.info(`Preparing JSON export for ${selectedMembers.size} conversations...`);

			const filterData = {
				group_id: group.id,
				chat_ids: Array.from(selectedMembers),
				skip: 0,
				limit: 0
			};

			const response = await fetch('/api/v1/chats/export/json', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${localStorage.token}`
				},
				body: JSON.stringify(filterData)
			});

			if (!response.ok) {
				const errorData = await response.json().catch(() => ({}));
				throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
			}

			const text = await response.text();
			const contentDisposition = response.headers.get('Content-Disposition');
			const filename = contentDisposition
				? contentDisposition.split('filename=')[1]?.replace(/"/g, '')?.trim()
				: `group-${group.id}-conversations.json`;

			const blob = new Blob([text], { type: 'application/json' });
			const url = URL.createObjectURL(blob);
			const link = document.createElement('a');
			link.href = url;
			link.download = filename;

			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);
			URL.revokeObjectURL(url);

			toast.success(`Successfully exported JSON: ${filename} (${selectedMembers.size} conversations)`);
		} catch (error) {
			console.error('JSON export failed:', error);
			toast.error(`Failed to export JSON: ${error.message}`);
		}
	};

	// Action dropdown options
	const handleAction = (action) => {
		console.log('Action:', action, 'for', selectedMembers.size, 'members');
		actionDropdownOpen = false;
		// TODO: Implement actions
	};

	// Get unique models from member stats
	const updateAvailableModels = () => {
		availableModels = [...new Set(memberStats.map((chat) => chat.model))];
	};

	// Show only chats with a specific model
	const showOnlyModel = (model) => {
		filteredModel = model;
		modelDropdownOpen = false;
		toast.success(`Showing only ${model} chats`);
	};

	// Clear model filter
	const clearModelFilter = () => {
		filteredModel = null;
		modelDropdownOpen = false;
		toast.success('Showing all models');
	};

	// Update available models when member stats changes
	$: if (memberStats.length > 0) {
		updateAvailableModels();
	}

	// Click outside handler
	const handleClickOutside = (event) => {
		// Close action dropdown if clicked outside
		if (actionDropdownRef && !actionDropdownRef.contains(event.target)) {
			actionDropdownOpen = false;
		}

		// Close model dropdown if clicked outside
		if (modelDropdownRef && !modelDropdownRef.contains(event.target)) {
			modelDropdownOpen = false;
		}
	};

	// Single trigger: only fetch when modal opens for a group, or when the group changes while open
	$: if (show && group?.id && group.id !== lastFetchedGroupId) {
		fetchConversationData();
	}

	// Add event listener when component mounts
	onMount(() => {
		document.addEventListener('click', handleClickOutside);

		// Cleanup event listener
		return () => {
			document.removeEventListener('click', handleClickOutside);
		};
	});

	// Questions modal state
	let showQuestionsModal = false;
	let selectedMemberForQuestions = null;

	// Show questions modal
	const showQuestions = (group) => {
		// Add safety check for group structure
		if (!group.chats || !Array.isArray(group.chats)) {
			console.error('Invalid group.chats:', group);
			toast.error('Unable to load questions - invalid data structure');
			return;
		}

		// Create a combined member object with all questions from all chats in the group
		const combinedMember = {
			name: group.name,
			model: group.model,
			email: group.email,
			questionsCount: group.questionsCount, // This is now the correct total count
			questions: group.chats.flatMap((chat) => chat.questions), // This is now the combined array of all questions
			chatCount: group.chats.length,
			chatNames: group.chats.map((chat) => chat.chatName || 'Unnamed Chat'),
			totalMessageCount: group.messageCount
		};

		selectedMemberForQuestions = combinedMember;
		showQuestionsModal = true;
	};

	// Column resizing state
	let isResizing = false;
	let resizingColumn = null;
	let startX = 0;
	let startWidth = 0;

	// Default column widths (in pixels)
	let columnWidths = {
		checkbox: 60,
		members: 240,
		email: 200,
		model: 240,
		messages: 140,
		questions_width: 120,
		updated: 120
	};

	// Updated column resizing functions
	const startResize = (event, columnKey) => {
		isResizing = true;
		resizingColumn = columnKey;
		startX = event.clientX;
		startWidth = columnWidths[columnKey];

		// Get the next column for two-column resizing
		const columnOrder = [
			'checkbox',
			'members',
			'email',
			'model',
			'messages',
			'questions',
			'updated'
		];
		const currentIndex = columnOrder.indexOf(columnKey);
		const nextColumnKey =
			currentIndex < columnOrder.length - 1 ? columnOrder[currentIndex + 1] : null;

		// Store next column info for resizing
		if (nextColumnKey) {
			startResize.nextColumn = nextColumnKey;
			startResize.nextColumnStartWidth = columnWidths[nextColumnKey];
		} else {
			startResize.nextColumn = null;
		}

		// Prevent text selection during resize
		document.body.style.userSelect = 'none';
		document.body.style.cursor = 'col-resize';

		// Add global mouse event listeners
		document.addEventListener('mousemove', handleResize);
		document.addEventListener('mouseup', stopResize);

		event.preventDefault();
	};

	const handleResize = (event) => {
		if (!isResizing || !resizingColumn) return;

		const deltaX = event.clientX - startX;
		const minWidth = 120; // Minimum column width

		// Calculate new width for current column
		const newCurrentWidth = Math.max(minWidth, startWidth + deltaX);
		const actualDelta = newCurrentWidth - startWidth;

		// Update current column width
		columnWidths[resizingColumn] = newCurrentWidth;

		// If there's a next column, adjust it inversely (but respect minimum width)
		if (startResize.nextColumn) {
			const newNextWidth = Math.max(minWidth, startResize.nextColumnStartWidth - actualDelta);
			columnWidths[startResize.nextColumn] = newNextWidth;
		}

		columnWidths = { ...columnWidths }; // Trigger reactivity
	};

	const stopResize = () => {
		isResizing = false;
		resizingColumn = null;

		// Clean up resize data
		startResize.nextColumn = null;
		startResize.nextColumnStartWidth = null;

		// Restore normal cursor and text selection
		document.body.style.userSelect = '';
		document.body.style.cursor = '';

		// Remove global mouse event listeners
		document.removeEventListener('mousemove', handleResize);
		document.removeEventListener('mouseup', stopResize);
	};

	// Updated keyboard resizing to work with neighboring columns
	const handleResizerKeyboard = (event, columnKey) => {
		const step = 10; // pixels to resize per key press
		const minWidth = 60;

		// Get column order for neighbor detection
		const columnOrder = [
			'checkbox',
			'members',
			'email',
			'model',
			'messages',
			'questions',
			'updated'
		];
		const currentIndex = columnOrder.indexOf(columnKey);
		const nextColumnKey =
			currentIndex < columnOrder.length - 1 ? columnOrder[currentIndex + 1] : null;

		if (event.key === 'ArrowLeft') {
			// Shrink current column, expand next column
			const newCurrentWidth = Math.max(minWidth, columnWidths[columnKey] - step);
			const actualChange = columnWidths[columnKey] - newCurrentWidth;

			columnWidths[columnKey] = newCurrentWidth;

			if (nextColumnKey && actualChange > 0) {
				columnWidths[nextColumnKey] = Math.max(
					minWidth,
					columnWidths[nextColumnKey] + actualChange
				);
			}

			columnWidths = { ...columnWidths };
			event.preventDefault();
		} else if (event.key === 'ArrowRight') {
			// Expand current column, shrink next column
			if (nextColumnKey) {
				const maxExpansion = columnWidths[nextColumnKey] - minWidth;
				const actualStep = Math.min(step, maxExpansion);

				if (actualStep > 0) {
					columnWidths[columnKey] += actualStep;
					columnWidths[nextColumnKey] -= actualStep;
					columnWidths = { ...columnWidths };
				}
			} else {
				// Last column, just expand
				columnWidths[columnKey] += step;
				columnWidths = { ...columnWidths };
			}
			event.preventDefault();
		} else if (event.key === 'Enter' || event.key === ' ') {
			// Reset to default widths
			const defaults = {
				checkbox: 60,
				members: 160,
				email: 200,
				model: 180,
				messages: 140,
				questions: 120,
				updated: 120
			};
			columnWidths[columnKey] = defaults[columnKey];
			if (nextColumnKey) {
				columnWidths[nextColumnKey] = defaults[nextColumnKey];
			}
			columnWidths = { ...columnWidths };
			event.preventDefault();
		}
	};

	// Cleanup on component destroy
	onMount(() => {
		// ... existing onMount code ...

		return () => {
			// ... existing cleanup ...
			document.removeEventListener('mousemove', handleResize);
			document.removeEventListener('mouseup', stopResize);
		};
	});

	// ... rest of existing code ...
</script>

<Modal size="6xl" bind:show>
	<!-- Table section with resizable columns -->
	<div class="flex-1 px-5 flex flex-col min-h-0">
		<!-- Header -->
		<div class="flex justify-between items-center dark:text-gray-100 px-5 pt-4 mb-4 flex-shrink-0">
			<!-- Replace the current export button section with this -->
			<div class="flex items-center gap-4">
				<div class="flex flex-col">
					<div class="text-lg font-medium font-primary">
						{group?.name || 'Group'}
					</div>
					<div class="text-sm text-gray-650 dark:text-gray-400">Conversation History</div>
				</div>

				<!-- Export: PDF, CSV, JSON -->
				<div class="flex items-center gap-3">
					<button
						class="text-xs text-gray-650 dark:text-gray-400 uppercase tracking-wider hover:text-gray-700 dark:hover:text-gray-200 flex items-center gap-2 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
						on:click={handleExportPDF}
						disabled={selectedMembers.size === 0}
						class:opacity-50={selectedMembers.size === 0}
						class:cursor-not-allowed={selectedMembers.size === 0}
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
							/>
						</svg>
						<span class="font-bold">Export as PDF</span>
					</button>

					<button
						class="text-xs text-gray-650 dark:text-gray-400 uppercase tracking-wider hover:text-gray-700 dark:hover:text-gray-200 flex items-center gap-2 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
						on:click={handleExportCSV}
						disabled={selectedMembers.size === 0}
						class:opacity-50={selectedMembers.size === 0}
						class:cursor-not-allowed={selectedMembers.size === 0}
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
							/>
						</svg>
						<span class="font-bold">Export as CSV</span>
					</button>

					<button
						class="text-xs text-gray-650 dark:text-gray-400 uppercase tracking-wider hover:text-gray-700 dark:hover:text-gray-200 flex items-center gap-2 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
						on:click={handleExportJSON}
						disabled={selectedMembers.size === 0}
						class:opacity-50={selectedMembers.size === 0}
						class:cursor-not-allowed={selectedMembers.size === 0}
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M8 9h8M8 13h4m-6 8h8a2 2 0 002-2V5a2 2 0 00-2-2h-2.343a2 2 0 01-1.414-.586l-1.657-1.657A2 2 0 0010.343 0H6a2 2 0 00-2 2v16a2 2 0 002 2z"
							/>
						</svg>
						<span class="font-bold">Export as JSON</span>
					</button>
				</div>
			</div>
			<button
				class="self-start"
				on:click={() => {
					show = false;
				}}
			>
				<Cross className="size-4.5 text-gray-800 dark:text-gray-400" />
			</button>
		</div>

		<!-- Table container with horizontal scroll -->
		<div class="flex-1 overflow-hidden">
			<div class="h-full table-container">
				<table class="resizable-table divide-y divide-gray-200 dark:divide-gray-700">
					<!-- Resizable table header -->
					<thead class="bg-gray-50 dark:bg-gray-800 sticky top-0 z-20">
						<tr>
							<!-- Checkbox column -->
							<th
								scope="col"
								class="px-4 py-3 text-left relative"
								style="width: {columnWidths.checkbox}px; min-width: {columnWidths.checkbox}px; max-width: {columnWidths.checkbox}px;"
							>
								<div class="flex items-center gap-2">
									<input
										bind:this={selectAllHeaderRef}
										type="checkbox"
										checked={selectAll || isPartialSelection}
										on:change={handleSelectAll}
										class="rounded border-gray-300 accent-[#8900e1] text-[#8900e1] focus:ring-2 focus:ring-[#8900e1]/45 focus:ring-offset-0 dark:accent-[#8900e1] dark:text-[#8900e1] dark:focus:ring-[#8900e1]/50"
										title={isPartialSelection
											? `${Array.from(selectedMembers).length} of ${filteredGroupedChats.flatMap((g) => g.ids).length} conversations selected (click to unselect all)`
											: selectAll
												? 'All conversations selected (click to unselect all)'
												: 'No conversations selected (click to select all)'}
									/>
								</div>
							</th>

							<!-- Members column -->
							<th
								scope="col"
								class="px-4 py-3 text-left relative"
								style="width: {columnWidths.members}px; min-width: {columnWidths.members}px; max-width: {columnWidths.members}px;"
							>
								<div class="overflow-hidden">
									<div class="flex items-center gap-2 w-full">
										{#if isSearching}
											<input
												bind:this={searchInputRef}
												bind:value={searchQuery}
												on:keydown={handleSearchKeydown}
												placeholder="Search..."
												class="text-xs font-medium bg-transparent border-none outline-none text-gray-900 dark:text-gray-100 placeholder-gray-400 flex-1 min-w-0"
											/>
											<button
												class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 flex-shrink-0"
												on:click={toggleSearch}
												aria-label="Close search"
											>
												<Cross className="w-3 h-3" />
											</button>
										{:else}
											<button
												class="flex items-center gap-2 text-xs font-medium text-gray-650 dark:text-gray-400 uppercase tracking-wider hover:text-gray-700 dark:hover:text-gray-200 w-full justify-start min-w-0"
												on:click={toggleSearch}
											>
												<span class="truncate">Members</span>
												<Search className="size-3.5 flex-shrink-0" />
											</button>
										{/if}
									</div>
								</div>
								<!-- Column resizer -->
								<button
									type="button"
									class="column-resizer"
									class:resizing={isResizing && resizingColumn === 'members'}
									on:mousedown={(e) => startResize(e, 'members')}
									on:keydown={(e) => handleResizerKeyboard(e, 'members')}
									aria-label="Resize members column"
									title="Drag to resize members column, or use arrow keys"
								></button>
							</th>

							<!-- Email column -->
							<th
								scope="col"
								class="px-4 py-3 text-left text-xs font-medium text-gray-650 dark:text-gray-400 uppercase tracking-wider relative"
								style="width: {columnWidths.email}px; min-width: {columnWidths.email}px; max-width: {columnWidths.email}px;"
							>
								<span class="truncate block">Email</span>
								<!-- Column resizer -->
								<button
									type="button"
									class="column-resizer"
									class:resizing={isResizing && resizingColumn === 'email'}
									on:mousedown={(e) => startResize(e, 'email')}
									on:keydown={(e) => handleResizerKeyboard(e, 'email')}
									aria-label="Resize email column"
									title="Drag to resize email column, or use arrow keys"
								></button>
							</th>

							<!-- Model column -->
							<th
								scope="col"
								class="px-4 py-3 text-left relative"
								style="width: {columnWidths.model}px; min-width: {columnWidths.model}px; max-width: {columnWidths.model}px;"
							>
								<div class="overflow-hidden">
									<div class="flex items-center gap-2 w-full">
										<div class="flex items-center gap-2 min-w-0 flex-1">
											<span
												class="text-xs font-medium text-gray-650 dark:text-gray-400 uppercase tracking-wider"
											>
												Model
											</span>
											{#if filteredModel}
												<span
													class="inline-flex items-center px-2.5 py-0 rounded-full text-xs font-medium bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-100 truncate"
												>
													{filteredModel}
												</span>
											{/if}
										</div>
										<!-- Enhanced model dropdown container -->
										<div
											class="relative flex-shrink-0 model-dropdown"
											bind:this={modelDropdownRef}
											style="z-index: 40; position: relative;"
										>
											{#if filteredModel}
												<button
													class="model-dropdown-button text-xs font-medium text-gray-650 dark:text-gray-400 uppercase tracking-wider hover:text-gray-700 dark:hover:text-gray-200 flex items-center gap-1"
													on:click|stopPropagation={clearModelFilter}
													title="Clear {filteredModel} filter"
												>
													<Cross className="size-3.5" />
												</button>
											{:else}
												<button
													class="model-dropdown-button text-xs font-medium text-gray-650 dark:text-gray-400 uppercase tracking-wider hover:text-gray-700 dark:hover:text-gray-200 flex items-center gap-1"
													on:click|stopPropagation={(e) => {
														e.preventDefault();
														e.stopPropagation();
														modelDropdownOpen = !modelDropdownOpen;
														actionDropdownOpen = false;
													}}
													title="Filter by model"
												>
													<ChevronDown className="size-3.5" />
												</button>
											{/if}

											{#if modelDropdownOpen && !filteredModel}
												<div
													class="fixed bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg max-h-72 overflow-y-auto"
													style="z-index: 1000; min-width: 200px; 
                   left: {modelDropdownRef?.getBoundingClientRect()?.left}px; 
                   top: {modelDropdownRef?.getBoundingClientRect()?.bottom + 4}px;"
												>
													{#each availableModels as model}
														<button
															class="block w-full text-left px-3 py-2 text-xs hover:bg-gray-100 dark:hover:bg-gray-700 border-b border-gray-100 dark:border-gray-600 last:border-b-0"
															on:click={() => showOnlyModel(model)}
															role="menuitem"
															aria-label="Show only {model} conversations ({memberStats.filter(
																(m) => m.model === model
															).length} conversations)"
															title="Filter to show only {model} conversations"
														>
															<div class="font-medium flex items-center gap-1">
																<span class="text-gray-400 text-[10px]">Show</span>
																<span
																	class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-100"
																>
																	{model}
																</span>
																<span class="text-gray-400 text-[10px]">
																	({filteredGroupedChats.filter((g) => g.model === model).length})
																</span>
															</div>
														</button>
													{/each}
												</div>
											{/if}
										</div>
									</div>
								</div>
								<!-- Column resizer -->
								<button
									type="button"
									class="column-resizer"
									class:resizing={isResizing && resizingColumn === 'model'}
									on:mousedown={(e) => startResize(e, 'model')}
									on:keydown={(e) => handleResizerKeyboard(e, 'model')}
									aria-label="Resize model column"
									title="Drag to resize model column, or use arrow keys"
								></button>
							</th>

							<!-- Messages column -->
							<th
								scope="col"
								class="px-4 py-3 text-left text-xs font-medium text-gray-650 dark:text-gray-400 uppercase tracking-wider relative"
								style="width: {columnWidths.messages}px; min-width: {columnWidths.messages}px; max-width: {columnWidths.messages}px;"
							>
								<span class="truncate block">Messages</span>
								<!-- Column resizer -->
								<button
									type="button"
									class="column-resizer"
									class:resizing={isResizing && resizingColumn === 'messages'}
									on:mousedown={(e) => startResize(e, 'messages')}
									on:keydown={(e) => handleResizerKeyboard(e, 'messages')}
									aria-label="Resize messages column"
									title="Drag to resize messages column, or use arrow keys"
								></button>
							</th>

							<!-- Questions column -->
							<th
								scope="col"
								class="px-4 py-3 text-left text-xs font-medium text-gray-650 dark:text-gray-400 uppercase tracking-wider relative"
								style="width: {columnWidths.questions_width}px; min-width: {columnWidths.questions_width}px; max-width: {columnWidths.questions_width}px;"
							>
								<span class="truncate block">Questions</span>
								<!-- Column resizer -->
								<button
									type="button"
									class="column-resizer"
									class:resizing={isResizing && resizingColumn === 'questions'}
									on:mousedown={(e) => startResize(e, 'questions')}
									on:keydown={(e) => handleResizerKeyboard(e, 'questions')}
									aria-label="Resize questions column"
									title="Drag to resize questions column, or use arrow keys"
								></button>
							</th>

							<!-- Updated column (no resizer on last column) -->
							<th
								scope="col"
								class="px-4 py-3 text-left text-xs font-medium text-gray-650 dark:text-gray-400 uppercase tracking-wider relative"
								style="width: {columnWidths.updated}px; min-width: {columnWidths.updated}px;"
							>
								<span class="truncate block">Updated</span>
							</th>
						</tr>
					</thead>

					<!-- Table body with matching column widths -->
					<tbody class="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
						{#each paginatedChats as group}
							<tr class="hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors h-16">
								<!-- Checkbox -->
								<td
									class="px-4 py-4 whitespace-nowrap"
									style="width: {columnWidths.checkbox}px; min-width: {columnWidths.checkbox}px; max-width: {columnWidths.checkbox}px;"
								>
									<input
										type="checkbox"
										checked={group.ids.every((id) => selectedMembers.has(id))}
										on:change={() => handleMemberSelect(group.ids)}
										class="rounded border-gray-300 accent-[#8900e1] text-[#8900e1] focus:ring-2 focus:ring-[#8900e1]/45 focus:ring-offset-0 dark:accent-[#8900e1] dark:text-[#8900e1] dark:focus:ring-[#8900e1]/50"
										aria-label="Select conversations for {group.name} using {group.model}"
									/>
								</td>

								<!-- Members -->
								<td
									class="px-4 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100"
									style="width: {columnWidths.members}px; min-width: {columnWidths.members}px; max-width: {columnWidths.members}px;"
								>
									<div class="truncate" title={group.name}>{group.name}</div>
								</td>

								<!-- Email -->
								<td
									class="px-4 py-4 whitespace-nowrap text-sm text-gray-650 dark:text-gray-400"
									style="width: {columnWidths.email}px; min-width: {columnWidths.email}px; max-width: {columnWidths.email}px;"
								>
									<div class="truncate" title={group.email}>{group.email}</div>
								</td>

								<!-- Model -->
								<td
									class="px-4 py-4 whitespace-nowrap text-sm text-gray-650 dark:text-gray-400"
									style="width: {columnWidths.model}px; min-width: {columnWidths.model}px; max-width: {columnWidths.model}px;"
								>
									<div class="overflow-hidden">
										<span
											class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-100 truncate max-w-full"
										>
											{group.model}
										</span>
									</div>
								</td>

								<!-- Messages -->
								<td
									class="px-4 py-4 whitespace-nowrap text-sm text-gray-650 dark:text-gray-400"
									style="width: {columnWidths.messages}px; min-width: {columnWidths.messages}px; max-width: {columnWidths.messages}px;"
								>
									{group.messageCount.toLocaleString()}
								</td>

								<!-- Questions -->
								<td
									class="px-4 py-4 whitespace-nowrap text-sm text-gray-650 dark:text-gray-400"
									style="width: {columnWidths.questions_width}px; min-width: {columnWidths.questions_width}px; max-width: {columnWidths.questions_width}px;"
								>
									<div class="flex items-start px-0">
										<button
											class="flex items-center gap-2 px-0 py-1"
											on:click|stopPropagation={() => showQuestions(group)}
											aria-label="View questions asked by {group.name}"
										>
											<span class="min-w-[20px] text-center">{group.questionsCount}</span>
											<div
												class="rounded p-1 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
											>
												<Eye className="size-3.5 flex-shrink-0" />
											</div>
										</button>
									</div>
								</td>

								<!-- Updated -->
								<td
									class="px-4 py-4 whitespace-nowrap text-sm text-gray-650 dark:text-gray-400"
									style="width: {columnWidths.updated}px; min-width: {columnWidths.updated}px;"
								>
									<div class="truncate" title={formatDate(group.lastUpdated)}>
										{formatDate(group.lastUpdated)}
									</div>
								</td>
							</tr>
						{/each}

						<!-- Fill empty rows -->
						{#each Array(Math.max(0, itemsPerPage - paginatedChats.length)) as _}
							<tr class="h-16">
								<td colspan="7" class="px-4 py-4"></td>
							</tr>
						{/each}

						<!-- No data message -->
						{#if paginatedChats.length === 0}
							<tr>
								<td colspan="7" class="px-4 py-8 text-center text-gray-650 dark:text-gray-400 h-32">
									{#if searchQuery || chatSearchQuery}
										No conversations found matching search criteria
									{:else if filteredModel}
										No conversations found for {filteredModel}
									{:else}
										No conversation data available
									{/if}
								</td>
							</tr>
						{/if}
					</tbody>
				</table>
			</div>
		</div>

		<!-- Pagination section -->
		<div class="px-5 py-4 border-t border-gray-200 dark:border-gray-700 flex-shrink-0">
			<div class="flex items-center justify-between">
				<!-- Left side - Items info -->
				<!-- <div class="text-sm text-gray-600 dark:text-gray-400">
					{#if totalItems > 0}
						Showing <span class="font-medium">{startIndex + 1}</span> to
						<span class="font-medium">{Math.min(endIndex, totalItems)}</span>
						of <span class="font-medium">{totalItems}</span> conversations
					{:else}
						No conversations to display
					{/if}
				</div> -->

				<!-- Center - Page navigation -->
				<div class="flex items-center gap-3">
					<!-- Previous button -->
					<button
						class="p-2 rounded-md border border-gray-450 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-750 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
						disabled={currentPage <= 1}
						on:click={prevPage}
						aria-label="Go to previous page"
						title="Go to previous page"
					>
						<ChevronLeft className="size-4 text-gray-800 dark:text-gray-400" />
					</button>
					<!-- Page indicator -->
					<div class="flex items-center gap-2">
						<span class="text-sm font-medium text-gray-900 dark:text-gray-100">
							Page {currentPage} of {totalPages}
						</span>
					</div>

					<!-- Next button -->
					<button
						class="p-2 rounded-md border border-gray-450 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-750 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
						disabled={currentPage >= totalPages}
						on:click={nextPage}
						aria-label="Go to next page"
						title="Go to next page"
					>
						<ChevronRight className="size-4 text-gray-800 dark:text-gray-400" />
					</button>
				</div>
			</div>
		</div>
	</div>
</Modal>

<!-- Questions Asked Modal -->
<QuestionsAskedModal bind:show={showQuestionsModal} member={selectedMemberForQuestions} />

<style>
	.column-resizer {
		position: absolute;
		top: 25%;
		bottom: 25%;
		right: -1px; /*  Changed from -2px to -1px */
		width: 3px; /*  Reduced from 4px to 3px */
		height: 50%;
		cursor: col-resize;
		background: transparent;
		z-index: 5;
		border-right: 1px solid;
		border-right-color: #bdbdbd;
		transition: border-color 0.2s ease;
		outline: none;
		pointer-events: auto;
	}

	.column-resizer:hover {
		border-right: 1.2px solid;
		z-index: 15;
	}

	.column-resizer.resizing {
		border-right: 1.2px solid;
		z-index: 15;
	}

	.column-resizer:focus {
		border-right: 1.2px solid;
		z-index: 15;
	}

	.table-container {
		overflow-x: auto;
		overflow-y: visible; /*  Allow vertical overflow for dropdowns */
	}

	.resizable-table {
		table-layout: fixed;
		min-width: 100%;
	}

	/*  Ensure dropdown escapes table constraints */
	.model-dropdown {
		position: relative;
		z-index: 20;
	}

	/*  Make sure dropdown container doesn't clip */
	.table-container,
	.h-full {
		overflow-y: visible !important;
	}
</style>
