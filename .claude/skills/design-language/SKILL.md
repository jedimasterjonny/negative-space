# Design Language — Negative Space

Cohesive design system guidelines inspired by the daisyUI website aesthetic. Use when building or modifying any UI.

## Theme

- Use the daisyUI **`coffee`** theme exclusively — warm, grounded, developer-friendly
- Use semantic colors only (`primary`, `secondary`, `accent`, `base-100`, `neutral`, `error`, etc.) — never raw Tailwind color names (`red-500`, `gray-800`)
- No `dark:` variants — the single theme handles everything
- Always pair backgrounds with their `-content` counterpart (`bg-primary text-primary-content`)
- Use `base-100` / `base-200` / `base-300` to create depth through layered surfaces, not shadows

## Typography

- **Clean hierarchy**: large, bold headings contrasted with lighter body text
- Headings are statement-sized — generous `text-2xl` to `text-4xl` for page titles and heroes
- Body text at default (`text-base`) with comfortable line height
- Use font weight to establish hierarchy: `font-bold` for headings, `font-normal` for body
- Keep text concise — the design favours short, punchy copy over long paragraphs
- Use the Tailwind Typography plugin (`prose`) for long-form content blocks

## Shape

- **Generously rounded, not pill-shaped** — `rounded-lg` to `rounded-xl` for cards and containers
- Buttons and interactive fields use `rounded-lg` (not `rounded-full`)
- Badges and small indicators can use `rounded-full`
- Consistent radius across related elements — don't mix sharp and round in the same context
- Use daisyUI's built-in radius tokens (`--radius-box`, `--radius-field`, `--radius-selector`) when customising

## Spacing and Layout

- **Generous whitespace** — let content breathe with substantial padding and gaps
- Centred content with a max-width container (`max-w-6xl` or similar)
- Grid-based layouts for component showcases and card collections
- Use consistent spacing scale: `gap-4` to `gap-8` between sections, `p-4` to `p-8` inside containers
- Larger gaps between major page sections (`py-12` to `py-16`)
- Mobile-first responsive design

## Depth and Elevation

- **Minimal shadows** — prefer surface colour contrast over drop shadows
- Layer surfaces using `base-100` (page) > `base-200` (cards) > `base-300` (inset elements)
- Reserve shadows for floating elements only (dropdowns, modals, tooltips)
- Use `--depth: 0` in theme config for flat, modern feel
- Borders are thin and subtle (`border-base-300`) — used for separation, not emphasis

## Interactive Elements

- **Buttons**: daisyUI button classes with semantic variants (`btn-primary`, `btn-secondary`, `btn-ghost`)
- Subtle hover transitions — colour shifts, not dramatic scale or shadow changes
- Smooth transitions: `transition-colors duration-200` for interactive state changes
- Focus rings for accessibility — use daisyUI's built-in focus styles
- Active states use slight darkening, not depression effects

## Icons

- **Outlined style** — stroke-based SVG icons, not filled
- Use Heroicons (outline variant) as the primary icon set
- Icons inherit text colour — size at `w-5 h-5` for inline, `w-6 h-6` for standalone
- Rounded line caps and joins for warmth
- Don't overuse icons — text labels are preferred where space allows

## Navigation

- **Sidebar navigation** with collapsible sections for complex apps
- Top navbar for simple page-level navigation
- Category-based grouping with clear section headers
- Active states use `bg-base-200` or `bg-primary text-primary-content`
- Support keyboard navigation (⌘K search pattern for power users)

## Cards and Containers

- `card` component with `bg-base-200` on a `bg-base-100` page
- Internal padding `p-6` to `p-8` — generous, not cramped
- Rounded corners `rounded-xl`
- No heavy borders — surface colour difference provides separation
- Card titles bold and prominent, descriptions in `text-base-content/70`

## Hero Sections

- **Typography-led** — large bold statement text, no hero images
- Centred alignment with generous vertical padding
- One or two CTA buttons below the headline
- Subtitle/description in lighter weight below the main heading
- Code snippets or install commands can feature prominently

## Motion

- Keep animations subtle and functional — no decorative animation
- `transition-all duration-200 ease-in-out` as the default transition
- Theme switches use smooth CSS variable transitions
- Loading states use daisyUI's `loading` component (spinner/dots)
- No page transition animations unless they serve navigation clarity

## Tone and Copy

- **Developer-friendly and approachable** — technical but not dry
- Conversational button labels ("Get started", "See components")
- Short, punchy headlines that lead with the benefit
- Empty states should be helpful, not just "No data"
- Error messages should be actionable, not just descriptive
- Avoid corporate jargon — be direct and human

## Patterns to Avoid

- Hero images or stock photography — use text and colour instead
- Raw Tailwind colours — always use semantic daisyUI colours
- Heavy shadows or glassmorphism effects
- Fully sharp corners (`rounded-none`) on interactive elements
- Filled/solid icon styles — use outline icons
- Dense, cramped layouts — always err on the side of more whitespace
- Multiple themes or dark mode toggles — stick to `coffee` theme only
