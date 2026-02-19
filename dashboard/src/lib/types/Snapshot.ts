export type Snapshot = {
	id: string
	name: string
	timestamp: string
	size: number
}

export type Snapshots = {
	snapshots: Snapshot[]
	infected_snapshot_id: string | null
	infected_snapshot_time: string | null
}
