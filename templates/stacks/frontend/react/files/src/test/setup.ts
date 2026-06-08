// Test setup: jest-dom matchers + DOM cleanup between tests.
//
// React Testing Library's automatic cleanup only runs when Vitest globals are enabled. This project
// keeps globals off (tests import { describe, it, expect } explicitly), so we register cleanup
// ourselves — without it, mounted components accumulate across tests and queries find duplicates.
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

import '@testing-library/jest-dom/vitest'

afterEach(() => {
  cleanup()
})
