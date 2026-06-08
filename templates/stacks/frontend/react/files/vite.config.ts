import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Vite + Vitest configuration. `vitest/config` extends Vite's `defineConfig` with the `test` key.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
