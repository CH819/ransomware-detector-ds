import makeRequest, { type MakeRequestProps } from '../makeRequest'

type RecoverNodeProps = Omit<MakeRequestProps, 'path'> & { id: string }

export default async ({ id, requestOptions }: RecoverNodeProps) =>
	await makeRequest<void>({
		path: `/nodes/${id}/recover`,
		requestOptions: {
			...requestOptions,
			method: 'POST',
			headers: {
				'Content-Type': 'application/json'
			}
		}
	})
