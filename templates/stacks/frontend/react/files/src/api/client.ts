import axios from 'axios'

/**
 * Shared Axios instance. The base URL comes from `VITE_API_URL` at build time, falling back to the
 * local backend. Import this everywhere instead of calling `axios` directly so headers, base URL,
 * and (later) interceptors are configured in one place.
 */
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? 'http://localhost:8000',
  headers: { 'Content-Type': 'application/json' },
})
