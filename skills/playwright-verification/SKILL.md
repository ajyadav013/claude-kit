---
name: playwright-verification
description: Run E2E tests after deployment to verify page loads, navigation flows, user interactions, and cross-browser compatibility using the project's E2E framework.
argument-hint: [page route, "smoke", "all", or "cross-browser"]
disable-model-invocation: true
---

Run E2E verification for: $ARGUMENTS.

## Steps

1. **Determine test scope**: Based on `$ARGUMENTS`, select the test scope according to the project's E2E framework configuration. Common patterns:

   | Argument | Scope | Example Command Pattern |
   |----------|-------|------------------------|
   | `smoke` | All smoke tests | Run smoke test suite |
   | `all` | All E2E tests | Run all E2E tests |
   | `cross-browser` | All tests on multiple browsers | Run tests on Chromium + Firefox + WebKit |
   | `/route` | Tests for a specific page | Run tests for a specific route |
   | `mobile` | Mobile viewport tests | Run mobile-specific tests |

2. **Ensure dev server is running**: Check if the app is running at the configured URL (e.g., `http://localhost:5173`, `http://localhost:3000`, `http://localhost:8000`). If not, start it according to the project's setup.

3. **Run the tests**: Execute the project's E2E test suite with the selected scope.

4. **If writing new tests**, follow these conventions:

   ### Test File Structure (Example Pattern)
   ```typescript
   // Example using Playwright syntax - adapt to project's E2E framework
   import { test, expect } from '@playwright/test';

   test.describe('Page Name', () => {
     test.beforeEach(async ({ page }) => {
       await page.goto('/route');
     });

     test('loads successfully', async ({ page }) => {
       await expect(page.locator('main#main-content')).toBeVisible();
     });

     test('displays key content', async ({ page }) => {
       await expect(page.getByRole('heading', { name: 'Page Title' })).toBeVisible();
     });

     test('navigation works', async ({ page }) => {
       await page.click('a[href="/next-page"]');
       await expect(page).toHaveURL('/next-page');
     });

     test('user interaction flow', async ({ page }) => {
       await page.getByRole('button', { name: 'Action' }).click();
       await expect(page.getByText('Result')).toBeVisible();
     });
   });
   ```

   ### Selector Priority (Accessibility-First)
   | Priority | Selector Type | Example |
   |----------|---------------|---------|
   | 1 | Role-based | `getByRole('button', { name: 'Submit' })` |
   | 2 | Text content | `getByText('Exception #1234')` |
   | 3 | Label association | `getByLabel('Search')` |
   | 4 | Placeholder | `getByPlaceholder('Filter by name')` |
   | 5 | Test IDs | `[data-testid="metric-card"]` |
   | 6 | CSS/XPath | `main#main-content` (last resort) |

   ### Page Object Model (for complex pages)
   ```typescript
   // Example using Playwright - adapt to project's framework
   import { Page, Locator, expect } from '@playwright/test';

   export class DashboardPage {
     readonly page: Page;
     readonly heading: Locator;
     readonly metricCards: Locator;
     readonly sidebar: Locator;

     constructor(page: Page) {
       this.page = page;
       this.heading = page.getByRole('heading', { level: 1 });
       this.metricCards = page.locator('[data-testid="metric-card"]');
       this.sidebar = page.locator('aside');
     }

     async goto() {
       await this.page.goto('/');
       await expect(this.page.locator('main#main-content')).toBeVisible();
     }

     async getMetricCount() {
       return this.metricCards.count();
     }

     async navigateTo(route: string) {
       await this.page.click(`a[href="${route}"]`);
       await expect(this.page).toHaveURL(route);
     }
   }
   ```

5. **Check test results**: Review the output for failures.

   ### On Failure
   - Read the error message and trace
   - Open the test framework's report viewer (e.g., HTML report)
   - Check the trace viewer for step-by-step screenshots/recordings
   - Fix the issue in the application code (not by weakening the test)

6. **Report results**: Output a summary table:

   | Test Suite | Passed | Failed | Skipped | Duration |
   |-----------|--------|--------|---------|----------|

   For failures:
   | Test | Error | File:Line | Suggested Fix |
   |------|-------|-----------|---------------|

## Test Categories

### Smoke Tests
Every route loads without errors:
- Main content is visible
- No console errors
- Navigation works
- Critical user paths complete

### Page Tests
Feature-specific user flows:
- Key content renders
- Filters and search work
- Interactive elements respond correctly
- Data displays correctly

### Cross-Cutting Tests
- User state changes (e.g., persona/role switching) update the view
- Global filters update data across pages
- Responsive behavior at key breakpoints
- Authentication flows
- Error states

## E2E Framework Config Reference

Example configuration (adapt to project's framework):

```typescript
// Example using Playwright - adapt as needed
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['html'], ['list']],
  use: {
    baseURL: 'http://localhost:5173', // Adjust to project's dev server
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 5'] } },
    { name: 'mobile-safari', use: { ...devices['iPhone 13'] } },
    { name: 'tablet', use: { ...devices['iPad (gen 7)'] } },
  ],
  webServer: {
    command: 'npm run dev', // Adjust to project's dev command
    url: 'http://localhost:5173', // Adjust to project's dev server
    reuseExistingServer: !process.env.CI,
  },
});
```

## E2E Directory Structure Example

```
e2e/
  smoke.spec.ts                # Smoke tests covering all routes
  pages/
    dashboard.spec.ts          # Page-specific tests
    feature-a.spec.ts
    feature-b.spec.ts
    models/
      DashboardPage.ts         # Page Object Models
      FeatureAPage.ts
  cross-cutting/
    auth.spec.ts               # Authentication flows
    responsive.spec.ts         # Responsive behavior tests
    navigation.spec.ts         # Global navigation tests
  fixtures/
    test-helpers.ts            # Shared test utilities
```

## Route Organization

Structure E2E tests to match the application's route hierarchy. Identify critical user paths and create dedicated test suites for:
- Landing/dashboard pages
- Primary features (list, detail, create, edit flows)
- Admin/settings pages
- Authentication/authorization flows
- Error and empty states
