<script lang="ts">
    import { v4 as uuidv4 } from 'uuid';
    import { onMount, tick } from 'svelte';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';


    import { WEBUI_BASE_URL } from '$lib/constants';
	import systemPrompt from './nagaexpert_prompt.txt?raw';

    import { chatCompletion, generateOpenAIChatCompletion } from '$lib/apis/openai';

    //import './helperbot.css';

    let isOpen = false;
    let input = '';
    let messages: { role: string; content: string }[] = [];
	let system = '';
    let loading = false;
	let autoScrollEnabled = true;

	
	function scrollToBottom() {
		const chatMessagesEl = document.getElementById('chat-messages');
		if (chatMessagesEl && autoScrollEnabled) {
			chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
		}
    }
    function isDarkMode() {
        if (typeof window !== 'undefined') {
            return document.documentElement.classList.contains('dark');
        }
        return false;
    }

    async function sendMessage() {
        if (!input.trim() || loading) return;

        // Create a user message with a unique ID.
        const userMessage = { id: uuidv4(), role: 'user', content: input };
        const assistantMessage = { id: uuidv4(), role: 'assistant', content: '' };

        // Build the payload for the API request:
        // If there's a system prompt, add it as the first message (only once).
        let payloadMessages = [];
        if (systemPrompt) {
            // If a system message isn't already in the messages array, add it.
            if (!messages.some((msg) => msg.role === 'system')) {
            payloadMessages.push({ id: uuidv4(), role: 'system', content: systemPrompt });
            } else {
            // If it's already in the messages, include it.
            payloadMessages.push(...messages.filter((msg) => msg.role === 'system'));
            }
        }
        // Add the new user message.
        payloadMessages.push(userMessage);

        // For UI purposes, update the messages array to show the new user message.
        messages = [...messages, userMessage];
        input = '';
        loading = true;

        try {
            const res = await generateOpenAIChatCompletion(
            localStorage.getItem('token'),
            {
                stream: false,
                model: 'naga-expert-beta',
                messages: payloadMessages,  // Use the payload that includes the system prompt if it exists.
                params: { stream_response: false }
            },
            `${WEBUI_BASE_URL}/api`
            );

    
            const fullReply = res?.choices?.[0]?.message?.content;
            if (fullReply) {
                // Add the assistant message to the UI (as a placeholder).
                messages = [...messages, assistantMessage];

                // Simulate a streaming effect by splitting the full reply into tokens.
                const tokens = fullReply.split(''); // Splitting by character; adjust if needed.
                let currentContent = '';

                // Recursive function to simulate token-by-token update.
                async function simulateTyping() {
                    if (tokens.length === 0) {
                    // Typing finished. Final update.
                    assistantMessage.content = currentContent;
                    // Replace the last message with the final assistant message.
                    messages = [...messages.slice(0, -1), assistantMessage];
                    scrollToBottom();
                    loading = false;
                    return;
                    }
                    currentContent += tokens.shift();
                    assistantMessage.content = currentContent;
                    // Update the messages array to trigger UI refresh.
                    messages = [...messages.slice(0, -1), assistantMessage];
                    await tick();
                    scrollToBottom();
                    setTimeout(simulateTyping, 5); // Adjust delay (50ms) as needed.
                }
                simulateTyping();
            } 
            else {
                loading = false;
            }
        } catch (err) {
            console.error('Error sending message:', err);
            loading = false;
        }
    }

    onMount(() => {
        console.log('[HelperBot] mounted');
        //socket.on('chat-events', helperBotEventHandler);
		const chatMessagesEl = document.getElementById('chat-messages');
		if (chatMessagesEl) {
			// Listen for user scroll events.
			chatMessagesEl.addEventListener('scroll', () => {
			const { scrollTop, clientHeight, scrollHeight } = chatMessagesEl;
			// If the user scrolled more than 100px away from the bottom, disable auto-scroll.
			if (scrollHeight - scrollTop - clientHeight > 100) {
				autoScrollEnabled = false;
			} else {
				autoScrollEnabled = true;
			}
			});
		}
        
    });


</script>

<style>
    #helperbot-button {
        position: fixed;
        bottom: 110px;
        right: 40px;
        width: 42px;
        height: 42px;
        border-radius: 50%;
        border: none;
        cursor: pointer;
        z-index: 9999;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
		display: flex;
		align-items: center;
		justify-content: center;
    }
	#helperbot-close {
        position: fixed;
        bottom: 110px;
        right: 40px;
        width: 42px;
        height: 42px;
        border-radius: 50%;
        border: none;
        cursor: pointer;
        z-index: 9999;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
        display: flex;
        align-items: center;
        justify-content: center;
        transition: transform 0.2s;
    }

    #helperbot-chat {
        position: fixed;
        bottom: 170px;
        right: 40px;
        width: 400px;
        height: 500px;
        border-radius: 16px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
        z-index: 9998;
        display: flex;
        flex-direction: column;
		margin: 0; 
    }

	#chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
    }

    .bubble {
        display: inline-block;
        max-width: 60%;
        padding: 0.75rem 1rem;
        border-radius: 20px;
        word-wrap: break-word;
        white-space: pre-wrap;
    }
    
    .message {
        margin-bottom: 0.75rem;
    }


	.message.user {
        display: flex;
        justify-content: flex-end;
        margin-bottom: 0.75rem;
    }

    .message.assistant {
        text-align: left;
    }
 
	#chat-input {
        display: flex;
        padding: 0.75rem;
        border-top: 1px solid #ccc;
    }

    #chat-input input {
        flex: 1;
        padding: 0.5rem;
        font-size: 1rem;
        border: 1px solid #ccc;
        border-radius: 4px;
    } 


    button.send {
        margin-left: 0.5rem;
        padding: 0.5rem 1rem;
        border-radius: 4px;
        cursor: pointer;
    }
</style>

<!-- Floating Button -->
{#if !isOpen}
  <button id="helperbot-button" 
          on:click={() => (isOpen = true)} 
          aria-label="Open HelperBot"
          class="bg-[#57068c] dark:bg-gray-600 text-white dark:text-black hover:scale-105 transition duration-200"
    >
    <img src={WEBUI_BASE_URL + '/static/flower-white.png'} alt="HelperBot" class="helperbot-icon" /> 
  </button>
{:else}
  <button id="helperbot-close"  
          on:click={() => (isOpen = false)} 
          aria-label="Close HelperBot"
          class="bg-[#57068c] dark:bg-gray-600 text-white dark:text-black hover:scale-105 transition duration-200"
    >
    <svg
	xmlns="http://www.w3.org/2000/svg"
	fill="none"
	viewBox="0 0 24 24"
	stroke-width="6"
	stroke="currentColor"
	class="w-5 h-5 text-white "
    >
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  </button>
{/if}

<!-- Direct Minimal Chat UI -->
{#if isOpen}
    <div id="helperbot-chat"  class="relative text-sm md:text-base bg-white dark:bg-[#1f1f1f] dark:text-white rounded-xl shadow-2xl border border-gray-300 dark:border-gray-600"> 
		{#if loading}
		<div     
            class="absolute bottom-16 left-4 px-2 py-1 
	                bg-gradient-to-r from-purple-600 to-purple-800 
	                dark:from-gray-700 dark:to-gray-900  
	                rounded-md shadow-lg"
			role="status"
			aria-live="polite"
			>
			<p class="text-xs font-bold text-white animate-pulse">NAGA is thinking...</p>
			</div>
		{/if}
		<div id="chat-messages">
			{#each messages as message (message.id)}
			  <div class="message {message.role}">
				{#if message.role === 'assistant'}
				  <Markdown id={message.id} content={message.content} />
				{:else}
				  <div class="bubble bg-gray-200 text-black dark:bg-gray-700 dark:text-white">
					<p>{message.content}</p>
				  </div>
				{/if}
			  </div>
			{/each}
		  </div>
		<div id="chat-input">
			<input
				type="text"
				bind:value={input}
				placeholder="Ask me something..."
				on:keydown={(e) => e.key === 'Enter' && sendMessage()}
                
                class="w-full 
                        border border-gray-300 dark:border-gray-600 
                        bg-white dark:bg-gray-800 
                        text-black dark:text-white 
                        focus:outline-none 
                        focus:border-[#7b039d] dark:focus:border-purple-400 
                        transition"
			/>
			
			<button class="send border border-gray-300 dark:border-gray-600 
	                        bg-[#57068c] text-white 
	                        dark:bg-white dark:text-black" 
                    on:click={sendMessage} 
                    disabled={loading}>
                    Send
            </button>
		</div>
    </div>
{/if}

