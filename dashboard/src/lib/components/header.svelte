<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query'
	import * as api from '$lib/api'
	import BiohazardIcon from '@lucide/svelte/icons/biohazard'
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu'
	import { Button } from './ui/button'
	import LogoutIcon from '@lucide/svelte/icons/log-out'
	import { goto } from '$app/navigation'
	import { AUTH_TOKEN_KEY } from '$lib/config/constants'

	const me = createQuery(() => ({
		queryKey: ['users.me'],
		queryFn: async () => (await api.users.me()).data
	}))

	const handleLogout = () => {
		localStorage.removeItem(AUTH_TOKEN_KEY)
		goto('/auth/login')
	}
</script>

<header
	class="fixed top-0 left-0 z-10 flex w-full items-center justify-center border-b border-border bg-card"
>
	<div class="mx-auto flex w-full max-w-2xl items-center justify-between px-4 py-2">
		<div class="flex items-center gap-2">
			<a href="/dashboard" class="flex items-center gap-2 self-center font-medium">
				<div
					class="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground"
				>
					<BiohazardIcon class="size-5" />
				</div>
			</a>
		</div>
		{#if me.isSuccess}
			<DropdownMenu.Root>
				<DropdownMenu.Trigger>
					<Button size="sm" variant="outline">
						{me.data.email}
					</Button>
				</DropdownMenu.Trigger>
				<DropdownMenu.Content>
					<DropdownMenu.Group>
						<DropdownMenu.Label>
							{me.data.role[0].toUpperCase() + me.data.role.slice(1)}
						</DropdownMenu.Label>
						<DropdownMenu.Separator />
						<DropdownMenu.Item onclick={handleLogout}>
							<LogoutIcon />
							Logout
						</DropdownMenu.Item>
					</DropdownMenu.Group>
				</DropdownMenu.Content>
			</DropdownMenu.Root>
		{/if}
	</div>
</header>
<div class="h-12 shrink-0"></div>
