import type { User } from '$lib/types/User'
import makeRequest, { type MakeRequestProps } from '../makeRequest'

type RegisterProps = Omit<MakeRequestProps, 'path'> & {
	password: string
	email: string
}

type RegisterResponse = {
	access_token: string
	token_type: string
	user: User
}

export default async ({ password, email, requestOptions }: RegisterProps) =>
	await makeRequest<RegisterResponse>({
		path: `/auth/register`,
		requestOptions: {
			method: 'POST',
			body: JSON.stringify({ password, email }),
			...requestOptions
		}
	})
