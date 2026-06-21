# vitest-rtl-msw-patterns

**Generic, reusable skill for frontend testing with Vitest, React Testing Library, and MSW.**

This skill encodes production patterns for:
- **Vitest** test runner configuration with coverage-v8
- **React Testing Library** component testing (render, screen, userEvent)
- **MSW v2** API mocking with http.get/post and HttpResponse
- **Contract testing** where frontend Zod schemas mirror backend Pydantic models, validated against generated fixtures (full/minimal/meta)

## What it covers

1. **Vitest configuration**: globals, jsdom environment, setupFiles, coverage thresholds
2. **Test setup**: jsdom API stubs (matchMedia, IntersectionObserver, localStorage, etc.)
3. **MSW v2 request mocking**: setupServer, handlers, error scenarios, per-test overrides
4. **React Testing Library**: accessible queries, user interactions, async assertions
5. **Contract testing**: strictDeep helper for Zod, fixture-driven validation, metadata assertions
6. **Test scripts**: watch mode, CI mode, coverage, UI runner

## Origin

This skill derives from **real production frontend services** (multiple React + TypeScript codebases with Vite, Vitest, MSW, and Zod-Pydantic contract tests). All examples and patterns are genericized for public distribution.

## Usage

This is a **Claude Skill** for use in Claude Code. It provides guidance on setting up and maintaining frontend test infrastructure with modern tooling (Vitest, RTL, MSW v2) and contract testing practices.

See `SKILL.md` for detailed conventions, examples, and anti-patterns.
