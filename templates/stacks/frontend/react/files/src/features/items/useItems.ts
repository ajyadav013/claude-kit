import { useCallback, useEffect, useState } from 'react'

import { createItem, listItems } from '../../api/items'
import type { Item, ItemCreate } from '../../types/item'

export interface UseItems {
  items: Item[]
  loading: boolean
  error: string | null
  add: (payload: ItemCreate) => Promise<void>
  reload: () => Promise<void>
}

/**
 * Encapsulates item list state and data fetching. Keeping data logic in a hook keeps the page
 * component presentational and makes the behavior independently testable.
 *
 * @returns The current items, loading/error flags, and `add` / `reload` actions.
 */
export function useItems(): UseItems {
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setItems(await listItems())
    } catch {
      setError('Failed to load items')
    } finally {
      setLoading(false)
    }
  }, [])

  const add = useCallback(async (payload: ItemCreate) => {
    const created = await createItem(payload)
    setItems((previous) => [created, ...previous])
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  return { items, loading, error, add, reload }
}
