import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as itemsApi from '../../api/items'
import type { Item } from '../../types/item'
import { ItemsPage } from './ItemsPage'

vi.mock('../../api/items')

const mockedApi = vi.mocked(itemsApi)

describe('ItemsPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('renders items fetched from the API', async () => {
    const items: Item[] = [
      { id: 1, title: 'Sample', description: null, created_at: '2026-01-01T00:00:00Z' },
    ]
    mockedApi.listItems.mockResolvedValue(items)

    render(<ItemsPage />)

    expect(await screen.findByText('Sample')).toBeInTheDocument()
  })

  it('shows the empty state when there are no items', async () => {
    mockedApi.listItems.mockResolvedValue([])

    render(<ItemsPage />)

    expect(await screen.findByText('No items yet. Add one above.')).toBeInTheDocument()
  })

  it('creates an item through the form', async () => {
    mockedApi.listItems.mockResolvedValue([])
    mockedApi.createItem.mockResolvedValue({
      id: 2,
      title: 'New item',
      description: null,
      created_at: '2026-01-01T00:00:00Z',
    })

    render(<ItemsPage />)
    await screen.findByText('No items yet. Add one above.')

    await userEvent.type(screen.getByLabelText('Title'), 'New item')
    await userEvent.click(screen.getByRole('button', { name: 'Add item' }))

    await waitFor(() =>
      expect(mockedApi.createItem).toHaveBeenCalledWith({
        title: 'New item',
        description: null,
      }),
    )
    expect(await screen.findByText('New item')).toBeInTheDocument()
  })
})
