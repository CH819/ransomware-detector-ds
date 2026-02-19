export enum NodeStatus {
	HEALTHY = 'healthy',
	SUSPICIOUS = 'suspicious',
	ISOLATED = 'isolated',
	RECOVERING = 'recovering'
}

export type Node = {
	id: string
	status: NodeStatus
	backup: { infected_backup_id: string } | null
}
