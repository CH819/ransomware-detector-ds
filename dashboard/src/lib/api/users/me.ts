import makeRequest, { type MakeRequestProps } from '../makeRequest'
import type { User } from '$lib/types/User'

type GetMeProps = Omit<MakeRequestProps, 'path'>

export default async ({ requestOptions }: GetMeProps = {}) =>
	await makeRequest<User>({
		path: `/users/me`,
		requestOptions
	})
