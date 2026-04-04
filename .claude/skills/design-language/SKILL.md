---
name: design-language
description: Cohesive design system guidelines for Negative Space — theme, typography, shape, icons, motion, layout, loading states, visual style, and tone. Use when building or modifying any UI.
---

# Design Language

When the `frontend-design` skill is also active, treat these guidelines as overrides — this project's design system takes precedence over generic aesthetic suggestions (e.g., use the coffee theme palette instead of inventing a new color scheme, use Nunito instead of picking a novel font).

All UI work must align with these decisions.

## Theme

- **DaisyUI theme:** `coffee` — set via `data-theme="coffee"` on the root `<html>` element
- **Single theme only** — no theme switching, no `dark:` variants needed
- Lean into the warm brown palette; use semantic colors (`primary`, `secondary`, `accent`, etc.) exclusively

## Typography

- **Headings:** Nunito (weights: 400-800) — rounded terminals echo the soft UI shape language
- **Body:** Nunito Sans (weights: 400-700) — same skeleton, optimized for readability at small sizes
- Loaded via Google Fonts in `src/app.html`
- Apply heading font with `font-heading` and body font with `font-body` (configured as `@theme` tokens in `app.css`)

## Shape & Radius

- **Fully rounded** — buttons, cards, inputs, badges all use maximum border radius (`rounded-full` for buttons/badges, generous `rounded-2xl`+ for cards and containers)
- Shape language should feel soft and approachable, never sharp or angular

## Icons

- **Heroicons** — use the outline variant by default, solid for emphasis/active states
- Install via `svelte-hero-icons` (`import { Icon, ArrowRight } from 'svelte-hero-icons'`) or inline SVG
- Keep icon sizes consistent: 16px inline, 20px in buttons, 24px standalone

## Motion & Transitions

- **Moderate** — purposeful transitions that guide attention, not decorative
- Page transitions: subtle fade or slide
- Hover states: smooth color/scale shifts (~150-200ms ease)
- Staggered reveals on page load for lists and card grids
- No gratuitous animation — every motion should serve navigation or feedback
- Prefer CSS transitions; reach for a motion library only for orchestrated sequences

## Layout

- **Top bar + sidebar** navigation pattern
- Content area should be comfortable reading width, not full-bleed
- Spacious — generous padding and margin; let the design breathe (the project is called "negative space" after all)
- **Responsive:** sidebar collapses to a hamburger menu on mobile; top bar persists at all breakpoints

## Loading States

- Use **skeleton loaders** (not spinners) for content loading — match the shape and size of the content they replace
- Use DaisyUI's `skeleton` class for consistency
- Skeletons should pulse subtly with the default DaisyUI animation

## Visual Style

- **Flat and clean** — no gradients, textures, noise, or heavy shadows
- Depth via subtle elevation (`shadow-sm`, `shadow-md`) sparingly, not layered effects
- Let the warm coffee palette and rounded shapes carry the visual identity

## Tone & Personality

- **Warm and playful** — friendly copy, approachable empty states, encouraging error messages
- Button labels should be conversational (e.g., "Let's go" over "Submit")
- Avoid cold, corporate, or overly formal language in the UI
