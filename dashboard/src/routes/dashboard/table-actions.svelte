<script lang="ts">
	import { Button } from '$lib/components/ui/button'
	import * as Dialog from '$lib/components/ui/dialog'
	import type { Node } from '$lib/types/Node'
	import type { Snapshot } from '$lib/types/Snapshot'
	import Table from './table.svelte'
	import { createMutation, createQuery } from '@tanstack/svelte-query'
	import * as api from '$lib/api'
	import type { ColumnDef } from '@tanstack/table-core'
	import { renderComponent } from '$lib/components/ui/data-table'
	import prettyBytes from 'pretty-bytes'
	import RecoverButton from './recover-button.svelte'

	let { node }: { node: Node } = $props()

	const snapshots = createQuery(() => ({
		queryKey: ['snapshots', node.id],
		queryFn: async () => (await api.nodes.getSnapshots({ id: node.id })).data
	}))

	let open = $state(false)

	const recoverSnapshot = createMutation(() => ({
		mutationFn: async (_snapshotId: string) => await api.nodes.recover({ id: node.id }),
		onSuccess: () => {
			open = false
		}
	}))

	const columns: ColumnDef<Snapshot>[] = [
		{
			id: 'timestamp',
			accessorKey: 'timestamp',
			header: 'Timestamp'
		},
		{
			id: 'size',
			accessorKey: 'size',
			header: 'Size',
			cell: ({ row }) => prettyBytes(row.original.size)
		},
		{
			id: 'select',
			cell: ({ row }) =>
				renderComponent(RecoverButton, {
					onclick: () => {
						recoverSnapshot.mutateAsync(row.original.id)
					}
				}),
			enableSorting: false,
			enableHiding: false
		}
	]
</script>

<Dialog.Root bind:open>
	<Dialog.Trigger>
		{#snippet child({ props })}
			<div class="flex justify-end">
				<Button {...props} variant="outline" size="sm" class="relative">Recover</Button>
			</div>
		{/snippet}
	</Dialog.Trigger>
	<Dialog.Content class="flex w-full flex-col">
		<Dialog.Header>
			<Dialog.Title>Recover snapshot</Dialog.Title>
			<Dialog.Description>
				Force client to recover from snapshot. Will delete all previous files.
			</Dialog.Description>
		</Dialog.Header>

		<div class="flex w-full flex-col gap-3">
			{#if snapshots.isPending}
				<p>Loading...</p>
			{:else if snapshots.isError}
				<p>Error: {snapshots.error?.message}</p>
			{:else if snapshots.isSuccess}
				<Button
					class="w-fit"
					onclick={() => recoverSnapshot.mutateAsync(snapshots.data.snapshots[0].id)}
				>
					Recover last healthy snapshot
				</Button>
				<Table {columns} disableSearch data={snapshots.data.snapshots} />
			{/if}
		</div>
	</Dialog.Content>
</Dialog.Root>
