<script lang="ts">
	import { greet } from './greet';

	let { guest = 'Vitest', host = 'SvelteKit' } = $props();
</script>

<h1>{greet(host)}</h1>
<p>{greet(guest)}</p>
