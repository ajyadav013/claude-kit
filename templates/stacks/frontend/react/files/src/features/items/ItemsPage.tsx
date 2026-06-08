import { type FormEvent, useState } from 'react'

import { useItems } from './useItems'

/**
 * The items screen: a create form plus a list. Data and side effects live in `useItems`; this
 * component owns only form state and rendering (the container/presentational split).
 */
export function ItemsPage() {
  const { items, loading, error, add } = useItems()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!title.trim()) {
      return
    }
    setSubmitting(true)
    try {
      await add({ title: title.trim(), description: description.trim() || null })
      setTitle('')
      setDescription('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section>
      <h1>Items</h1>

      <form onSubmit={handleSubmit} aria-label="Create item">
        <input
          aria-label="Title"
          placeholder="Title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <input
          aria-label="Description"
          placeholder="Description (optional)"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <button type="submit" disabled={submitting || !title.trim()}>
          Add item
        </button>
      </form>

      {loading && <p>Loading…</p>}
      {error && <p role="alert">{error}</p>}

      <ul>
        {items.map((item) => (
          <li key={item.id}>
            <strong>{item.title}</strong>
            {item.description ? ` — ${item.description}` : ''}
          </li>
        ))}
      </ul>

      {!loading && !error && items.length === 0 && <p>No items yet. Add one above.</p>}
    </section>
  )
}
