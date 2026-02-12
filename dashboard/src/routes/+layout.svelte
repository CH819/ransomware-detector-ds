<script lang="ts">
	import '../styles/global.css'
	import favicon from '$lib/assets/favicon.svg'
	import { QueryClientProvider, QueryClient } from '@tanstack/svelte-query'
	import { Toaster } from '$lib/components/ui/sonner'

	let { children } = $props()
	const queryClient = new QueryClient({
		defaultOptions: {
			queries: {
				retry: 0
			}
		}
	})
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>
<QueryClientProvider client={queryClient}>
	<Toaster />
	{@render children()}
</QueryClientProvider>
