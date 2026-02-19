<script lang="ts">
	import { NodeStatus, type Node } from '$lib/types/Node'
	import { type ColumnDef } from '@tanstack/table-core'
	import { renderComponent } from '$lib/components/ui/data-table'
	import DataTableCheckbox from '$lib/components/ui/data-table/data-table-checkbox.svelte'
	import { Button } from '$lib/components/ui/button'
	import { Badge } from '$lib/components/ui/badge'
	import { createMutation, createQuery } from '@tanstack/svelte-query'
	import * as api from '$lib/api'
	import Table from './table.svelte'
	import TableActions from './table-actions.svelte'
	import RecoverButton from './recover-button.svelte'
	import { toast } from 'svelte-sonner'

	const nodes = createQuery(() => ({
		queryKey: ['nodes'],
		queryFn: async () => (await api.nodes.get()).data,
		refetchInterval: 5000
	}))

	const recover = createMutation(() => ({
		mutationFn: api.nodes.recover,
		onSuccess: (_, data) => {
			toast.success(`Node ${data.id} recovered successfully`)
		},
		onError: (error, data) => {
			toast.error(`Failed to recover node ${data.id}: ${error.message}`)
		}
	}))

	const handleRecover = (nodeId: string) => {
		recover.mutate({ id: nodeId })
	}

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
			id: 'id',
			accessorKey: 'id',
			header: 'ID'
		},
		{
			id: 'status',
			accessorKey: 'status',
			header: 'Status',
			cell: ({ row }) => {
				const status = row.getValue('status') as NodeStatus
				return renderComponent(Badge, {
					label: status,
					variant: status === 'healthy' ? 'valid' : 'destructive'
				})
			}
		},
		{
			id: 'actions',
			enableHiding: false,
			cell: ({ row }) =>
				renderComponent(RecoverButton, {
					onclick: () => handleRecover(row.original.id),
					disabled: row.original.status === NodeStatus.HEALTHY
				})
		}
	]
</script>

<div class="flex flex-col gap-6 p-4">
	<div class="flex flex-col gap-4">
		<h1 class="text-2xl font-semibold">Nodes</h1>

		{#if nodes.isPending}
			<p>Loading...</p>
		{:else if nodes.isError}
			<p>Error: {nodes.error?.message}</p>
		{:else if nodes.isSuccess}
			<Table {columns} data={nodes.data} />
		{/if}
	</div>
</div>
