---
name: zustand-state-patterns
description: Encodes production Zustand conventions covering typed stores with StateCreator slices, exported selector functions, async actions with API integration, status polling patterns with cleanup, HMR persistence wrappers, and devtools/persist middleware. Use when building or refactoring client state management, implementing async workflows with progress tracking, adding authentication or multi-tenant context stores, or optimizing component re-renders via granular selectors.
---

Standardize Zustand state management structure, async actions, polling patterns, and persistence following production frontend patterns.

## When to use

- Scaffolding a new Zustand store for a domain or feature
- Implementing authentication state with session restoration and token refresh
- Building async workflows with job polling and progress tracking
- Adding optimistic UI updates before API responses resolve
- Migrating from Redux or Context API to a simpler state solution
- Setting up multi-tenant or workspace context stores
- Implementing real-time data polling (e.g., video generation status, job progress)
- Designing computed selectors for performance optimization
- Integrating devtools middleware for debugging state transitions
- Adding persistence middleware for localStorage/sessionStorage
- Preserving state across HMR during development

## Core conventions

1. **Typed store with State + Actions interface**: define a single interface that declares both state fields (primitives, arrays, objects, loading flags) and action methods (async functions, setters). Use `create<MyState>()((set, get) => ({ ... }))` with the full interface as the type parameter.

2. **StateCreator slices for complex stores**: break large stores into logical slices using `StateCreator<MyState>`. Each slice returns a partial state object; combine them via spread `{ ...authSlice(set, get), ...profileSlice(set, get) }`. This pattern is optional but useful for stores with 10+ actions.

3. **Exported selector functions**: export named selectors like `export const selectUser = (state: AuthState) => state.user;` for trivial field access and `export const selectIsAuthenticated = (state: AuthState) => state.isAuthenticated;` for computed values. Use selectors in components via `const user = useAuthStore(selectUser);` to minimize re-renders (only re-render when the selected slice changes). Add JSDoc for non-trivial selectors.

4. **Async actions with try/catch and loading flags**: all async actions set `isLoading: true` before the API call, handle errors in a catch block, and reset `isLoading: false` in finally or catch. Store error messages in `error: string | null` state. Example: `login: async (email, password) => { set({ isLoading: true }); try { ... } catch { set({ error: ... }); } finally { set({ isLoading: false }); } }`.

5. **Optimistic updates**: for actions that update UI immediately before the API responds, add the new item to the state array/object first, then call the API, and rollback or reconcile on error. Example: in chat, add user message to `messages` array optimistically before sending, then append assistant response when polling completes.

6. **Polling pattern with setInterval and cleanup**: store the interval ID in state (`pollingInterval: ReturnType<typeof setInterval> | null`), start polling in a `startPolling()` action via `setInterval(async () => { ... }, INTERVAL_MS)`, and stop polling in `stopPolling()` via `clearInterval()`. Always call `stopPolling()` on success/error/unmount. Example use cases: video generation status, async job progress, real-time data updates.

7. **HMR persistence wrapper**: for stores that should survive hot module replacement during development, wrap the StateCreator with a custom `persistHMR(name, config)` middleware that saves state to `import.meta.hot.data` on dispose and restores it on reload. This is dev-only and does not affect production builds.

8. **persist middleware for localStorage/sessionStorage**: use `persist((set, get) => ({ ... }), { name: 'storage-key', partialize: (state) => ({ field1: state.field1, ... }) })` to persist only selected fields to storage. Use `sessionStorage` for session-scoped data (auth tokens) and `localStorage` for user preferences. The `partialize` function controls which fields are persisted (omit sensitive data, transient UI state, or large objects).

9. **devtools middleware for debugging**: wrap the store with `devtools((set, get) => ({ ... }), { name: 'MyStore' })` to enable Redux DevTools integration. Use for complex stores with many actions or when debugging state transitions is needed.

10. **Immutable nested updates via spread**: always use spread operators to update nested objects/arrays immutably. Example: `set((state) => ({ items: [...state.items, newItem] }))` or `set((state) => ({ user: { ...state.user, name: newName } }))`. Never mutate state directly (`state.items.push(newItem)` is forbidden).

11. **Action naming conventions**: use imperative verbs for actions (`login`, `logout`, `loadTrends`, `approveBrief`, `setFilters`) and `select*` prefix for selectors (`selectUser`, `selectCurrentBrand`, `selectIsLoading`). Boolean flags use `is*` or `has*` prefix (`isLoading`, `isAuthenticated`, `hasUnreadMessages`).

12. **Initial state constant**: define `const initialState = { ... }` for the default state shape and reuse it in the store and in reset actions. This ensures consistent state structure and simplifies reset logic.

13. **Session restoration pattern**: for auth stores, implement a `checkAuth()` action that runs on app mount to restore the session from persisted tokens or storage. Handle network errors gracefully (don't log out on transient failures). Use `isInitializing` flag to distinguish "checking session" from "ready".

14. **Brand/tenant/workspace switching**: for multi-tenant apps, store the active tenant/brand/workspace in state and provide a `switchBrand(id)` action that calls the backend to get new scoped tokens, then updates local state. Preserve the selected brand in persisted state so it survives page reloads.

15. **Pagination state**: for paginated list stores, track `pagination: { page, page_size, total, total_pages } | null` and a `filters` object. When filters change, reset `page` to 1. Example: `setFilters(newFilters) => { set({ filters: { ...filters, ...newFilters, page: 1 } }); loadData(); }`.

## Skeleton / example

```typescript
// stores/authStore.ts
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User, Brand, UserRole } from '@/types';
import { authService } from '@/lib/auth';

interface AuthState {
  // State
  user: User | null;
  isAuthenticated: boolean;
  isInitializing: boolean;
  isLoading: boolean;
  currentBrand: Brand | null;
  availableBrands: Brand[];
  userRole: UserRole;

  // Actions
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
  switchBrand: (brandId: string) => Promise<void>;
  updateProfile: (data: { name?: string; phone?: string }) => Promise<User>;
}

const initialState = {
  user: null,
  isAuthenticated: false,
  isInitializing: true,
  isLoading: false,
  currentBrand: null,
  availableBrands: [],
  userRole: 'viewer' as UserRole,
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      ...initialState,

      login: async (email: string, password: string) => {
        set({ isLoading: true });
        try {
          await authService.login(email, password);
          const { user, brands } = await fetchUserAndBrands();
          
          // Switch to first brand to get scoped tokens
          let currentBrand: Brand | null = null;
          if (brands.length > 0 && brands[0]) {
            const response = await authService.switchBrand(brands[0].id);
            currentBrand = response.brand;
          }

          set({
            user,
            isAuthenticated: true,
            isLoading: false,
            availableBrands: brands,
            currentBrand,
            userRole: currentBrand?.role ?? 'viewer',
          });
        } catch (error) {
          set({ isLoading: false });
          throw error;
        }
      },

      logout: async () => {
        try {
          await authService.logout();
        } finally {
          set({
            user: null,
            isAuthenticated: false,
            currentBrand: null,
            availableBrands: [],
            userRole: 'viewer',
          });
        }
      },

      checkAuth: async () => {
        const token = getAccessToken();
        if (!token) {
          set({ isInitializing: false, isAuthenticated: false });
          return;
        }

        try {
          const { user, brands } = await fetchUserAndBrands();
          const { currentBrand: persisted } = get();
          
          // Use persisted brand if still valid, else first brand
          let brandToSwitch = persisted && brands.find(b => b.id === persisted.id)
            ? persisted
            : brands[0] ?? null;

          if (brandToSwitch) {
            const response = await authService.switchBrand(brandToSwitch.id);
            brandToSwitch = response.brand;
          }

          set({
            user,
            isAuthenticated: true,
            isInitializing: false,
            availableBrands: brands,
            currentBrand: brandToSwitch,
            userRole: brandToSwitch?.role ?? 'viewer',
          });
        } catch (error) {
          // Keep persisted state on network errors, clear on auth errors
          const isAuthError = error.status === 401;
          if (isAuthError) {
            set({ ...initialState, isInitializing: false });
          } else {
            set({ isInitializing: false });
          }
        }
      },

      switchBrand: async (brandId: string) => {
        const { availableBrands } = get();
        const brand = availableBrands.find(b => b.id === brandId);
        if (!brand) return;

        try {
          const response = await authService.switchBrand(brandId);
          set({
            currentBrand: response.brand,
            userRole: response.brand.role,
          });
        } catch (error) {
          console.error('Failed to switch brand:', error);
          // Fallback to local state even if API fails
          set({ currentBrand: brand, userRole: brand.role });
        }
      },

      updateProfile: async (data) => {
        const updatedUser = await authService.updateProfile(data);
        set({ user: updatedUser });
        return updatedUser;
      },
    }),
    {
      name: 'app-auth-storage',
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        currentBrand: state.currentBrand,
        availableBrands: state.availableBrands,
        userRole: state.userRole,
      }),
    }
  )
);

// Selectors
export const selectUser = (state: AuthState) => state.user;
export const selectIsAuthenticated = (state: AuthState) => state.isAuthenticated;
export const selectIsInitializing = (state: AuthState) => state.isInitializing;
export const selectCurrentBrand = (state: AuthState) => state.currentBrand;
export const selectUserRole = (state: AuthState) => state.userRole;

export default useAuthStore;
```

```typescript
// stores/videoStore.ts
import { create } from 'zustand';
import { videoService } from '@/lib/video';
import type { Video, VideoStatus } from '@/types';

interface VideoState {
  currentVideo: Video | null;
  isLoading: boolean;
  isGenerating: boolean;
  isPolling: boolean;
  error: string | null;
  pollingInterval: ReturnType<typeof setInterval> | null;

  loadVideo: (videoId: string) => Promise<void>;
  generateVideo: (briefId: string) => Promise<void>;
  startPolling: (videoId: string, onComplete?: () => void) => void;
  stopPolling: () => void;
  clearVideo: () => void;
}

const POLLING_INTERVAL = 3000;

export const useVideoStore = create<VideoState>()((set, get) => ({
  currentVideo: null,
  isLoading: false,
  isGenerating: false,
  isPolling: false,
  error: null,
  pollingInterval: null,

  loadVideo: async (videoId: string) => {
    set({ isLoading: true, error: null });
    try {
      const video = await videoService.getVideo(videoId);
      set({ currentVideo: video, isLoading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to load video',
        isLoading: false,
      });
      throw error;
    }
  },

  generateVideo: async (briefId: string) => {
    set({ isGenerating: true, error: null });
    try {
      const response = await videoService.generateVideo(briefId);
      const video: Video = {
        id: response.id,
        brief_id: briefId,
        status: 'queued',
        progress_percent: 0,
        // ... other fields
      };
      set({ currentVideo: video, isGenerating: false });
      
      // Start polling for status updates
      get().startPolling(response.id);
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to generate video',
        isGenerating: false,
      });
      throw error;
    }
  },

  startPolling: (videoId: string, onComplete?: () => void) => {
    // Stop any existing polling
    get().stopPolling();
    set({ isPolling: true });

    const interval = setInterval(async () => {
      try {
        const status = await videoService.getStatus(videoId);
        
        set((state) => ({
          currentVideo: state.currentVideo
            ? {
                ...state.currentVideo,
                status: status.status,
                progress_percent: status.progress_percent,
                video_url: status.video_url,
              }
            : null,
        }));

        // Stop polling if complete or failed
        if (status.status === 'ready' || status.status === 'failed') {
          get().stopPolling();
          if (onComplete) onComplete();
        }
      } catch {
        // Continue polling on error
      }
    }, POLLING_INTERVAL);

    set({ pollingInterval: interval });
  },

  stopPolling: () => {
    const { pollingInterval } = get();
    if (pollingInterval) {
      clearInterval(pollingInterval);
    }
    set({ isPolling: false, pollingInterval: null });
  },

  clearVideo: () => {
    get().stopPolling();
    set({ currentVideo: null, error: null });
  },
}));

export const selectCurrentVideo = (state: VideoState) => state.currentVideo;
export const selectVideoIsGenerating = (state: VideoState) => state.isGenerating;
export const selectVideoIsPolling = (state: VideoState) => state.isPolling;
export const selectVideoProgress = (state: VideoState) =>
  state.currentVideo?.progress_percent ?? 0;
```

```typescript
// HMR persistence wrapper (dev-only pattern)
import { StateCreator } from 'zustand';

const persistHMR =
  <T>(name: string, config: StateCreator<T>): StateCreator<T> =>
  (set, get, api) => {
    // @ts-ignore - Vite HMR API
    if (import.meta.hot) {
      // @ts-ignore
      const existingState = import.meta.hot.data?.[name];
      if (existingState) {
        setTimeout(() => set(existingState), 0);
      }

      // @ts-ignore
      import.meta.hot.dispose(() => {
        // @ts-ignore
        import.meta.hot.data[name] = get();
      });
    }

    return config(set, get, api);
  };

// Usage:
export const useDevStore = create<DevState>()(
  persistHMR('devStore', (set, get) => ({
    // store implementation
  }))
);
```

## Anti-patterns to avoid

1. **Mutating state directly**: always use `set()` with immutable updates via spread operators, never `state.items.push()` or `state.user.name = 'x'`.
2. **Missing error handling in async actions**: always wrap API calls in try/catch and set `error` state. Reset `isLoading` in finally block or catch.
3. **Not cleaning up polling intervals**: always call `clearInterval()` in `stopPolling()` and on unmount, or you'll leak memory and make redundant API calls.
4. **Persisting everything to storage**: use `partialize` to exclude transient UI state, error messages, loading flags, and large objects. Only persist auth tokens, user preferences, and selected filters.
5. **Over-selecting state in components**: instead of `const state = useAuthStore()` (re-renders on any state change), use `const user = useAuthStore(selectUser)` (re-renders only when user changes).
6. **Hardcoding API URLs in stores**: import service functions from `@/lib/*` that read from environment config, never hardcode `fetch('https://...')`.
7. **Not handling network errors gracefully in session restoration**: if `checkAuth()` fails due to network issues, keep the persisted session instead of logging the user out.
8. **Calling async actions multiple times without guards**: check `if (isLoading || jobId) return;` at the start of async actions to prevent duplicate concurrent calls.
9. **Storing derived state**: if a value can be computed from existing state, use a selector instead of duplicating it in state. Example: `selectHasUnreadMessages = (state) => state.messages.some(m => !m.read)`.
10. **Not typing the store**: always use `create<MyState>()` with the full interface as the type parameter to get type safety in actions and selectors.

## References

- [repo-evidence.md](references/repo-evidence.md) — genericized source snippets
- [store-structure-and-selectors.md](references/store-structure-and-selectors.md) — typed stores, StateCreator slices, exported selectors
- [async-polling-and-persistence.md](references/async-polling-and-persistence.md) — async actions, polling patterns, HMR persistence, devtools/persist middleware
- See also: [frontend-repo-architecture](../frontend-repo-architecture/SKILL.md) for overall project structure
