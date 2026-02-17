<script lang="ts">
	import type { Node } from '$lib/types/Node'
	import { type ColumnDef } from '@tanstack/table-core'
	import { renderComponent } from '$lib/components/ui/data-table'
	import DataTableCheckbox from '$lib/components/ui/data-table/data-table-checkbox.svelte'
	import Table from './table.svelte'
	import { Button } from '$lib/components/ui/button'
	import { createQuery } from '@tanstack/svelte-query'
	import * as api from '$lib/api'

	const nodes = createQuery(() => ({
		queryKey: ['nodes'],
		queryFn: async () => (await api.nodes.get()).data
	}))

	const nodesBackups = createQuery(() => ({
		queryKey: ['nodes-backups'],
		queryFn: async () => (await api.nodes.getBackups()).data
	}))

	export const data: Node[] = [
		{
			id: 1,
			name: 'Node 1',
			ip_address: '10.0.0.5',
			status: 'online',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 2,
			name: 'Node 2',
			ip_address: '10.0.0.6',
			status: 'offline',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 3,
			name: 'Node 3',
			ip_address: '10.0.0.7',
			status: 'online',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 4,
			name: 'Node 4',
			ip_address: '10.0.0.8',
			status: 'offline',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 5,
			name: 'Node 5',
			ip_address: '10.0.0.9',
			status: 'online',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 6,
			name: 'Node 6',
			ip_address: '10.0.0.10',
			status: 'offline',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 7,
			name: 'Node 7',
			ip_address: '10.0.0.11',
			status: 'online',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 8,
			name: 'Node 8',
			ip_address: '10.0.0.12',
			status: 'offline',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 9,
			name: 'Node 9',
			ip_address: '10.0.0.13',
			status: 'online',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 10,
			name: 'Node 10',
			ip_address: '10.0.0.14',
			status: 'offline',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 11,
			name: 'Node 11',
			ip_address: '10.0.0.15',
			status: 'online',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 12,
			name: 'Node 12',
			ip_address: '10.0.0.16',
			status: 'offline',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 13,
			name: 'Node 13',
			ip_address: '10.0.0.17',
			status: 'online',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 14,
			name: 'Node 14',
			ip_address: '10.0.0.18',
			status: 'offline',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 15,
			name: 'Node 15',
			ip_address: '10.0.0.19',
			status: 'online',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 16,
			name: 'Node 16',
			ip_address: '10.0.0.20',
			status: 'offline',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 17,
			name: 'Node 17',
			ip_address: '10.0.0.21',
			status: 'online',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 18,
			name: 'Node 18',
			ip_address: '10.0.0.22',
			status: 'offline',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 19,
			name: 'Node 19',
			ip_address: '10.0.0.23',
			status: 'online',
			created_at: 1770856916705,
			updated_at: 1770856916705
		},
		{
			id: 20,
			name: 'Node 20',
			ip_address: '10.0.0.24',
			status: 'offline',
			created_at: 1770856916705,
			updated_at: 1770856916705
		}
	]

	export const columns: ColumnDef<Node>[] = [
		{
			id: 'select',
			header: ({ table }) =>
				renderComponent(DataTableCheckbox, {
					checked: table.getIsAllPageRowsSelected(),
					indeterminate: table.getIsSomePageRowsSelected() && !table.getIsAllPageRowsSelected(),
					onCheckedChange: (value) => table.toggleAllPageRowsSelected(!!value),
					'aria-label': 'Select all'
				}),
			cell: ({ row }) =>
				renderComponent(DataTableCheckbox, {
					checked: row.getIsSelected(),
					onCheckedChange: (value) => row.toggleSelected(!!value),
					'aria-label': 'Select row'
				}),
			enableSorting: false,
			enableHiding: false
		},
		{
			id: 'name',
			accessorKey: 'name',
			header: 'Name'
		},
		{
			id: 'ip_address',
			accessorKey: 'ip_address',
			header: 'IP Address'
		},
		{
			id: 'status',
			accessorKey: 'status',
			header: 'Status'
		},
		{
			id: 'created_at',
			accessorKey: 'created_at',
			header: 'Created at',
			cell: ({ row }) => {
				const date = new Date(row.getValue('created_at') as number)
				return date.toLocaleString()
			}
		}
	]
</script>

<div class="flex flex-col gap-6 p-4">
	<div class="flex flex-col gap-4">
		<h1 class="text-2xl font-semibold">Quick actions</h1>
		<div class="flex gap-2">
			<Button>Recover all nodes</Button>
			<Button variant="outline">Add admin</Button>
		</div>
	</div>
	<div class="flex flex-col gap-4">
		<h1 class="text-2xl font-semibold">Nodes</h1>
		<Table {columns} {data} />

		{#if nodes.isPending}
			<p>Loading...</p>
		{:else if nodes.isError}
			<p>Error</p>
		{:else if nodes.isSuccess}
			{JSON.stringify(nodes.data)}
		{/if}

		{#if nodesBackups.isPending}
			<p>Loading...</p>
		{:else if nodesBackups.isError}
			<p>Error</p>
		{:else if nodesBackups.isSuccess}
			{JSON.stringify(nodesBackups.data)}
		{/if}
	</div>
</div>
