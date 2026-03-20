# Design System

Visual language, color palette, typography, spacing, and formatting rules for the Warren Cashett terminal.

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md)

## Design Philosophy

Bloomberg-inspired: **data-dense, dark, professional**. Every pixel earns its place by showing useful information. Whitespace is used for grouping, not decoration. The terminal should feel like a financial cockpit — everything you need visible at a glance.

## Color Palette

### Base Colors

| Token | Hex | Usage |
|-------|-----|-------|
| `bg-primary` | `#0A0E17` | Main background (near-black navy) |
| `bg-secondary` | `#111827` | Card/panel background |
| `bg-tertiary` | `#1F2937` | Elevated surfaces, hover states |
| `bg-hover` | `#374151` | Interactive element hover |
| `border-default` | `#1F2937` | Default borders |
| `border-subtle` | `#111827` | Subtle separators |

### Text Colors

| Token | Hex | Usage |
|-------|-----|-------|
| `text-primary` | `#F9FAFB` | Primary text, numbers, headings |
| `text-secondary` | `#9CA3AF` | Labels, descriptions, secondary info |
| `text-tertiary` | `#6B7280` | Disabled text, timestamps, footnotes |
| `text-inverse` | `#0A0E17` | Text on light backgrounds (rare) |

### Semantic Colors

| Token | Hex | Usage |
|-------|-----|-------|
| `positive` | `#22C55E` | Gains, positive returns, upward movement |
| `positive-muted` | `#166534` | Positive background tint |
| `negative` | `#EF4444` | Losses, negative returns, downward movement |
| `negative-muted` | `#7F1D1D` | Negative background tint |
| `warning` | `#F59E0B` | Warnings, alerts, approaching limits |
| `warning-muted` | `#78350F` | Warning background tint |
| `info` | `#3B82F6` | Informational highlights, links, active states |
| `info-muted` | `#1E3A5F` | Info background tint |
| `accent` | `#8B5CF6` | Primary accent (purple — brand color) |

### Asset Class Colors (for charts and allocation views)

| Asset Class | Hex | Token |
|-------------|-----|-------|
| Stocks | `#3B82F6` | `asset-stocks` |
| ETFs | `#8B5CF6` | `asset-etfs` |
| Bonds | `#22D3EE` | `asset-bonds` |
| Crypto | `#F59E0B` | `asset-crypto` |
| Cash | `#6B7280` | `asset-cash` |

## Typography

### Font Families

| Usage | Font | Fallback |
|-------|------|----------|
| Numbers, data, code | `JetBrains Mono` | `ui-monospace, monospace` |
| Labels, headings, UI text | `Inter` | `ui-sans-serif, system-ui, sans-serif` |

### Font Sizes

| Token | Size | Line Height | Usage |
|-------|------|-------------|-------|
| `text-3xl` | 30px | 36px | Page titles |
| `text-2xl` | 24px | 32px | Section headings, hero metrics |
| `text-xl` | 20px | 28px | Card titles, large numbers |
| `text-lg` | 18px | 28px | Sub-headings |
| `text-base` | 14px | 20px | Default body text, table cells |
| `text-sm` | 12px | 16px | Labels, captions, secondary info |
| `text-xs` | 10px | 14px | Timestamps, footnotes, badge text |

**Note**: Default `text-base` is 14px (not 16px) — denser than typical web. This is intentional for the terminal aesthetic.

### Font Weights

| Token | Weight | Usage |
|-------|--------|-------|
| `font-normal` | 400 | Body text, descriptions |
| `font-medium` | 500 | Labels, table headers |
| `font-semibold` | 600 | Card titles, important numbers |
| `font-bold` | 700 | Hero metrics, page titles |

## Spacing

Base unit: **4px**. All spacing is a multiple of 4px.

| Token | Value | Usage |
|-------|-------|-------|
| `space-1` | 4px | Tight inline spacing (icon-to-text) |
| `space-2` | 8px | Compact element spacing (within cards) |
| `space-3` | 12px | Default padding inside cards |
| `space-4` | 16px | Standard gap between elements |
| `space-6` | 24px | Gap between cards/sections |
| `space-8` | 32px | Page padding, major section breaks |

## Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| `rounded-sm` | 4px | Buttons, badges, inputs |
| `rounded-md` | 6px | Cards, panels |
| `rounded-lg` | 8px | Modals, dialogs |
| `rounded-full` | 9999px | Circular indicators, avatars |

## Number Formatting

### Currency

| Scenario | Format | Example |
|----------|--------|---------|
| EUR amounts | `€{n}` with 2 decimals | `€12,345.67` |
| USD amounts | `${n}` with 2 decimals | `$1,234.56` |
| Large amounts (≥1M) | Abbreviated | `€1.23M` |
| Large amounts (≥1B) | Abbreviated | `€4.56B` |
| Negative amounts | Minus prefix, red color | `-€1,234.56` |
| Zero | Shown, dimmed (text-tertiary) | `€0.00` |

### Percentages

| Scenario | Format | Example |
|----------|--------|---------|
| Returns, changes | Sign prefix, 2 decimals | `+12.34%`, `-5.67%` |
| Allocation weights | No sign, 1 decimal | `42.5%` |
| Small values | 2 decimals minimum | `0.04%` |

### Quantities

| Scenario | Format | Example |
|----------|--------|---------|
| Stock shares | Integer or 2 decimals if fractional | `150` or `12.50` |
| Crypto amounts | Up to 8 significant decimals | `0.00345678` |
| Large quantities | Comma separated | `1,500` |

### Dates

| Context | Format | Example |
|---------|--------|---------|
| Full date | `DD MMM YYYY` | `19 Mar 2026` |
| Short date | `DD/MM` | `19/03` |
| With time | `DD MMM YYYY HH:mm` | `19 Mar 2026 14:30` |
| Relative (< 24h) | Relative | `2 hours ago` |
| Year headers | `YYYY` | `2026` |

### Gain/Loss Color Rules

- **Positive values**: `positive` color (#22C55E)
- **Negative values**: `negative` color (#EF4444)
- **Zero**: `text-tertiary` color (#6B7280)
- **Neutral data** (not a gain/loss): `text-primary` color (#F9FAFB)
- Apply to: return percentages, P&L amounts, price changes

## Shadows

Minimal shadow usage — depth conveyed primarily through background color differences.

| Token | Value | Usage |
|-------|-------|-------|
| `shadow-sm` | `0 1px 2px rgba(0,0,0,0.3)` | Dropdowns, tooltips |
| `shadow-md` | `0 4px 12px rgba(0,0,0,0.4)` | Modals, command palette |

## Transitions

| Property | Duration | Easing |
|----------|----------|--------|
| Color, background | 150ms | ease-in-out |
| Transform, opacity | 200ms | ease-out |
| Layout (height, width) | 300ms | ease-in-out |

## Responsive Behavior

- **Minimum viewport**: 1280 × 720px
- **Target viewport**: 1920 × 1080px (full HD)
- **No mobile support** — this is a desktop terminal application
- Sidebar collapses to icon-only at viewports < 1440px wide
- Tables scroll horizontally if columns exceed available width

## TailwindCSS Configuration

These tokens map to a custom Tailwind theme extending the default config:

```
theme: {
  extend: {
    colors: {
      terminal: {
        bg: { primary, secondary, tertiary, hover },
        border: { default, subtle },
        text: { primary, secondary, tertiary },
        positive, negative, warning, info, accent,
        asset: { stocks, etfs, bonds, crypto, cash }
      }
    },
    fontFamily: {
      mono: ['JetBrains Mono', ...monospace],
      sans: ['Inter', ...sans-serif]
    },
    fontSize: { /* custom scale above */ }
  }
}
```

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
