import type { User } from '$lib/types/User'
import makeRequest, { type MakeRequestProps } from '../makeRequest'

type LoginProps = Omit<MakeRequestProps, 'path'> & {
	email: string
	password: string
}

type LoginResponse = {
	access_token: string
	token_type: string
	user: User
}

export default async ({ email, password, requestOptions }: LoginProps) => {
	const formData = new FormData()
	formData.append('username', email)
	formData.append('password', password)

	return await makeRequest<LoginResponse>({
		path: `/auth/login`,
		requestOptions: {
			method: 'POST',
			body: formData,
			...requestOptions
		}
	})
}
