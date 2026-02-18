import makeRequest, { type MakeRequestProps } from '../makeRequest'

type RecoverNodeProps = Omit<MakeRequestProps, 'path'> & { id: string; snapshotId: string }

export default async ({ id, snapshotId, requestOptions }: RecoverNodeProps) =>
	await makeRequest<void>({
		path: `/nodes/${id}/recover`,
		requestOptions: {
			...requestOptions,
			method: 'POST',
			body: JSON.stringify({
				snapshot_id: snapshotId
			}),
			headers: {
				'Content-Type': 'application/json'
			}
		}
	})
