<script lang="ts">
	import { NodeStatus, type Node } from '$lib/types/Node'
	import { type ColumnDef } from '@tanstack/table-core'
	import { renderComponent } from '$lib/components/ui/data-table'
	import DataTableCheckbox from '$lib/components/ui/data-table/data-table-checkbox.svelte'
	import { Button } from '$lib/components/ui/button'
	import { Badge, type BadgeVariant } from '$lib/components/ui/badge'
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query'
	import * as api from '$lib/api'
	import Table from './table.svelte'
	import TableActions from './table-actions.svelte'
	import RecoverButton from './recover-button.svelte'
	import { toast } from 'svelte-sonner'

	const queryClient = useQueryClient()
	const nodes = createQuery(() => ({
		queryKey: ['nodes'],
		queryFn: async () => (await api.nodes.get()).data,
		refetchInterval: 5000
	}))

	const recover = createMutation(() => ({
		mutationFn: api.nodes.recover,
		onMutate: async ({ id }) => {
			await queryClient.cancelQueries({ queryKey: ['nodes'] })
			const previousNodes = queryClient.getQueryData<Node[]>(['nodes'])
			queryClient.setQueryData<Node[]>(['nodes'], (old = []) => {
				return old.map((node) =>
					node.id === id ? { ...node, status: NodeStatus.RECOVERING } : node
				)
			})
			return { previousNodes }
		},
		onSuccess: (_, data) => {
			toast.success(`Node ${data.id} recovered successfully`)
			queryClient.setQueryData<Node[]>(['nodes'], (old = []) => {
				return old.map((node) =>
					node.id === data.id ? { ...node, status: NodeStatus.HEALTHY } : node
				)
			})
		},
		onError: (error, data) => {
			toast.error(`Failed to recover node ${data.id}: ${error.message}`)
		}
	}))

	const handleRecover = (nodeId: string) => {
		recover.mutate({ id: nodeId })
	}

	let selectedNodes = $state<Node[]>([])

	const handleRecoverSelected = () => {
		for (const node of selectedNodes) {
			recover.mutate({ id: node.id })
		}
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
				let variant: BadgeVariant = 'default'
				switch (status) {
					case NodeStatus.HEALTHY:
						variant = 'valid'
						break
					case NodeStatus.SUSPICIOUS:
						variant = 'warning'
						break
					case NodeStatus.ISOLATED:
						variant = 'destructive'
						break
					case NodeStatus.RECOVERING:
						variant = 'secondary'
						break
					default:
						break
				}

				return renderComponent(Badge, {
					label: status,
					variant
				})
			}
		},
		{
			id: 'actions',
			enableHiding: false,
			cell: ({ row }) =>
				renderComponent(RecoverButton, {
					onclick: () => handleRecover(row.original.id),
					disabled:
						row.original.status === NodeStatus.HEALTHY ||
						row.original.status === NodeStatus.RECOVERING
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
			<Table
				{columns}
				data={nodes.data}
				bind:selectedRows={selectedNodes}
				onRecoverSelected={handleRecoverSelected}
				recoverPending={recover.isPending}
				enableRowSelection={(row) =>
					row.original.status !== NodeStatus.HEALTHY &&
					row.original.status !== NodeStatus.RECOVERING}
			/>
		{/if}
	</div>
</div>
