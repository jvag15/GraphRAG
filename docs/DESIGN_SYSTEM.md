# docs/DESIGN_SYSTEM.md

> Version: 2026.06 Rev.2 Purpose: Canonical design specification for all
> GraphRAG Platform applications and AI coding agents.

# 1. Objective

This document is the single source of truth for implementing the GraphRAG
design language. AI agents must treat this document as authoritative.

# 2. Core Design Principles

-   Professional before decorative.
-   Editorial typography with modern UI.
-   Warm neutral palette.
-   Low visual noise.
-   Large whitespace.
-   Accessibility first.
-   Consistency over novelty.
-   Reuse components before creating new ones.

# 3. Brand Personality

Premium, calm, trustworthy, enterprise, audit-focused, minimal,
paper-inspired.

Avoid: - Neon colors - Heavy gradients - Excessive shadows - Random
border radii - Glassmorphism-heavy interfaces

# 4. Typography

## Display

Cormorant Garamond (`font-display`) - Hero headings - Product names -
Editorial titles

## UI

DM Sans (`font-sans`) Future migration: Hanken Grotesk

## Monospace

DM Mono (`font-mono`) Future migration: JetBrains Mono

Use for IDs, counts, metadata, keyboard shortcuts and technical
information.

# 5. Color System

Background: #faf8f5 Dark Background: #191919 Surface: #ffffff Dark
Surface: #1f1c19 Primary Text: #1c1410 Dark Text: #f0ebe3 Accent:
#9a3324 Accent Hover: #c9523c

Semantic: - Success #3d9a5c - Warning #c47b14 - Error #c93a2a - Info
#2b6cb0

# 6. Spacing

8-point grid only.

Scale: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80

Never invent arbitrary spacing.

# 7. Radius

4px badge 6px controls 8px small cards 12px standard cards 16px panels
9999px pills

# 8. Motion

Durations: 80ms 150ms 200ms 300ms

Curve: cubic-bezier(0.22,1,0.36,1)

Hover: translateY(-2px)

Never bounce.

# 9. Layout

Max width: 1280px Header: 56px Responsive Dark mode first-class

# 10. Components

All UI is composed from reusable components.

Header Toolbar Sidebar Search Cards Buttons Inputs Badges Dropdowns
Tables Toasts Skeletons Dialogs Tabs Accordions

# 11. Accessibility

Visible focus Keyboard navigation Reduced motion Readable contrast

# 12. Dark Mode

Warm charcoal. Never invert colors mechanically. Use dedicated dark
tokens.

# 13. AI Implementation Rules

-   Never invent colors.
-   Never invent spacing.
-   Never invent radii.
-   Never mix design systems.
-   Never inline CSS.
-   Always reuse existing components.
-   Always support dark mode.
-   Always use semantic HTML.

# 14. Technology

Tailwind CSS CSS Variables (--vv-\*) graphrag-design.css DM Sans DM Mono
Cormorant Garamond

# 15. Repository

design/ docs/DESIGN_SYSTEM.md variables.css components.css
tailwind.config.js tokens.json

# 19. Tailwind Configuration Map

The project overrides Tailwind's gray palette with the firm's warm
neutral palette.

Always use Tailwind utilities rather than raw hex values whenever
possible.

## Colors

Page Background - bg-gray-50 - dark:bg-\[#191919\]

Surface - bg-white - dark:bg-gray-800

Primary Text - text-gray-900 - dark:text-gray-100

Secondary Text - text-gray-500 - dark:text-gray-400

Borders - border-gray-200 - dark:border-gray-700

Accent - text-accent-500 - bg-accent-600 - hover:bg-accent-700

## Typography

Display - font-display

Interface - font-sans

Monospace - font-mono

# 20. Immutable Component Blueprints

## Primary Button

inline-flex items-center justify-center px-4 py-2 text-sm font-medium
transition-transform duration-200 ease-out rounded-md text-white
bg-accent-600 hover:bg-accent-700 hover:-translate-y-\[2px\]
focus:outline-none focus-visible:ring-2

## Ghost Button

inline-flex items-center justify-center px-4 py-2 text-sm font-medium
transition-colors duration-150 ease-out border border-gray-300
rounded-md text-gray-900 bg-transparent hover:bg-gray-50
dark:border-gray-700 dark:text-gray-100 dark:hover:bg-gray-800
focus:outline-none focus-visible:ring-2

## Standard Card

flex flex-col p-6 overflow-hidden bg-white border border-gray-200
rounded-xl shadow-sm transition-all duration-300
hover:-translate-y-\[2px\] hover:shadow-md dark:bg-gray-800
dark:border-gray-800

## Tool Card

flex items-center justify-between p-4 bg-white border border-gray-200
rounded-xl shadow-sm dark:bg-gray-800 dark:border-gray-800

## Text Input

w-full px-3 py-2 text-sm transition-colors duration-150 bg-transparent
border border-gray-300 rounded-md text-gray-900
placeholder:text-gray-400 focus:outline-none focus:border-accent-600
focus:ring-1 focus:ring-accent-600 dark:border-gray-700
dark:text-gray-100 dark:placeholder:text-gray-500

# 21. State Management Rules

Focus - Always use focus:outline-none focus-visible:ring-2

Hover - translateY(-2px) - increase elevation

Pressed - remove translation - reduce elevation

Disabled - opacity-50 - cursor-not-allowed - pointer-events-none

Loading - cursor-progress - pointer-events-none

Dark Mode - Use dark: variants only.

# 22. Component Inventory

Mandatory reusable components:

-   Header
-   Sidebar
-   Toolbar
-   Navigation Item
-   Search Bar
-   Command Palette
-   Tool Card
-   Metric Card
-   Primary Button
-   Secondary Button
-   Ghost Button
-   Icon Button
-   Input
-   Textarea
-   Select
-   Checkbox
-   Radio
-   Badge
-   Table
-   Pagination
-   Dropdown
-   Modal
-   Drawer
-   Toast
-   Skeleton
-   Tabs
-   Accordion
-   Empty State
-   Hero Banner

# 23. AI Hard Rules

-   Never create duplicate styling.
-   Never hardcode colors.
-   Never hardcode spacing.
-   Never exceed 1280px layout width.
-   Reuse before creating.
-   Extract repeated UI into components.
-   If a component exists, always use it.
-   Do not mix Bootstrap, Material UI, or unrelated design languages.
-   Use Tailwind utilities consistently.
-   Prefer CSS variables for custom values.

# 24. AI Decision Tree

1.  Check whether a reusable component already exists.
2.  If yes, reuse it.
3.  If not, compose from existing primitives.
4.  Create a new component only if composition is impossible.
5.  Register the new component in the design system.
6.  Never duplicate component styles.
