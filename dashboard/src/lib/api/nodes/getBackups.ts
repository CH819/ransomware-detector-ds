import makeRequest, { type MakeRequestProps } from '../makeRequest'
import type { Node } from '$lib/types/Node'

type GetNodesBackupsProps = Omit<MakeRequestProps, 'path'>

export default async ({ requestOptions }: GetNodesBackupsProps = {}) =>
	await makeRequest<Node[]>({
		path: `/nodes/backups`,
		requestOptions
	})
