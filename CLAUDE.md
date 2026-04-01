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

### Formatting (enforced by Prettier)

- Tabs for indentation
- Single quotes
- No trailing commas
- 100 character line width

### Linting (enforced by ESLint)

- Import ordering is enforced by `eslint-plugin-perfectionist` using natural alphabetical sorting
- Separate library imports from local imports with a blank line
- Library imports come first, local imports last
- Do not manually reorder imports — run `bun run lint:fix` if import order fails
- Do not add `eslint-disable` comments unless absolutely necessary; always include a justification

#### typescript-eslint

- `@typescript-eslint/no-explicit-any` — avoid `any`; use `unknown` and narrow the type
- `@typescript-eslint/no-unused-vars` — do not leave unused variables or imports (prefix intentionally unused params with `_`)

#### eslint-plugin-svelte

- `svelte/no-dom-manipulating` — do not directly manipulate the DOM; use `{@attach}` for external library integration
- `svelte/no-object-in-text-mustaches` — do not pass objects directly into `{...}` text interpolation
- `svelte/no-top-level-browser-globals` — never reference `window`, `document`, or other browser globals at the top level; guard with `browser` from `$app/environment` or use `$effect`
- `svelte/prefer-svelte-reactivity` — use Svelte's reactive `SvelteMap`/`SvelteSet` instead of mutable built-in `Map`/`Set`
- `svelte/require-event-prefix` — event callback props must start with `on` (e.g., `onclick`, `onchange`)
- `svelte/valid-each-key` — `{#each}` keys must reference variables defined within the each block

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

This project uses Tailwind CSS v4 with the Vite plugin (`@tailwindcss/vite`) — not PostCSS.

#### CSS-first configuration

- There is no `tailwind.config.js` — all configuration lives in `src/app.css`
- Import Tailwind with `@import 'tailwindcss'` at the top of `src/app.css`
- Define design tokens (colors, fonts, breakpoints, spacing, etc.) with the `@theme` directive using CSS variables:

```css
@import 'tailwindcss';

@theme {
	--font-display: 'Satoshi', 'sans-serif';
	--color-brand-500: oklch(0.84 0.18 117.33);
	--breakpoint-3xl: 1920px;
}
```

#### Theme variables in custom CSS

- Reference theme tokens with CSS variables (`var(--color-red-500)`), **not** the legacy `theme()` function
- Place component-level custom styles in `@layer components { ... }`

#### Custom utilities, variants, and sources

- Define custom utilities with `@utility` — they automatically work with all Tailwind variants (hover, focus, responsive, etc.):

```css
@utility content-auto {
	content-visibility: auto;
}
```

- Apply Tailwind variants inside custom CSS with `@variant`:

```css
.my-element {
	background: white;
	@variant dark {
		background: black;
	}
}
```

- Define custom variants with `@custom-variant` (e.g., class-based dark mode):

```css
@custom-variant dark (&:where(.dark, .dark *));
```

- Use `@source` to include paths not covered by automatic content detection:

```css
@source '../node_modules/@my-company/ui-lib';
```

#### Class sorting

- `prettier-plugin-tailwindcss` automatically sorts utility classes — do not manually reorder them
- The plugin is configured with `tailwindStylesheet: './src/app.css'` in `.prettierrc`

#### Usage conventions

- Prefer Tailwind utility classes in markup over custom CSS
- Use Tailwind's responsive (`sm:`, `md:`, `lg:`, etc.) and state (`hover:`, `focus:`, `dark:`, etc.) variants — do not write manual media queries or pseudo-selectors when a variant exists
- Use Svelte's scoped `<style>` block only for styles that cannot be expressed as utilities
- When using `@apply` in scoped styles, keep it minimal — prefer utility classes in the template

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
3. `bun run build` succeeds

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
- Renovate manages automated dependency updates
- Node >= 20 required (`engine-strict=true`)

## Testing

- Unit/integration tests: Vitest
- E2E tests: Playwright
- Place unit tests alongside source files as `*.test.ts` or `*.test.svelte.ts`
- Place E2E tests in `tests/` directory as `*.spec.ts`
