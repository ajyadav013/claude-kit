---
name: performance-optimization
description: Analyze and optimize application performance covering web vitals, bundle size, code splitting, chunking strategy, and rendering best practices for web frontends.
argument-hint: [page, component, or "bundle"]
disable-model-invocation: true
---

Optimize performance for: $ARGUMENTS.

## Steps

1. **Identify the optimization target**: Determine if this is a bundle optimization, render performance issue, or Core Web Vitals improvement for `$ARGUMENTS`.

2. **Gather baseline metrics**: Run the appropriate analysis tools.

   ### Bundle Analysis
   ```bash
   # Use the project's bundle analyzer (examples: vite-bundle-visualizer, webpack-bundle-analyzer, esbuild analyzer)
   # Run the project's build and check output for chunk sizes
   ```

   ### Runtime Performance
   - Use the `auditor` agent or Chrome DevTools to run a Lighthouse trace on the target page
   - Check for framework-specific warnings in the browser console

3. **Apply optimizations based on category**:

---

### A. Bundle Optimization

#### Code Splitting (Route-Level)
Every major route should be lazy-loaded where the framework supports it:

**React/Preact example:**
```typescript
// App entry point
const DashboardPage = React.lazy(() => import('./pages/DashboardPage'));
const DataPage = React.lazy(() => import('./pages/DataPage'));

// Wrap in Suspense
<Suspense fallback={<Spinner />}>
  <Route path="/" element={<DashboardPage />} />
</Suspense>
```

**Vue example:**
```javascript
const routes = [
  { path: '/', component: () => import('./pages/DashboardPage.vue') },
  { path: '/data', component: () => import('./pages/DataPage.vue') },
];
```

**Angular example:**
```typescript
// In routing module
const routes: Routes = [
  { path: 'dashboard', loadChildren: () => import('./dashboard/dashboard.module').then(m => m.DashboardModule) },
];
```

#### Tree Shaking
- Import only what you use:
  ```typescript
  // GOOD
  import { IconName, SpecificIcon } from 'icon-library';

  // BAD
  import * as Icons from 'icon-library';
  ```
- Verify chart/visualization library imports are specific (e.g., import only the chart types you need)

#### Chunk Strategy
| Chunk | Contents | Target Size |
|-------|----------|-------------|
| `vendor-core` | Core framework (react/vue/angular) + router | ~40-50KB gz |
| `vendor-ui` | UI component library | ~30KB gz |
| `vendor-charts` | Chart/visualization libraries | ~50KB gz (lazy) |
| `app` | Application code | <100KB gz |
| Route chunks | Per-page code | <30KB gz each |

**Example configuration (adapt to your bundler):**

Vite:
```typescript
build: {
  rollupOptions: {
    output: {
      manualChunks: {
        'vendor-core': ['framework', 'framework-router'],
        'vendor-ui': ['ui-library-pkg'],
        'vendor-charts': ['chart-library'],
      },
    },
  },
},
```

Webpack:
```javascript
optimization: {
  splitChunks: {
    cacheGroups: {
      vendor: { test: /[\\/]node_modules[\\/]/, name: 'vendor' },
      // ... custom groups
    },
  },
},
```

#### Bundle Size Targets
| Metric | Target | Alert |
|--------|--------|-------|
| Initial JS (gzipped) | < 200KB | > 250KB |
| Largest chunk (gzipped) | < 100KB | > 120KB |
| Total CSS (gzipped) | < 30KB | > 50KB |

---

### B. UI Rendering Performance

#### Avoid Unnecessary Re-renders
**React/Preact:**
```typescript
// Use memoization for pure display components
const MetricCard = React.memo(function MetricCard({ title, value }: Props) {
  return <div>...</div>;
});

// Use memoization for expensive derivations
const sortedItems = useMemo(() =>
  items.sort((a, b) => b.priority - a.priority),
  [items]
);

// Use callbacks for handlers passed as props
const handleFilter = useCallback((value: string) => {
  setFilter(value);
}, []);
```

**Vue:**
```vue
<script setup>
// Use computed properties for derived state
const sortedItems = computed(() =>
  items.value.sort((a, b) => b.priority - a.priority)
);
</script>
```

**Angular:**
```typescript
// Use OnPush change detection for pure components
@Component({
  changeDetection: ChangeDetectionStrategy.OnPush
})
```

#### Client State Store Anti-patterns
**Zustand (React) example:**
```typescript
// BAD - subscribes to entire store, re-renders on ANY change
const store = useStore();

// GOOD - subscribe to specific values
const items = useStore((s) => s.items);
const setFilter = useStore((s) => s.setFilter);

// BAD - creates new reference every render
const filtered = useStore((s) => s.items.filter(i => i.active));

// GOOD - store derived data as state, recompute in actions
const filteredItems = useStore((s) => s.filteredItems);
```

**Pinia (Vue) / Vuex:**
```javascript
// Use getters for derived state, not computed in components
const store = useMyStore();
const filteredItems = store.filteredItems; // getter defined in store
```

**NgRx (Angular):**
```typescript
// Use selectors for derived state
const filteredItems$ = store.select(selectFilteredItems);
```

#### Virtualization
Use virtualization for lists with > 50 items. Examples by framework:

**React:**
```typescript
import { useVirtualizer } from '@tanstack/react-virtual';

function VirtualList({ items }: { items: Item[] }) {
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 64,
  });

  return (
    <div ref={parentRef} className="h-[600px] overflow-auto">
      <div style={{ height: virtualizer.getTotalSize() }} className="relative w-full">
        {virtualizer.getVirtualItems().map((virtualItem) => (
          <div
            key={virtualItem.key}
            className="absolute top-0 left-0 w-full"
            style={{ height: virtualItem.size, transform: `translateY(${virtualItem.start}px)` }}
          >
            <ItemRow item={items[virtualItem.index]} />
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Vue:** Use `vue-virtual-scroller` or `@tanstack/vue-virtual`

**Angular:** Use `@angular/cdk/scrolling` with `cdk-virtual-scroll-viewport`

---

### C. Core Web Vitals

| Metric | Target | Common Fixes |
|--------|--------|-------------|
| LCP < 2.5s | Optimize critical rendering path | Lazy-load below-fold content, preload fonts |
| FID < 100ms | Minimize main thread work | Code-split heavy components, defer non-critical JS |
| CLS < 0.1 | Prevent layout shifts | Set explicit dimensions on images/containers, use min-height |
| INP < 200ms | Fast interactions | Debounce handlers, use framework-specific non-blocking APIs (e.g., React `startTransition`) |

#### Font Loading
```html
<!-- Preconnect to font CDN (if using web fonts) -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>

<!-- Or use font-display: swap in CSS -->
@font-face {
  font-family: 'CustomFont';
  font-display: swap;
  src: url('/fonts/custom.woff2') format('woff2');
}
```

#### Image Optimization
- Use the project's optimized image component if available
- Specify `width` and `height` attributes to prevent CLS
- Use `loading="lazy"` for below-fold images
- Consider using modern formats (WebP, AVIF) with fallbacks

---

4. **Verify improvements**: Re-run analysis tools and compare against baseline.

5. **Report**: Output a before/after comparison table:

   | Metric | Before | After | Change |
   |--------|--------|-------|--------|
   | Initial bundle | Xkb | Ykb | -Z% |
   | LCP | Xs | Ys | -Zms |
   | ... | ... | ... | ... |

6. **Run build**: Execute the project's build command to confirm the build still passes.

## References

- Check the project's bundler config (e.g., `vite.config.ts`, `webpack.config.js`, `angular.json`)
- Consult the project's design system documentation for image/icon sizing guidelines
- Use the project's virtualization library (e.g., `@tanstack/react-virtual`, `vue-virtual-scroller`, `@angular/cdk/scrolling`)
