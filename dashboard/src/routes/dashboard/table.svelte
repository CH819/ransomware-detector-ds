<script lang="ts" generics="TData, TValue">
	import { Button } from '$lib/components/ui/button'
	import { createSvelteTable, FlexRender } from '$lib/components/ui/data-table'
	import { Input } from '$lib/components/ui/input'
	import * as Table from '$lib/components/ui/table'
	import {
		type ColumnDef,
		type ColumnFiltersState,
		type PaginationState,
		type Row,
		type RowSelectionState,
		type SortingState,
		getCoreRowModel,
		getFilteredRowModel,
		getPaginationRowModel,
		getSortedRowModel
	} from '@tanstack/table-core'

	type DataTableProps<TData, TValue> = {
		data: TData[]
		columns: ColumnDef<TData, TValue>[]
		disableSearch?: boolean
		selectedRows?: TData[]
		enableRowSelection?: boolean | ((row: Row<TData>) => boolean)
		onRecoverSelected?: () => void
		recoverPending?: boolean
	}

	let {
		data,
		columns,
		disableSearch = false,
		selectedRows = $bindable([]),
		enableRowSelection = true,
		onRecoverSelected,
		recoverPending = false
	}: DataTableProps<TData, TValue> = $props()

	let pagination = $state<PaginationState>({ pageIndex: 0, pageSize: 10 })
	let sorting = $state<SortingState>([])
	let columnFilters = $state<ColumnFiltersState>([])
	let rowSelection = $state<RowSelectionState>({})

	const table = createSvelteTable({
		get data() {
			return data
		},
		// svelte-ignore state_referenced_locally
		columns,
		get enableRowSelection() {
			return enableRowSelection
		},
		getCoreRowModel: getCoreRowModel(),
		getPaginationRowModel: getPaginationRowModel(),
		getSortedRowModel: getSortedRowModel(),
		getFilteredRowModel: getFilteredRowModel(),
		onPaginationChange: (updater) => {
			if (typeof updater === 'function') {
				pagination = updater(pagination)
			} else {
				pagination = updater
			}
		},
		onSortingChange: (updater) => {
			if (typeof updater === 'function') {
				sorting = updater(sorting)
			} else {
				sorting = updater
			}
		},
		onColumnFiltersChange: (updater) => {
			if (typeof updater === 'function') {
				columnFilters = updater(columnFilters)
			} else {
				columnFilters = updater
			}
		},
		onRowSelectionChange: (updater) => {
			if (typeof updater === 'function') {
				rowSelection = updater(rowSelection)
			} else {
				rowSelection = updater
			}
		},
		state: {
			get pagination() {
				return pagination
			},
			get sorting() {
				return sorting
			},
			get columnFilters() {
				return columnFilters
			},
			get rowSelection() {
				return rowSelection
			}
		}
	})

	$effect(() => {
		selectedRows = table.getSelectedRowModel().rows.map((row) => row.original)
	})
</script>

<div class="flex flex-col gap-3">
	{#if !disableSearch}
		<div class="flex items-center justify-between gap-2">
			<Input
				placeholder="Filter items..."
				value={(table.getColumn('id')?.getFilterValue() as string) ?? ''}
				onchange={(e) => {
					table.getColumn('id')?.setFilterValue(e.currentTarget.value)
				}}
				oninput={(e) => {
					table.getColumn('id')?.setFilterValue(e.currentTarget.value)
				}}
				class="max-w-sm"
			/>
			{#if onRecoverSelected && selectedRows.length > 0}
				<Button
					class="h-full"
					disabled={recoverPending}
					onclick={() => {
						onRecoverSelected?.()
						table.resetRowSelection()
					}}
				>
					Recover selected ({selectedRows.length})
				</Button>
			{/if}
		</div>
	{/if}

	<div class="overflow-hidden rounded-md border">
		<Table.Root>
			<Table.Header>
				{#each table.getHeaderGroups() as headerGroup (headerGroup.id)}
					<Table.Row>
						{#each headerGroup.headers as header (header.id)}
							<Table.Head colspan={header.colSpan}>
								{#if !header.isPlaceholder}
									<FlexRender
										content={header.column.columnDef.header}
										context={header.getContext()}
									/>
								{/if}
							</Table.Head>
						{/each}
					</Table.Row>
				{/each}
			</Table.Header>
			<Table.Body>
				{#each table.getRowModel().rows as row (row.id)}
					<Table.Row data-state={row.getIsSelected() && 'selected'}>
						{#each row.getVisibleCells() as cell (cell.id)}
							<Table.Cell>
								<FlexRender content={cell.column.columnDef.cell} context={cell.getContext()} />
							</Table.Cell>
						{/each}
					</Table.Row>
				{:else}
					<Table.Row>
						<Table.Cell colspan={columns.length} class="h-24 text-center">No results.</Table.Cell>
					</Table.Row>
				{/each}
			</Table.Body>
		</Table.Root>
	</div>
	<div class="flex items-center justify-end space-x-2">
		<Button
			variant="outline"
			size="sm"
			onclick={() => table.previousPage()}
			disabled={!table.getCanPreviousPage()}
		>
			Previous
		</Button>
		<Button
			variant="outline"
			size="sm"
			onclick={() => table.nextPage()}
			disabled={!table.getCanNextPage()}
		>
			Next
		</Button>
	</div>
</div>
