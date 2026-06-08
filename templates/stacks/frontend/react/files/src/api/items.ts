import type { Item, ItemCreate } from '../types/item'
import { apiClient } from './client'

/** Fetch all items (newest first). */
export async function listItems(): Promise<Item[]> {
  const { data } = await apiClient.get<Item[]>('/items')
  return data
}

/** Create an item and return the created record. */
export async function createItem(payload: ItemCreate): Promise<Item> {
  const { data } = await apiClient.post<Item>('/items', payload)
  return data
}

/** Delete an item by id. */
export async function deleteItem(id: number): Promise<void> {
  await apiClient.delete(`/items/${id}`)
}
