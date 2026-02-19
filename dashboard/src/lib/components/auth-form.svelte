<script lang="ts">
	import { Button } from '$lib/components/ui/button'
	import * as Card from '$lib/components/ui/card'
	import { FieldGroup, Field, FieldLabel, FieldDescription } from '$lib/components/ui/field'
	import { Input } from '$lib/components/ui/input'
	import { cn } from '$lib/utils'
	import type { HTMLAttributes } from 'svelte/elements'
	import * as api from '$lib/api'
	import { createMutation, useQueryClient } from '@tanstack/svelte-query'
	import { goto } from '$app/navigation'
	import { toast } from 'svelte-sonner'
	import { AUTH_TOKEN_KEY } from '$lib/config/constants'
	import type { User } from '$lib/types/User'

	let {
		class: className,
		register = false,
		...restProps
	}: HTMLAttributes<HTMLDivElement> & { register?: boolean } = $props()

	const id = $props.id()
	const client = useQueryClient()
	const { mutate: loginMutate, isPending: isLoginPending } = createMutation(() => ({
		mutationFn: api.auth.login,
		onSuccess: ({ data }) => {
			localStorage.setItem(AUTH_TOKEN_KEY, data.access_token)
			client.setQueryData<User>(['users.me'], data.user)
			goto('/dashboard')
		},
		onError: (error) => {
			toast.error(error.message)
		}
	}))
	const { mutate: registerMutate, isPending: isRegisterPending } = createMutation(() => ({
		mutationFn: api.auth.register,
		onSuccess: ({ data }) => {
			localStorage.setItem(AUTH_TOKEN_KEY, data.access_token)
			client.setQueryData<User>(['users.me'], data.user)
			goto('/dashboard')
		},
		onError: (error) => {
			toast.error(error.message)
		}
	}))

	const onSubmit = (event: SubmitEvent & { currentTarget: EventTarget & HTMLFormElement }) => {
		event.preventDefault()

		const data = new FormData(event.currentTarget)
		const email = data.get('email') as string
		const password = data.get('password') as string

		if (register) {
			registerMutate({ email, password })
		} else {
			loginMutate({ email, password })
		}
	}
</script>

<div class={cn('flex flex-col gap-6', className)} {...restProps}>
	<Card.Root>
		<Card.Header class="text-center">
			<Card.Title class="text-xl">{register ? 'Create an account' : 'Welcome back'}</Card.Title>
			<Card.Description>
				{register ? 'Register with your email' : 'Login with your email'}
			</Card.Description>
		</Card.Header>
		<Card.Content>
			<form onsubmit={onSubmit}>
				<FieldGroup class="gap-4">
					<Field class="gap-2">
						<FieldLabel for="email-{id}">Email</FieldLabel>
						<Input
							id="email-{id}"
							name="email"
							type="email"
							placeholder="me@example.com"
							required
						/>
					</Field>
					<Field class="gap-2">
						<FieldLabel for="password-{id}">Password</FieldLabel>
						<Input id="password-{id}" name="password" type="password" required />
					</Field>
					<Field>
						<Button loading={isLoginPending || isRegisterPending} type="submit">
							{register ? 'Register' : 'Login'}
						</Button>
						<FieldDescription class="text-center">
							{register ? 'Already have an account?' : "Don't have an account?"}
							<a href={register ? '/auth/login' : '/auth/register'}>
								{register ? 'Login' : 'Sign up'}
							</a>
						</FieldDescription>
					</Field>
				</FieldGroup>
			</form>
		</Card.Content>
	</Card.Root>
</div>
