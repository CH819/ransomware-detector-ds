import makeRequest, { type MakeRequestProps } from '../makeRequest'
import type { Snapshots } from '$lib/types/Snapshot'

type GetNodeSnapshotsProps = Omit<MakeRequestProps, 'path'> & { id: string }

export default async ({ id, requestOptions }: GetNodeSnapshotsProps) =>
	await makeRequest<Snapshots>({
		path: `/nodes/${id}/snapshots`,
		requestOptions
	})
