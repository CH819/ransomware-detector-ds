<script lang="ts">
	import { goto } from '$app/navigation'
	import { createQuery } from '@tanstack/svelte-query'
	import * as api from '$lib/api'
	import { AUTH_TOKEN_KEY } from '$lib/config/constants'
	import Header from '$lib/components/header.svelte'

	let { children } = $props()

	const me = createQuery(() => ({
		queryKey: ['users.me'],
		queryFn: async () => {
			try {
				return (await api.users.me()).data
			} catch (error) {
				console.log(error)
			}
		}
	}))

	$effect(() => {
		if (me.isError) {
			localStorage.removeItem(AUTH_TOKEN_KEY)
			goto('/auth/login')
		}
	})
</script>

<div class="mx-auto flex h-screen max-w-2xl flex-col">
	{#if me.isPending}
		<p>Loading...</p>
	{:else if me.isError}
		<p>Error</p>
	{:else if me.isSuccess}
		<Header />
		{@render children()}
	{/if}
</div>
