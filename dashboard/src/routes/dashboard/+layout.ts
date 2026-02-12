import { redirect } from '@sveltejs/kit'
import type { LayoutLoad } from './$types'
import { AUTH_TOKEN_KEY } from '$lib/config/constants'

export const load: LayoutLoad = async () => {
	const token = localStorage.getItem(AUTH_TOKEN_KEY)

	if (!token) {
		throw redirect(303, '/auth/login')
	}
}
