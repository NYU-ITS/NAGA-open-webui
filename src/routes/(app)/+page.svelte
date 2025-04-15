<script lang="ts">
	import Chat from '$lib/components/chat/Chat.svelte';
	import Help from '$lib/components/layout/Help.svelte';
	// Below are the Tutorial codes
	import { onMount } from 'svelte';
	import { run, Tour, subscribe, TourTip, } from '$lib/components/tour';
  import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';


	// step1, have a Tour Object, TourTip is customizable, and run is the entry function. Tour is the scrim and manages the step.
  
  let tourActive = false;
  
  const unsubscribe = subscribe(store => {
    tourActive = store.active;
  });
  
  onMount(() => {
    console.log(`webui_base_url: ${WEBUI_BASE_URL}`);
    // Optional: Auto-start tour (remove if not needed)
    setTimeout(() => run(), 1000);
    
    return () => {
      unsubscribe();
      stop(); // Cleanup on unmount
    };
  });

  function startTour() {
    run();
  }
  
  function endTour() {
    stop();
  }

</script>


<Help />
<Chat />
<Tour {TourTip} />
