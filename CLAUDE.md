# CLAUDE.md

## Project Overview

Negative Space is a SvelteKit application using Svelte 5 (runes mode enforced) and TypeScript.

## Commands

- `bun install` - install dependencies
- `bun run dev` - start dev server
- `bun run build` - production build
- `bun run check` - typecheck with svelte-check
- `bun run lint` - check formatting (Prettier) and linting (ESLint)
- `bun run lint:fix` - auto-fix formatting and lint issues

## Code Style

### Linting (enforced by ESLint)

- Import ordering is enforced by `eslint-plugin-perfectionist` using natural alphabetical sorting
- Separate library imports from local imports with a blank line
- Library imports come first, local imports last
- Do not manually reorder imports — run `bun run lint:fix` if import order fails
- Do not add `eslint-disable` comments unless absolutely necessary; always include a justification

### TypeScript

- Use `lang="ts"` on all Svelte script tags
- Prefer `type` for type aliases and `interface` for object shapes that may be extended
- Use `verbatimModuleSyntax` — always use `import type` for type-only imports
- Type `$props` with an `interface` and destructure: `let { prop1, prop2 }: Props = $props()`
- For generic components, use the `generics` attribute: `<script lang="ts" generics="T extends ...">`
- When wrapping native elements, use types from `svelte/elements` (e.g. `HTMLButtonAttributes`)
- Only type-only TS features work in Svelte components — no enums, no constructor parameter modifiers
- Use the `Component` type from `svelte`, not the legacy `SvelteComponent`

### Svelte 5 Patterns

- Runes mode is enforced project-wide — do not use legacy Svelte 4 patterns
- Use `$props()` destructuring for component props: `let { prop1, prop2 } = $props()`
- Treat props as potentially changing — derive values from props with `$derived`, not plain assignment
- Use `{@render children()}` for slot content, not `<slot />`
- Use `{#snippet ...}` and `{@render ...}` instead of `<slot>`, `$$slots`, or `<svelte:fragment>`

#### Reactivity

- Only use `$state` for variables that are actually reactive (read by `$derived`, `$effect`, or templates)
- Use `$state.raw` for large objects that are only reassigned, not mutated (e.g. API responses)
- Use `$derived` (not `$effect`) to compute values from state; use `$derived.by` for complex expressions
- `$effect` is an escape hatch — avoid updating state inside effects. Prefer:
  - `{@attach ...}` for syncing with external libraries (e.g. D3, Tippy.js)
  - Event handlers or function bindings for responding to user interaction
  - `$inspect` for debugging, `$inspect.trace` for tracing reactivity issues

#### Modern API preferences

- Use `onclick={...}` instead of `on:click={...}`
- Use `{@attach ...}` instead of `use:action`
- Use `<DynamicComponent>` instead of `<svelte:component this={DynamicComponent}>`
- Use clsx-style arrays/objects in `class` attributes instead of the `class:` directive
- Use `createContext` for type-safe context instead of `setContext`/`getContext`

#### State sharing

- For shared reactive state, prefer context (`createContext`) over module-level `$state` in `.svelte.ts` files — module-level state can leak between users during SSR
- Module-level `$state` in `.svelte.ts` files is fine for client-only state that is never mutated during SSR

#### Templates

- Prefer keyed `{#each}` blocks — the key must uniquely identify the item (never use the index)
- Avoid destructuring in `{#each}` if you need to mutate the item (e.g. `bind:value={item.count}`)
- Use CSS custom properties (`--prop`) for styling child components rather than `:global`

### Svelte MCP Server

A Svelte MCP server is configured for this project, providing access to comprehensive Svelte 5 and SvelteKit documentation. Use its tools as follows:

- **`list-sections`** — Call this first at the start of a chat to discover available documentation sections. Each section includes titles, use cases, and paths.
- **`get-documentation`** — After listing sections, fetch all sections relevant to the current task. Analyze the `use_cases` field to determine which sections to retrieve.
- **`svelte-autofixer`** — Run this on all Svelte code before finalizing it. Keep calling it until no issues or suggestions are returned.
- **`playground-link`** — Only use after asking the user if they want a playground link, and never if code was written directly to project files.

### Tailwind CSS 4

- Tailwind v4 with Vite plugin (`@tailwindcss/vite`) — not PostCSS
- No `tailwind.config.js` — all configuration lives in `src/app.css` using `@theme` directive
- Reference theme tokens with CSS variables (`var(--color-red-500)`), **not** the legacy `theme()` function
- Define custom utilities with `@utility`, custom variants with `@custom-variant`, sources with `@source`
- `prettier-plugin-tailwindcss` sorts utility classes automatically — do not manually reorder them
- Prefer Tailwind utility classes in markup over custom CSS
- Use Svelte's scoped `<style>` block only for styles that cannot be expressed as utilities

### DaisyUI 5

UI components via daisyUI 5 (`@plugin "daisyui"` in `src/app.css`).

- Use daisyUI semantic colors (`primary`, `base-100`, `error`, etc.) instead of Tailwind colors (`red-500`, `gray-800`) — semantic colors adapt to themes automatically, no `dark:` prefix needed
- Pair backgrounds with their `*-content` counterpart (e.g. `bg-primary text-primary-content`)
- Avoid Tailwind color names for text — `text-gray-800` on `bg-base-100` is unreadable on dark themes
- Use `!` suffix on utilities only as a last resort for specificity (e.g. `btn bg-red-500!`)
- Component reference: https://daisyui.com/llms.txt

## Design Language

Full design system guidelines are in `.claude/skills/design-language/`. Key rules:

- **DaisyUI `coffee` theme only** — use semantic colors exclusively, never raw Tailwind color names, no `dark:` variants
- **Generously rounded shapes** — `rounded-lg` to `rounded-xl` for cards/containers, `rounded-lg` for buttons/fields, `rounded-full` only for badges
- **Minimal depth** — layer surfaces with `base-100`/`base-200`/`base-300` instead of shadows
- **Typography-led** — large bold headings, no hero images, text and colour carry the design
- **Outlined icons** — Heroicons outline variant, stroke-based, inheriting text colour
- **Generous whitespace** — generous padding and gaps, centred max-width content
- **Developer-friendly tone** — conversational, approachable, direct copy

### Component Structure

Order sections in Svelte files as:

1. `<script lang="ts">` (props, state, logic)
2. Markup (HTML template)
3. `<style>` (scoped styles)

## Code Quality

This project enforces pedantic code review standards. Every change must be surgical and intentional.

### Clean Diffs

- Every commit must have a clean diff — only change lines directly related to the purpose of that commit
- Do not sneak in unrelated formatting fixes, refactors, renames, or import reordering in the same commit
- If you notice something unrelated that needs fixing, make it a separate commit
- No dead code, commented-out code, or leftover debug statements (e.g., `console.log`) in diffs
- Do not add, remove, or reorder imports unless the commit requires it
- Avoid unnecessary whitespace-only changes

### Every Commit Must Pass

Before creating any commit, verify:

1. `bun run lint` passes (Prettier + ESLint)
2. `bun run check` passes (svelte-check / TypeScript)
3. `bun run test` passes (unit + E2E)
4. `bun run build` succeeds

Do not commit code that breaks the build, fails type checking, or has lint errors. Every commit in history must be independently buildable and clean.

## Git & Workflow

### Commit Messages

Use Conventional Commits format: `type(scope): description`

- Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `build`, `ci`
- Lowercase description, no period at end
- Scope is optional but encouraged for clarity (e.g., `fix(auth): handle expired tokens`)

### Pre-commit

Husky runs `bun run lint` on every commit. All code must pass Prettier and ESLint checks before committing.

### Dependencies

- Package manager: Bun
- Renovate manages dependency updates — do not manually bump dependencies
- Node >= 20 required (`engine-strict=true`)

## Testing

- Unit/integration tests: Vitest
- E2E tests: Playwright
- `bun run test:unit` — run Vitest in watch mode
- `bun run test:e2e` — run Playwright E2E tests
- `bun run test` — run all tests once (unit + E2E)

### File naming and placement

- Unit/component tests: `*.test.ts` or `*.svelte.test.ts` — place alongside source files
- E2E tests: `*.spec.ts` — place in `tests/` directory

### Writing tests

- Every test must contain at least one assertion (`requireAssertions: true`)
- Tests that use runes (`$state`, `$derived`, `$effect`) **must** use the `.svelte.test.ts` extension so Vitest processes them correctly
- Add `/// <reference types="vitest/browser" />` in browser test files for correct type hints
- Before writing a component test, consider whether the logic can be extracted and tested in isolation without the component overhead
- For testing components with two-way bindings, context, or snippets, create a `.test.svelte` wrapper component
- Use `flushSync` from `svelte` after state mutations to synchronously flush updates before asserting
- Wrap tests that exercise `$effect`-based code in `$effect.root()` and call the returned cleanup function

### Component testing (vitest-browser-svelte)

- Use `render` from `vitest-browser-svelte` to mount components: `const screen = await render(Component, { props })`
- Always use `expect.element()` with locators (not bare `expect()`) — it has built-in retry-ability that reduces flakiness from async rendering
- Prefer accessible locators: `getByRole`, `getByText`, `getByLabelText` over `getByTestId`

### E2E testing (Playwright)

- Prefer user-facing locators in this priority order:
  1. `page.getByRole()` — most resilient, based on accessibility roles (e.g., `getByRole('button', { name: 'Submit' })`)
  2. `page.getByText()`, `page.getByLabel()`, `page.getByPlaceholder()` — based on visible text/labels
  3. `page.getByTestId()` — use only when accessible locators are not practical
  4. `page.locator('css-selector')` — last resort; avoid CSS/XPath selectors as they are brittle
- Use web-first assertions (`await expect(locator).toBeVisible()`) — they auto-retry until the condition is met, avoiding flaky tests
- Do not add manual waits or `page.waitForTimeout()` — rely on Playwright's built-in auto-waiting
- Each test gets a fresh browser context — do not rely on state from previous tests
