<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import { showControls, showRightsideQuestions } from '$lib/stores';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import { Tooltip } from 'bits-ui';

	type PracticeQuestion = {
		id: string;
		sequence: number;
		homework: string;
		topics: string[];
		question: string;
		completed?: boolean;
	};

	const fallbackGroupName = 'MATH-I - InstructorName - CourseCode - Section';
	const fallbackHomeworkOptions = [
		'Homework1-MATH-Code-Section-Semester',
		'Homework2-MATH-Code-Section-Semester',
		'Homework3-MATH-Code-Section-Semester',
		'Homework4-MATH-Code-Section-Semester'
	];
	const fallbackTopicOptions = [
		'Linear Algebra',
		'Differentiation',
		'Integration by Parts',
		'Limit Definition',
		'Factoring',
		'Trigonometric Identities'
	];

	const fallbackQuestions: PracticeQuestion[] = [
		{
			id: 'hq-1',
			sequence: 1,
			homework: 'Homework1-MATH-Code-Section-Semester',
			topics: ['Linear Algebra', 'Differentiation'],
			question: 'Find the eigenvalues of the matrix A and explain how they relate to the transformation.',
			completed: false
		},
		{
			id: 'hq-2',
			sequence: 2,
			homework: 'Homework2-MATH-Code-Section-Semester',
			topics: ['Integration by Parts'],
			question: 'Compute the integral of x cos(x) dx and justify why integration by parts is the right method.',
			completed: true
		},
		{
			id: 'hq-3',
			sequence: 1,
			homework: 'Homework3-MATH-Code-Section-Semester',
			topics: ['Limit Definition', 'Factoring'],
			question: 'Use the limit definition to derive the derivative of f(x)=x^2-4x, simplifying carefully at each step.',
			completed: false
		},
		{
			id: 'hq-4',
			sequence: 3,
			homework: 'Homework4-MATH-Code-Section-Semester',
			topics: ['Trigonometric Identities'],
			question: 'Prove that 1 - cos(2x) = 2sin^2(x) and explain which identity you start from.',
			completed: true
		}
	];

	let groupName = fallbackGroupName;
	let homeworkOptions = fallbackHomeworkOptions;
	let questions: PracticeQuestion[] = fallbackQuestions;

	$: practicing = $page.url.searchParams.get('practicing');
	$: practicingValue = practicing ? String(practicing) : null;
	$: assignmentId = $page.url.searchParams.get('assignment_id');
	$: initialHomework =
		practicingValue && homeworkOptions[Number(practicingValue) - 1]
			? homeworkOptions[Number(practicingValue) - 1]
			: homeworkOptions[0];

	let selectedHomework = initialHomework;
	let started = false;
	let practiceContextKey = '';
	let lastPracticeContextKey = '';
	let sendingQuestionId: string | null = null;

	export let submitPrompt: Function | null = null;
	export let chatId: string | null = null;
	export let prompt = '';

	$: practiceContextKey = `${chatId ?? ''}::${practicingValue ?? ''}::${assignmentId ?? ''}`;
	$: if (practiceContextKey !== lastPracticeContextKey) {
		lastPracticeContextKey = practiceContextKey;
		const nextContext = loadAssignmentPracticeContext();
		selectedHomework = nextContext.initialHomework;
		started = false;
	}

	function getChatBoundPracticeKey() {
		if (!chatId) return '';
		return `aiTutorPracticeAssignment-${chatId}`;
	}

	function readPracticeAssignmentRaw() {
		if (typeof localStorage === 'undefined' || typeof sessionStorage === 'undefined') return null;
		const chatBoundKey = getChatBoundPracticeKey();
		if (chatBoundKey) {
			return localStorage.getItem(chatBoundKey);
		}
		return (
			sessionStorage.getItem('aiTutorActivePracticeAssignment') ||
			localStorage.getItem('aiTutorPracticeAssignmentPending')
		);
	}

	function loadAssignmentPracticeContext() {
		if (typeof sessionStorage === 'undefined') {
			groupName = fallbackGroupName;
			homeworkOptions = fallbackHomeworkOptions;
			questions = fallbackQuestions;
			const fallbackInitialHomework = fallbackHomeworkOptions[0];
			return {
				initialHomework: fallbackInitialHomework
			};
		}

		const raw = readPracticeAssignmentRaw();
		if (!raw) {
			groupName = fallbackGroupName;
			homeworkOptions = fallbackHomeworkOptions;
			questions = fallbackQuestions;
			const fallbackInitialHomework = fallbackHomeworkOptions[0];
			return {
				initialHomework: fallbackInitialHomework
			};
		}

		try {
			const payload = JSON.parse(raw);
			if (!chatId && assignmentId && payload?.assignmentId && payload.assignmentId !== assignmentId) {
				groupName = fallbackGroupName;
				homeworkOptions = fallbackHomeworkOptions;
				questions = fallbackQuestions;
				const fallbackInitialHomework = fallbackHomeworkOptions[0];
				return {
					initialHomework: fallbackInitialHomework
				};
			}

			const assignmentQuestions = Array.isArray(payload?.assignedItems) ? payload.assignedItems : [];
			const homeworkLabel = String(payload?.homeworkLabel || fallbackHomeworkOptions[0]);

			groupName = 'Assigned Practice Questions';
			homeworkOptions = [homeworkLabel];
			questions =
				assignmentQuestions.length > 0
					? assignmentQuestions.map((item: any, index: number) => ({
							id: String(item?.id ?? `${payload?.assignmentId ?? 'assignment'}-${index + 1}`),
							sequence: index + 1,
							homework: homeworkLabel,
							topics:
								Array.isArray(item?.topics) && item.topics.length > 0
									? item.topics.map((topic: any) => String(topic))
									: ['General Practice'],
							question: String(
								item?.question ?? item?.prompt ?? item?.text ?? 'Practice question'
							),
								completed: false
							}))
						: fallbackQuestions;
			return {
				initialHomework: homeworkLabel
			};
		} catch {
			groupName = fallbackGroupName;
			homeworkOptions = fallbackHomeworkOptions;
			questions = fallbackQuestions;
			const fallbackInitialHomework = fallbackHomeworkOptions[0];
			return {
				initialHomework: fallbackInitialHomework
			};
		}
	}

	function resetFilters() {
		started = false;
		selectedHomework = initialHomework;
	}

	function startSelection() {
		started = true;
	}

	$: filteredQuestions = questions.filter((question) => {
		return question.homework === selectedHomework;
	});

	$: completedCount = filteredQuestions.filter((question) => question.completed).length;

	async function closePanel() {
		if (!window.confirm('Close homework practice questions?')) {
			return;
		}

		const params = new URLSearchParams($page.url.searchParams);
		params.delete('practicing');

		showRightsideQuestions.set(false);
		showControls.set(false);
		await goto(`${$page.url.pathname}${params.toString() ? `?${params.toString()}` : ''}`, {
			replaceState: true,
			keepFocus: true,
			noScroll: true
		});
	}

	async function pasteQuestion(question: PracticeQuestion) {
		console.log('[pasteQuestion] clicked, question:', question.question);
		// 1. Copy to clipboard with fallback
		let copied = false;
		try {
			if (navigator.clipboard && navigator.clipboard.writeText) {
				await navigator.clipboard.writeText(question.question);
				copied = true;
				console.log('[pasteQuestion] navigator.clipboard succeeded');
			}
		} catch (err) {
			console.warn('[pasteQuestion] Clipboard API failed:', err);
		}
		if (!copied) {
			try {
				const ta = document.createElement('textarea');
				ta.value = question.question;
				ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px;';
				document.body.appendChild(ta);
				ta.focus();
				ta.select();
				copied = document.execCommand('copy');
				document.body.removeChild(ta);
				console.log('[pasteQuestion] execCommand result:', copied);
			} catch (err2) {
				console.warn('[pasteQuestion] execCommand copy failed:', err2);
			}
		}
		if (copied) {
			toast.success('Question copied to clipboard');
		}

		// 2. Append to existing prompt instead of replacing
		console.log('[pasteQuestion] prompt before:', JSON.stringify(prompt));
		if (prompt && prompt.trim()) {
			prompt = prompt.trim() + '\n\n' + question.question;
		} else {
			prompt = question.question;
		}
		console.log('[pasteQuestion] prompt after:', JSON.stringify(prompt));

		// 3. Focus the chat input so user can see the change
		setTimeout(() => {
			const input = document.getElementById('chat-input');
			console.log('[pasteQuestion] chat-input element:', input);
			input?.focus();
		}, 50);
	}

	async function sendQuestion(question: PracticeQuestion) {
		if (!submitPrompt) {
			toast.error('Chat send is unavailable right now.');
			return;
		}

		try {
			sendingQuestionId = question.id;
			await submitPrompt(question.question);
		} catch (error) {
			toast.error('Failed to send question to chat.');
		} finally {
			sendingQuestionId = null;
		}
	}
</script>

<div class="flex h-full w-full flex-col overflow-hidden rounded-2xl border border-[#57068C] bg-white dark:border-[#57068C] dark:bg-gray-900">
	<div class="flex items-start justify-between gap-4 px-5 py-4 bg-[#57068C] dark:bg-[#57068C] rounded-t-2xl">
		<div>
			<h3 class="text-lg font-semibold text-white">Practice Questions</h3>
			<div class="mt-1 text-xs text-white/80">{groupName}</div>
		</div>
		<button
			on:click={closePanel}
			class="rounded p-1 transition hover:bg-white/20"
			aria-label="Close panel"
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				stroke-width="2"
				stroke="currentColor"
				class="h-3.5 w-3.5 text-white"
			>
				<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
			</svg>
		</button>
	</div>

	<div class="flex-1 overflow-y-auto px-5 py-4" style:scrollbar-gutter="stable">
		<div class="space-y-6">
				<section>
					<!-- {started ? 'text-gray-400 dark:text-gray-500' : 'text-gray-900 dark:text-gray-100'} -->
					<div class="space-y-3 text-gray-900 dark:text-gray-100">
						<div class="flex items-center justify-between gap-3 text-sm">
							<div class="relative min-w-0 flex-1">
								<div
									class="block w-full truncate bg-transparent pr-5 text-sm font-medium text-gray-700 dark:text-gray-300"
									title={selectedHomework}
								>
									{selectedHomework}
								</div>
							</div>

						</div>
					<!-- <div class="flex items-center justify-between gap-3 pt-1 text-xs">
						<div class="flex items-center gap-3">
							<button
								type="button"
								class="font-medium text-gray-400 transition hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300"
								on:click={resetFilters}
							>
								Reset
							</button>
						</div>
						<button
							type="button"
							class="text-sm font-medium {started
								? 'text-gray-400 dark:text-gray-500'
								: 'text-gray-900 hover:text-gray-700 dark:text-gray-100 dark:hover:text-gray-300'} transition"
							on:click={startSelection}
						>
							{started ? 'In Progress' : 'Start'}
						</button>
					</div> -->
				</div>
			</section>
			<!-- {started ? 'text-gray-900 dark:text-gray-100' : 'text-gray-400 dark:text-gray-500'} -->
			<div class="flex items-center text-base font-semibold text-gray-900 dark:text-gray-100">
				Questions
				{#if started}
					<div class="mx-2.5 h-5 w-px bg-gray-200 dark:bg-gray-700"></div>
					<span class="text-base font-medium text-gray-500 dark:text-gray-300">{completedCount}/{filteredQuestions.length}</span>
				{/if}
			</div>
			<section>
				<!-- {!started ? 'text-gray-400 dark:text-gray-500' : 'text-gray-900 dark:text-gray-100'} -->
				<div class="space-y-3 text-gray-900 dark:text-gray-100">
					{#each filteredQuestions as question}
						<article class="flex flex-col rounded-lg border border-gray-200 p-4 dark:border-gray-700">
							<div class="mb-1 markdown-prose-xs text-sm leading-6 text-gray-900 dark:text-gray-100">
								<Markdown
									id={`practice-question-${assignmentId ?? 'fallback'}-${question.id}`}
									content={question.question}
								/>
							</div>
							<div class="mt-auto flex min-h-[1.25rem] items-center justify-between pt-3">
								<Tooltip.Root openDelay={200}>
									<Tooltip.Trigger
										type="button"
										class="inline-flex items-center text-gray-500 transition hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
										aria-label="Copy and paste to input"
										on:click={() => pasteQuestion(question)}
										>
										<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="h-3 w-3">
											<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75" />
										</svg>
									</Tooltip.Trigger>
									<Tooltip.Content
										side="right"
										sideOffset={4}
										class="z-50 rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700 shadow-lg dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
										>
										Copy & Append to Input
									</Tooltip.Content>
								</Tooltip.Root>
								<button
									type="button"
									class="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-[#57068C]/40 px-3 py-1 text-xs font-bold text-[#57068C] transition hover:bg-purple-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-purple-700 dark:text-purple-400 dark:hover:bg-purple-900/20"
									on:click={() => sendQuestion(question)}
									disabled={sendingQuestionId === question.id}
									>
										{sendingQuestionId === question.id ? 'Sending...' : 'Start'}
									</button>
							</div>
						</article>
					{/each}

						{#if filteredQuestions.length === 0}
							<div class="py-8 text-center text-sm text-gray-500 dark:text-gray-400">
								No practice questions available for this chat.
							</div>
						{/if}
					</div>
				</section>
		</div>
	</div>
</div>
