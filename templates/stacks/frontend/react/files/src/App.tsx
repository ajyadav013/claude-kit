import { ItemsPage } from './features/items/ItemsPage'

export default function App() {
  return (
    <main
      style={{
        maxWidth: 640,
        margin: '2rem auto',
        padding: '0 1rem',
        fontFamily: 'system-ui, sans-serif',
      }}
    >
      <ItemsPage />
    </main>
  )
}
