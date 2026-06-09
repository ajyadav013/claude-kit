---
name: manual-test
description: Manually test a developed feature using browser automation in headed mode. Navigates to the page, interacts with elements, and verifies behavior visually — like a QA tester sitting at the screen.
argument-hint: [page route or feature name, e.g. "/store-view", "dashboard filters", "exception card"]
disable-model-invocation: true
---

Manually test the feature: $ARGUMENTS.

## Steps

### 1. Identify what to test

Based on `$ARGUMENTS`, determine:
- Which page/route to navigate to
- Which UI elements to interact with
- What behavior to verify (renders, clicks, filters, navigation, edge cases)

If `$ARGUMENTS` is vague, ask the user:
- Which page or component should I test?
- What specific behavior should I verify?
- Any particular edge cases to check?

### 2. Set up authenticated browser session

If the app requires authentication, use the project's E2E framework to create a headed (visible) browser session with auth bypassed or configured.

The helper should support **multiple browsers** and **custom viewports** for device simulation. Example pattern (adapt to your project's E2E framework):

```typescript
// Example using Playwright
import { test, expect } from '@playwright/test';
import { chromium, firefox, webkit } from '@playwright/test';
import type { BrowserType } from '@playwright/test';

// Supported browsers
const BROWSERS = {
  chrome: chromium,
  firefox: firefox,
  safari: webkit,
} as const;

// Device presets — screen sizes for testing
const DEVICES = {
  // Mobile
  'iphone-se':       { width: 375,  height: 667,  label: 'iPhone SE',           isMobile: true },
  'iphone-14':       { width: 390,  height: 844,  label: 'iPhone 14',           isMobile: true },
  'iphone-14-pro-max': { width: 430, height: 932, label: 'iPhone 14 Pro Max',   isMobile: true },
  'pixel-7':         { width: 412,  height: 915,  label: 'Pixel 7',             isMobile: true },
  'samsung-s23':     { width: 360,  height: 780,  label: 'Samsung Galaxy S23',  isMobile: true },
  // Tablet
  'ipad':            { width: 768,  height: 1024, label: 'iPad',                isMobile: true },
  'ipad-pro':        { width: 1024, height: 1366, label: 'iPad Pro 12.9"',      isMobile: true },
  'android-tablet':  { width: 800,  height: 1280, label: 'Android Tablet',      isMobile: true },
  // Desktop
  'laptop':          { width: 1366, height: 768,  label: 'Laptop (1366x768)',    isMobile: false },
  'desktop':         { width: 1920, height: 1080, label: 'Desktop (1080p)',      isMobile: false },
  'desktop-xl':      { width: 2560, height: 1440, label: 'Desktop (1440p)',      isMobile: false },
} as const;

type BrowserName = keyof typeof BROWSERS;
type DeviceName = keyof typeof DEVICES;

interface AuthPageOptions {
  browser?: BrowserName;            // default: 'chrome'
  device?: DeviceName;              // default: 'desktop'
  viewport?: { width: number; height: number }; // custom override
}

async function createAuthenticatedPage(options: AuthPageOptions = {}) {
  const browserName = options.browser ?? 'chrome';
  const browserType = BROWSERS[browserName];
  const device = options.device ? DEVICES[options.device] : undefined;
  const viewport = options.viewport ?? (device ? { width: device.width, height: device.height } : { width: 1920, height: 1080 });

  const browser = await browserType.launch({ headless: false });
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport,
    isMobile: device?.isMobile ?? false,
    hasTouch: device?.isMobile ?? false,
    userAgent: device?.isMobile
      ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
      : undefined,
  });
  const page = await context.newPage();

  const deviceLabel = device?.label ?? `${viewport.width}x${viewport.height}`;
  console.log(`Browser: ${browserName} | Device: ${deviceLabel} | Viewport: ${viewport.width}x${viewport.height}`);

  // Mock authentication or inject session storage
  // Adapt this to your project's auth mechanism
  await page.route('**/api/auth/session**', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        user: {
          firstName: 'Test', lastName: 'User',
          email: 'test@example.com',
          role: 'admin',
        },
      }),
    });
  });

  // Navigate to login and inject session state
  await page.goto('http://localhost:3000/login', {
    waitUntil: 'domcontentloaded',
    timeout: 15000,
  });
  await page.evaluate(() => {
    sessionStorage.setItem('auth-state', JSON.stringify({
      isAuthenticated: true,
      user: {
        firstName: 'Test', lastName: 'User',
        email: 'test@example.com',
        role: 'admin',
      },
    }));
  });

  return { browser, context, page, browserName, deviceLabel, viewport };
}
```

### 3. Write the test file

Create the test in the appropriate E2E test directory. Name it `<feature>.manual.spec.ts` or follow your project's naming convention.

**Test template:**

```typescript
import { test, expect } from '@playwright/test';

// -- Auth helper with BROWSERS and DEVICES constants (from step 2) --

test.describe('<Feature Name> — Manual Test', () => {

  test('<what you are testing>', async () => {
    const { browser, page } = await createAuthenticatedPage();
    // Or with specific browser/device:
    // const { browser, page } = await createAuthenticatedPage({ browser: 'firefox' });
    // const { browser, page } = await createAuthenticatedPage({ device: 'iphone-14' });
    // const { browser, page } = await createAuthenticatedPage({ browser: 'safari', device: 'ipad' });

    try {
      await page.goto('http://localhost:3000/<route>', {
        waitUntil: 'networkidle',
        timeout: 30000,
      });

      await expect(page.locator('main')).toBeVisible({ timeout: 15000 });

      // ... your test steps here ...

    } finally {
      await browser.close();
    }
  });
});
```

### 4. Build the test based on the feature type

Pick the relevant test patterns below and combine them:

#### Page load verification
```typescript
// Verify page renders with key content
await page.goto('http://localhost:3000/<route>', {
  waitUntil: 'networkidle', timeout: 30000,
});
await expect(page.locator('main')).toBeVisible({ timeout: 15000 });
await expect(page.getByRole('heading', { name: '<Page Title>' })).toBeVisible();
```

#### Click interactions
```typescript
// Click a button and verify result
const button = page.getByRole('button', { name: '<Button Text>' });
await expect(button).toBeVisible();
await button.click();
await expect(page.getByText('<Expected Result>')).toBeVisible();
```

#### Filter / dropdown testing
```typescript
// Open a filter dropdown, select option, verify results update
const filterButton = page.getByRole('button', { name: '<Filter Name>' }).first();
await filterButton.click();
await page.waitForTimeout(500);
const dropdown = page.locator('.dropdown-container');
await expect(dropdown).toBeVisible();

// Count options
const optionCount = await dropdown.locator('ul li button').count();
console.log(`Filter options: ${optionCount}`);

// Select an option
const firstOption = dropdown.locator('ul li button').first();
const optionText = await firstOption.textContent();
console.log(`Selecting: "${optionText}"`);
await firstOption.click();
await page.waitForTimeout(1000);
```

#### Tab switching
```typescript
// Click a tab and verify content changes
const tab = page.getByRole('tab', { name: '<Tab Name>' });
await tab.click();
await expect(page.getByRole('tabpanel')).toBeVisible();
await expect(page.getByText('<Expected Content>')).toBeVisible();
```

#### Navigation
```typescript
// Click a link/card and verify navigation
await page.click('a[href="/<target-route>"]');
await expect(page).toHaveURL('/<target-route>');
await expect(page.locator('main')).toBeVisible();
```

#### Table / list verification
```typescript
// Verify table renders with data
const table = page.locator('table');
await expect(table).toBeVisible();
const rows = table.locator('tbody tr');
const rowCount = await rows.count();
console.log(`Table rows: ${rowCount}`);
expect(rowCount).toBeGreaterThan(0);
```

#### Empty state
```typescript
// Verify empty state shows when no data
await expect(page.getByText(/no.*found/i)).toBeVisible();
```

#### Cross-browser testing (Chrome + Firefox + Safari)

**ALWAYS run tests on multiple browsers.** Write a loop that tests the same page on Chrome, Firefox, and Safari:

```typescript
// Test on all three browsers
for (const browserName of ['chrome', 'firefox', 'safari'] as const) {
  test(`<Feature> works on ${browserName}`, async () => {
    const { browser, page, deviceLabel } = await createAuthenticatedPage({ browser: browserName });

    try {
      await page.goto('http://localhost:3000/<route>', {
        waitUntil: 'networkidle', timeout: 30000,
      });
      await expect(page.locator('main')).toBeVisible({ timeout: 15000 });

      // ... your test assertions here ...

      await page.screenshot({
        path: `e2e/screenshots/<feature>-${browserName}.png`,
        fullPage: true,
      });
      console.log(`[${browserName}] PASSED`);
    } finally {
      await browser.close();
    }
  });
}
```

#### Multi-device responsive testing

**ALWAYS test on multiple screen sizes.** This runs the same test across mobile phones, tablets, and desktop screens:

```typescript
// Devices to test — covers the critical breakpoints
const TEST_DEVICES: DeviceName[] = [
  'iphone-se',         // 375px — smallest supported mobile
  'iphone-14',         // 390px — common iPhone
  'pixel-7',           // 412px — common Android
  'ipad',              // 768px — tablet breakpoint
  'ipad-pro',          // 1024px — large tablet / small laptop
  'laptop',            // 1366px — common laptop
  'desktop',           // 1920px — full HD desktop
];

for (const deviceName of TEST_DEVICES) {
  test(`<Feature> renders correctly on ${DEVICES[deviceName].label}`, async () => {
    const { browser, page, deviceLabel, viewport } = await createAuthenticatedPage({
      device: deviceName,
    });

    try {
      await page.goto('http://localhost:3000/<route>', {
        waitUntil: 'networkidle', timeout: 30000,
      });

      // Verify page loads
      await expect(page.locator('main')).toBeVisible({ timeout: 15000 });

      // Check for horizontal overflow (common mobile bug)
      const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
      const windowWidth = await page.evaluate(() => window.innerWidth);
      const hasOverflow = bodyWidth > windowWidth + 1;
      console.log(`[${deviceLabel}] ${viewport.width}x${viewport.height} | Overflow: ${hasOverflow ? 'YES (BUG)' : 'none'}`);
      expect(hasOverflow, `Horizontal overflow detected on ${deviceLabel}`).toBe(false);

      // Check touch targets on mobile (buttons should be at least 44px)
      if (DEVICES[deviceName].isMobile) {
        const buttons = page.locator('button:visible');
        const buttonCount = await buttons.count();
        for (let i = 0; i < Math.min(buttonCount, 10); i++) {
          const box = await buttons.nth(i).boundingBox();
          if (box && box.height < 44) {
            const text = await buttons.nth(i).textContent();
            console.log(`  WARNING: Button "${text?.trim()}" is ${box.height}px tall (min 44px)`);
          }
        }
      }

      // Screenshot for visual comparison
      await page.screenshot({
        path: `e2e/screenshots/<feature>-${deviceName}.png`,
        fullPage: true,
      });
      console.log(`[${deviceLabel}] PASSED — screenshot saved`);

    } finally {
      await browser.close();
    }
  });
}
```

#### Cross-browser + cross-device matrix (full coverage)

For critical features, test every browser on every device size:

```typescript
// Full matrix: 3 browsers x 3 key screen sizes
const BROWSER_LIST: BrowserName[] = ['chrome', 'firefox', 'safari'];
const KEY_DEVICES: DeviceName[] = ['iphone-se', 'ipad', 'desktop'];

for (const browserName of BROWSER_LIST) {
  for (const deviceName of KEY_DEVICES) {
    test(`<Feature> on ${browserName} @ ${DEVICES[deviceName].label}`, async () => {
      const { browser, page } = await createAuthenticatedPage({
        browser: browserName,
        device: deviceName,
      });

      try {
        await page.goto('http://localhost:3000/<route>', {
          waitUntil: 'networkidle', timeout: 30000,
        });
        await expect(page.locator('main')).toBeVisible({ timeout: 15000 });

        // ... assertions ...

        await page.screenshot({
          path: `e2e/screenshots/<feature>-${browserName}-${deviceName}.png`,
          fullPage: true,
        });
        console.log(`[${browserName} | ${DEVICES[deviceName].label}] PASSED`);
      } finally {
        await browser.close();
      }
    });
  }
}
```

#### Screenshot capture
```typescript
// Take a screenshot for visual review
await page.screenshot({ path: `e2e/screenshots/<feature>-<state>.png`, fullPage: true });
console.log('Screenshot saved: e2e/screenshots/<feature>-<state>.png');
```

### 5. Run the test

Make sure the dev server is running first, then run the manual test using the project's E2E test runner:

```bash
# Ensure dev server is running (in a separate terminal or background)
# Use the project's dev server command (examples: npm run dev, npm start, yarn dev, pnpm dev)

# Run the specific manual test in headed mode
# Adjust command based on your E2E framework (Playwright, Cypress, etc.)
# Example with Playwright:
npx playwright test e2e/manual/<feature>.manual.spec.ts --headed --reporter=list

# Run all manual tests
npx playwright test e2e/manual/ --headed --reporter=list

# Run with longer timeout for cross-browser matrix tests
npx playwright test e2e/manual/<feature>.manual.spec.ts --headed --reporter=list --timeout=120000
```

**Important flags (Playwright example - adapt to your E2E framework):**
- `--headed` — opens a visible browser window so you can see the test running
- `--reporter=list` — shows step-by-step output in terminal
- `--timeout=120000` — increase timeout for multi-browser tests (2 min per test)
- `--debug` — opens test inspector for step-by-step debugging (optional)
- `--workers=1` — run tests sequentially (easier to watch headed browser)

**Note:** If using Playwright, Firefox and Safari (WebKit) require browser binaries. If not installed:
```bash
npx playwright install firefox webkit
```

### 6. Report results

After running, output a report with browser and device coverage:

**If all tests pass:**
```
Manual Test Results: <Feature Name>
Route: /<route>
Status: PASSED

Browser Coverage:
  [PASS] Chrome (Desktop 1920x1080)
  [PASS] Firefox (Desktop 1920x1080)
  [PASS] Safari/WebKit (Desktop 1920x1080)

Device Coverage:
  [PASS] iPhone SE (375x667) — no overflow, touch targets OK
  [PASS] iPhone 14 (390x844) — no overflow, touch targets OK
  [PASS] Pixel 7 (412x915) — no overflow, touch targets OK
  [PASS] iPad (768x1024) — no overflow
  [PASS] Laptop (1366x768) — no overflow
  [PASS] Desktop (1920x1080) — no overflow

Feature Tests:
  [PASS] Page loads with expected content
  [PASS] <Interaction> works correctly
  [PASS] <Filter/navigation> behaves as expected

Screenshots: e2e/screenshots/<feature>-*.png (one per browser/device)
```

**If any test fails:**
```
Manual Test Results: <Feature Name>
Route: /<route>
Status: FAILED

Failures:
  [FAIL] Firefox @ iPad (768x1024)
    Issue: Horizontal overflow detected (body 820px > viewport 768px)
    Screenshot: e2e/screenshots/<feature>-firefox-ipad.png

  [FAIL] Chrome @ iPhone SE (375x667)
    Issue: Button "Apply Filters" is 32px tall (minimum 44px for touch)
    Screenshot: e2e/screenshots/<feature>-chrome-iphone-se.png

Suggested fixes:
  1. Add overflow wrapper on the filter bar container
  2. Increase button minimum height to 44px for touch targets
```

## Selector Priority

Always prefer accessible selectors:

| Priority | Selector | Example |
|----------|----------|---------|
| 1 | `getByRole` | `page.getByRole('button', { name: 'Apply' })` |
| 2 | `getByText` | `page.getByText('Total Revenue')` |
| 3 | `getByLabel` | `page.getByLabel('Search stores')` |
| 4 | `getByPlaceholder` | `page.getByPlaceholder('Filter by name')` |
| 5 | `data-testid` | `page.locator('[data-testid="metric-card"]')` |
| 6 | CSS selector | `page.locator('main')` (last resort) |

## Supported Browsers

| Key | Browser | Engine | Notes |
|-----|---------|--------|-------|
| `chrome` | Google Chrome | Chromium | Default. Most users. |
| `firefox` | Mozilla Firefox | Gecko | Second most popular. Tests CSS differences. |
| `safari` | Apple Safari | WebKit | Tests macOS/iOS rendering. |

Install missing browsers (Playwright): `npx playwright install firefox webkit`

## Supported Devices

| Key | Device | Size | Type |
|-----|--------|------|------|
| `iphone-se` | iPhone SE | 375x667 | Mobile (smallest supported) |
| `iphone-14` | iPhone 14 | 390x844 | Mobile |
| `iphone-14-pro-max` | iPhone 14 Pro Max | 430x932 | Mobile (largest iPhone) |
| `pixel-7` | Pixel 7 | 412x915 | Mobile (Android) |
| `samsung-s23` | Samsung Galaxy S23 | 360x780 | Mobile (Android) |
| `ipad` | iPad | 768x1024 | Tablet |
| `ipad-pro` | iPad Pro 12.9" | 1024x1366 | Tablet (large) |
| `android-tablet` | Android Tablet | 800x1280 | Tablet (Android) |
| `laptop` | Laptop | 1366x768 | Desktop (common) |
| `desktop` | Desktop 1080p | 1920x1080 | Desktop (default) |
| `desktop-xl` | Desktop 1440p | 2560x1440 | Desktop (large) |

**Minimum test coverage:** Every feature MUST be tested on at least `iphone-se` (375px), `ipad` (768px), and `desktop` (1920px).

## Tips

- Use `await page.waitForTimeout(500)` after clicks to let dropdowns/animations settle
- Use `await page.waitForSelector('<selector>')` instead of arbitrary timeouts when possible
- Use `console.log()` generously — the output shows in the terminal during test runs
- Use `page.pause()` to freeze the test and inspect the page manually in the browser
- Take screenshots at key steps for visual evidence
- Always close the browser in a `finally` block to prevent orphaned processes
- Run with `--workers=1` when using `--headed` to watch one browser at a time
- For cross-browser matrix tests, increase timeout appropriately
- Mobile tests automatically set `isMobile: true` and `hasTouch: true` for realistic simulation
