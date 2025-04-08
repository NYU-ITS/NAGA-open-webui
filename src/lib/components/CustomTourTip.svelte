<script>
	export let atEnd;
	export let message;
	export let onClickNext;
  </script>
  
  <div class="container">
	<p class="message">{@html message}</p>
	<button 
	  data-testid="next-button" 
	  on:click={onClickNext}
	  class="next-button"
	>
	  {atEnd ? 'Finish' : 'Next'}
	</button>
  </div>
  
  <style>
	.container {
	  padding: 12px;
	  /* border: 3px solid #8900E1; */
	  border-radius: 8px;
	  background: transparent;
	  box-shadow: 0 0 5px rgba(0, 0, 0, 0.2), 0 0 2px rgba(0, 0, 0, 0.2);
	}
	.message {
	  background: white;
	  color:#8900E1;
	  font-size: large;
	  border-radius: 8px;
	  padding: 8px;
	  margin: 0 0 16px;
	}
	.next-button {
	  background: #8900E1;
	  color: white;
	  border-radius: 8px;
	  border: none;
	  padding: 6px 12px;
	  cursor: pointer;
	}
  </style>
  