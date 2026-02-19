import makeRequest, { type MakeRequestProps } from '../makeRequest'
import type { Node } from '$lib/types/Node'

type GetNodesProps = Omit<MakeRequestProps, 'path'>

export default async ({ requestOptions }: GetNodesProps = {}) =>
	await makeRequest<Node[]>({
		path: `/nodes`,
		requestOptions
	})
