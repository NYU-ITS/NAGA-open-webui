<script>
  import { WEBUI_BASE_URL } from '$lib/constants';
  export let atEnd;
  export let message;
  export let onClickNext;
</script>

<div class="container">
  <div class="tour-icon">
    <img
      src="{WEBUI_BASE_URL}/static/blossom.svg"
      alt="Tour icon"
      class="h-full w-auto object-cover"
      crossorigin="anonymous"
    />
  </div>
  <div class="content">
    <p class="message">{@html message}</p>
    <button 
      data-testid="next-button" 
      class="next-button"
      on:click={onClickNext}
    >
      {atEnd ? 'Done': 'Next'}
    </button>
  </div>
</div>

<style>
  .container {
    position: relative;
    background: white;
    border-radius: 4px;
    cursor: pointer;
    z-index: 9999;
    width: 200px;
    transition: all 0.3s ease-out;
    padding: 12px;
    display: flex;
    gap: 4px;
  }

  .tour-icon {
    flex: 0 0 36px; /* Fixed width instead of auto */
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .tour-icon img {
    width: 36px;
    height: 36px;
    object-fit: contain; /* Better than object-cover for SVGs */
  }

  .content {
    flex: 1;
    display: flex;
    flex-direction: column;
  }

  .message {
    margin: 0;
    font-family: 'NYU', system-ui, -apple-system, sans-serif;
    font-size: 12px;
    font-weight: 600;
    color: #000000;
    line-height: 1.4;
  }

  .next-button {
    align-self: flex-end;
    font-family: 'NYU', system-ui, -apple-system, sans-serif;
    font-size: 12px;
    font-weight: 700;
    color: #9ca3af; /* gray-400 */
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    margin-top: 4px;
  }

  .container:hover,
  .container:focus {
    background: #f8f8f8;
  }
</style>