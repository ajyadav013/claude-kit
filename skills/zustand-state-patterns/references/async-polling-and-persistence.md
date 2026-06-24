# Async Actions, Polling, and Persistence

## Async actions with error handling

Standard pattern for async actions:

```typescript
login: async (email: string, password: string) => {
  set({ isLoading: true });
  try {
    await authService.login(email, password);
    const { user, tenants } = await fetchUserAndTenants();
    
    set({
      user,
      isAuthenticated: true,
      isLoading: false,
      availableTenants: tenants,
    });
  } catch (error) {
    set({ isLoading: false });
    throw error;
  }
},

loadReports: async (filters?: ReportFilters) => {
  const currentFilters = filters ?? get().filters;
  set({ isLoading: true, error: null, filters: currentFilters });

  try {
    const response = await reportsService.listReports(currentFilters);
    set({
      reports: response.items,
      pagination: response.pagination,
      isLoading: false,
    });
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : 'Failed to load reports';
    set({ error: errorMessage, isLoading: false });
    throw error;
  }
},
```

## Optimistic updates

Add data to state immediately before API call resolves:

```typescript
sendMessage: async (message: string) => {
  const { currentConversation } = get();
  if (!currentConversation) {
    throw new Error('No active conversation');
  }

  // Add user message optimistically
  const userMessage: ChatMessage = {
    id: `msg-${Date.now()}`,
    role: 'user',
    content: message,
    timestamp: new Date().toISOString(),
  };

  set((state) => ({
    messages: [...state.messages, userMessage],
    isProcessing: true,
  }));

  try {
    // Send message async and poll for completion
    const response = await chatService.sendMessageAsync(
      currentConversation.id,
      message
    );

    set({ jobId: response.job_id });

    // Start polling for assistant response
    await chatService.pollJobStatus(response.job_id, {
      onComplete: (job) => {
        const assistantMessage = job.result.messages.find(m => m.role === 'assistant');
        if (assistantMessage) {
          set((state) => ({
            messages: [...state.messages, assistantMessage],
            isProcessing: false,
          }));
        }
      },
    });
  } catch (error) {
    set({
      isProcessing: false,
      errors: [{ message: error.message }],
    });
  }
},
```

## Polling pattern with setInterval

Store interval ID in state and clean up properly:

```typescript
interface VideoState {
  currentVideo: Video | null;
  isPolling: boolean;
  pollingInterval: ReturnType<typeof setInterval> | null;
  
  startPolling: (videoId: string, onComplete?: () => void) => void;
  stopPolling: () => void;
}

const POLLING_INTERVAL = 3000;

export const useVideoStore = create<VideoState>()((set, get) => ({
  currentVideo: null,
  isPolling: false,
  pollingInterval: null,

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

        // Stop polling if generation is complete or failed
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

  generateVideo: async (documentId: string) => {
    set({ isGenerating: true, error: null });
    try {
      const response = await videoService.generateVideo(documentId);
      set({ currentVideo: response, isGenerating: false });
      
      // Start polling for status updates
      get().startPolling(response.id);
    } catch (error) {
      set({ error: error.message, isGenerating: false });
      throw error;
    }
  },

  clearVideo: () => {
    get().stopPolling();
    set({ currentVideo: null, error: null });
  },
}));
```

Component usage:

```typescript
function VideoPlayer() {
  const currentVideo = useVideoStore(selectCurrentVideo);
  const isPolling = useVideoStore(selectVideoIsPolling);

  useEffect(() => {
    // Cleanup polling on unmount
    return () => {
      useVideoStore.getState().stopPolling();
    };
  }, []);

  return (
    <div>
      {isPolling && <ProgressBar percent={currentVideo?.progress_percent ?? 0} />}
      {currentVideo?.video_url && <video src={currentVideo.video_url} />}
    </div>
  );
}
```

## Job polling with progress callbacks

Pattern for async jobs with progress tracking:

```typescript
startConversationAsync: async (prompt: string) => {
  const { isProcessing, jobId } = get();

  // Prevent duplicate calls
  if (isProcessing || jobId) return;

  set({
    isProcessing: true,
    errors: [],
    chatProgress: {
      currentPhase: 'analyzing_request',
      overallProgress: 10,
      currentActivity: 'Processing your message...',
    },
  });

  try {
    const response = await chatService.createConversationAsync(prompt);
    set({ jobId: response.job_id });

    // Start polling with callbacks
    await chatService.pollJobStatus(
      response.job_id,
      {
        onProgress: (job) => {
          set({
            chatProgress: {
              currentPhase: job.current_phase ?? 'analyzing_request',
              overallProgress: job.progress,
              currentActivity: job.current_activity,
            },
          });
        },
        onComplete: (job) => {
          if (job.result) {
            set({
              isProcessing: false,
              currentConversation: job.result,
              messages: job.result.messages,
              chatProgress: null,
              jobId: null,
            });
          }
        },
        onError: (error) => {
          set({
            isProcessing: false,
            errors: [{ message: error.message }],
            chatProgress: null,
            jobId: null,
          });
        },
      },
      { intervalMs: 1000, maxAttempts: 120 }
    );
  } catch (error) {
    set({
      isProcessing: false,
      errors: [{ message: error.message }],
      chatProgress: null,
      jobId: null,
    });
  }
},
```

## persist middleware with partialize

Use `persist` to save selected fields to localStorage/sessionStorage:

```typescript
export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      isAuthenticated: false,
      isInitializing: true,
      isLoading: false,
      currentTenant: null,
      availableTenants: [],
      userRole: 'viewer',

      // ... actions
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        // Only persist these fields
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        currentTenant: state.currentTenant,
        availableTenants: state.availableTenants,
        userRole: state.userRole,
        // Exclude transient state: isInitializing, isLoading, error
      }),
    }
  )
);
```

Custom storage (sessionStorage instead of localStorage):

```typescript
export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({ /* state */ }),
    {
      name: 'session-auth',
      storage: {
        getItem: (name) => {
          const str = sessionStorage.getItem(name);
          return str ? JSON.parse(str) : null;
        },
        setItem: (name, value) =>
          sessionStorage.setItem(name, JSON.stringify(value)),
        removeItem: (name) => sessionStorage.removeItem(name),
      },
      partialize: (state) => ({
        isAuthenticated: state.isAuthenticated,
        frontEndPermissions: state.frontEndPermissions,
        activeOrgId: state.activeOrgId,
        activeRoleSlug: state.activeRoleSlug,
      }),
    }
  )
);
```

## HMR persistence wrapper (dev-only)

Preserve state across hot module replacement during development:

```typescript
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
export const useInterviewStore = create<InterviewState>()(
  persistHMR('interviewStore', (set, get) => ({
    currentInterview: null,
    isRecording: false,
    transcript: [],
    // ... rest of store
  }))
);
```

## Session restoration pattern

For auth stores, restore session on app mount:

```typescript
checkAuth: async () => {
  const token = getAccessToken();
  if (!token) {
    set({ isInitializing: false, isAuthenticated: false });
    return;
  }

  try {
    const { user, tenants } = await fetchUserAndTenants();

    // Check if we have a persisted tenant selection
    const { currentTenant: persistedTenant } = get();
    let tenantToSwitch: Tenant | null = null;

    // Use persisted tenant if it's still in the available list
    if (persistedTenant && tenants.find((t) => t.id === persistedTenant.id)) {
      tenantToSwitch = persistedTenant;
    } else if (tenants.length > 0 && tenants[0]) {
      tenantToSwitch = tenants[0];
    }

    // Switch to tenant to get tenant-scoped tokens
    if (tenantToSwitch) {
      try {
        const switchResponse = await authService.switchTenant(tenantToSwitch.id);
        tenantToSwitch = switchResponse.tenant;
      } catch (switchError) {
        console.error('Failed to switch tenant during initialization:', switchError);
        // Continue with tenant data we have
      }
    }

    set({
      user,
      isAuthenticated: true,
      isInitializing: false,
      availableTenants: tenants,
      currentTenant: tenantToSwitch,
      userRole: tenantToSwitch?.role ?? 'viewer',
    });
  } catch (error) {
    // Only clear tokens on auth errors (401)
    const isAuthError = error instanceof APIError && error.status === 401;

    if (isAuthError) {
      clearTokens();
      set({
        user: null,
        isAuthenticated: false,
        isInitializing: false,
        currentTenant: null,
        availableTenants: [],
        userRole: 'viewer',
      });
    } else {
      // Keep persisted auth state on network errors
      const { user: persistedUser, currentTenant, availableTenants, userRole } = get();
      set({
        isInitializing: false,
        isAuthenticated: persistedUser !== null,
        user: persistedUser,
        currentTenant,
        availableTenants,
        userRole,
      });
    }
  }
},
```

## Pagination state

Track pagination and filters, reset page when filters change:

```typescript
interface ReportsState {
  reports: Report[];
  filters: ReportFilters;
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  } | null;

  loadReports: (filters?: ReportFilters) => Promise<void>;
  setFilters: (filters: Partial<ReportFilters>) => void;
}

export const useReportsStore = create<ReportsState>()((set, get) => ({
  reports: [],
  filters: {
    type: 'all',
    status: 'all',
    region: 'all',
    tenants: [],
    page: 1,
    page_size: 20,
  },
  pagination: null,

  loadReports: async (filters?: ReportFilters) => {
    const currentFilters = filters ?? get().filters;
    set({ isLoading: true, error: null, filters: currentFilters });

    try {
      const response = await reportsService.listReports(currentFilters);
      set({
        reports: response.items,
        pagination: response.pagination,
        isLoading: false,
      });
    } catch (error) {
      set({ error: error.message, isLoading: false });
      throw error;
    }
  },

  setFilters: (filters: Partial<ReportFilters>) => {
    const currentFilters = get().filters;
    // If page is explicitly being set, use it; otherwise reset to 1
    const page = filters.page !== undefined ? filters.page : 1;
    const newFilters = { ...currentFilters, ...filters, page };
    set({ filters: newFilters });
    void get().loadReports(newFilters);
  },

  setTypeFilter: (type: ReportType | 'all') => {
    get().setFilters({ type });
  },
}));
```
