# Store Structure and Selectors

## Typed store with State + Actions interface

Define a single interface that declares both state fields and action methods:

```typescript
interface AuthState {
  // State
  user: User | null;
  isAuthenticated: boolean;
  isInitializing: boolean;
  isLoading: boolean;
  currentTenant: Tenant | null;
  availableTenants: Tenant[];
  userRole: UserRole;

  // Actions
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
  switchTenant: (tenantId: string) => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      // Initial state
      user: null,
      isAuthenticated: false,
      isInitializing: true,
      isLoading: false,
      currentTenant: null,
      availableTenants: [],
      userRole: 'viewer',

      // Actions implementation
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
      // ... other actions
    }),
    { name: 'auth-storage' }
  )
);
```

## Initial state constant

Define initial state separately for reuse in reset actions:

```typescript
const initialState = {
  user: null,
  isAuthenticated: false,
  isInitializing: true,
  isLoading: false,
  currentTenant: null,
  availableTenants: [],
  userRole: 'viewer' as UserRole,
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      ...initialState,
      
      logout: async () => {
        try {
          await authService.logout();
        } finally {
          set({
            user: null,
            isAuthenticated: false,
            currentTenant: null,
            availableTenants: [],
            userRole: 'viewer',
          });
        }
      },

      reset: () => set({ ...initialState }),
    }),
    { name: 'auth-storage' }
  )
);
```

## Exported selector functions

Export named selectors for field access and computed values:

```typescript
/**
 * Selectors for authentication store state access.
 */
export const selectUser = (state: AuthState) => state.user;
export const selectIsAuthenticated = (state: AuthState) => state.isAuthenticated;
export const selectIsInitializing = (state: AuthState) => state.isInitializing;
export const selectIsLoading = (state: AuthState) => state.isLoading;

/** Returns the currently active tenant the user is scoped to for API calls. */
export const selectCurrentTenant = (state: AuthState) => state.currentTenant;

/** Returns all tenants the authenticated user has access to across organizations. */
export const selectAvailableTenants = (state: AuthState) => state.availableTenants;

/** Returns the user's role within the currently active tenant (admin, editor, viewer). */
export const selectUserRole = (state: AuthState) => state.userRole;
```

Usage in components:

```typescript
// Granular subscription - only re-renders when user changes
const user = useAuthStore(selectUser);

// Avoid this - re-renders on ANY state change
const state = useAuthStore();
```

## Computed selectors

For derived state, use selectors instead of storing duplicated values:

```typescript
/** Filters insights to those matching a specific type. */
export const selectInsightsByType =
  (type: 'success_pattern' | 'improvement' | 'warning') => (state: AnalyticsState) =>
    state.insights.filter((insight) => insight.type === type);

/** Returns only recent reports from the current loaded list. */
export const selectRecentReports = (state: ReportsState) =>
  state.reports.filter((report) => report.status === 'recent');

/** Returns true if no reference tenants are configured. */
export const selectHasNoReferenceTenants = (state: ReportsState) =>
  state.referenceTenants.length === 0;
```

## StateCreator slices for complex stores

For large stores, break into logical slices:

```typescript
import { StateCreator } from 'zustand';

type InterviewState = RecordingSlice & TranscriptSlice & InsightsSlice;

interface RecordingSlice {
  isRecording: boolean;
  isPaused: boolean;
  recordingDuration: number;
  startRecording: () => void;
  stopRecording: () => void;
  updateDuration: (duration: number) => void;
}

interface TranscriptSlice {
  transcript: TranscriptSegment[];
  currentSpeechText: string;
  addTranscriptSegment: (segment: TranscriptSegment) => void;
  clearTranscript: () => void;
}

interface InsightsSlice {
  insights: AIInsight[];
  followUpQuestions: FollowUpQuestion[];
  addInsight: (insight: AIInsight) => void;
  addFollowUpQuestion: (question: FollowUpQuestion) => void;
}

const createRecordingSlice: StateCreator<InterviewState, [], [], RecordingSlice> = (set, get) => ({
  isRecording: false,
  isPaused: false,
  recordingDuration: 0,
  
  startRecording: () => {
    set({ isRecording: true, isPaused: false, recordingDuration: 0 });
  },
  
  stopRecording: () => {
    set({ isRecording: false, isPaused: false });
  },
  
  updateDuration: (duration) => {
    set({ recordingDuration: duration });
  },
});

const createTranscriptSlice: StateCreator<InterviewState, [], [], TranscriptSlice> = (set) => ({
  transcript: [],
  currentSpeechText: '',
  
  addTranscriptSegment: (segment) => {
    set((state) => ({
      transcript: [...state.transcript, segment],
    }));
  },
  
  clearTranscript: () => set({ transcript: [], currentSpeechText: '' }),
});

// Combine slices
export const useInterviewStore = create<InterviewState>()(
  (set, get, api) => ({
    ...createRecordingSlice(set, get, api),
    ...createTranscriptSlice(set, get, api),
    ...createInsightsSlice(set, get, api),
  })
);
```

## Immutable nested updates

Always use spread operators for nested updates:

```typescript
// Adding to array
addInsight: (insight) => {
  set((state) => ({
    insights: [...state.insights, insight],
  }));
},

// Updating nested object
updateProfile: async (data) => {
  const updatedUser = await authService.updateProfile(data);
  set({ user: updatedUser });
  return updatedUser;
},

// Updating array element
updateVideoUrl: (url: string) => {
  set((state) => ({
    currentVideo: state.currentVideo
      ? { ...state.currentVideo, video_url: url }
      : null,
  }));
},

// Merging filters
setFilters: (filters: Partial<ReportFilters>) => {
  const currentFilters = get().filters;
  const page = filters.page !== undefined ? filters.page : 1;
  const newFilters = { ...currentFilters, ...filters, page };
  set({ filters: newFilters });
},
```

## Action naming conventions

- **Imperative verbs** for actions: `login`, `logout`, `loadReports`, `approveDocument`, `setFilters`, `switchTenant`
- **`select*` prefix** for selectors: `selectUser`, `selectCurrentTenant`, `selectIsLoading`
- **`is*` or `has*` prefix** for boolean flags: `isLoading`, `isAuthenticated`, `hasUnreadMessages`, `isInitializing`
- **Specific action names** over generic ones: `loadReports` instead of `load`, `switchTenant` instead of `switch`
