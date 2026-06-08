/** An item as returned by the API. Mirrors the backend `ItemRead` schema. */
export interface Item {
  id: number
  title: string
  description: string | null
  created_at: string
}

/** Payload for creating an item. Mirrors the backend `ItemCreate` schema. */
export interface ItemCreate {
  title: string
  description?: string | null
}
