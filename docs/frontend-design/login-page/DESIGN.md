---
name: CleanOps Institutional
colors:
  surface: '#edfdf3'
  surface-dim: '#ceded4'
  surface-bright: '#edfdf3'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#e7f7ed'
  surface-container: '#e2f2e8'
  surface-container-high: '#dcece2'
  surface-container-highest: '#d6e6dc'
  on-surface: '#111e18'
  on-surface-variant: '#3f4942'
  inverse-surface: '#25332d'
  inverse-on-surface: '#e4f5eb'
  outline: '#6f7a72'
  outline-variant: '#bfc9c0'
  surface-tint: '#186b47'
  primary: '#00452a'
  on-primary: '#ffffff'
  primary-container: '#005f3c'
  on-primary-container: '#88d7aa'
  inverse-primary: '#88d7aa'
  secondary: '#006b56'
  on-secondary: '#ffffff'
  secondary-container: '#7af5d2'
  on-secondary-container: '#00705a'
  tertiary: '#00452d'
  on-tertiary: '#ffffff'
  tertiary-container: '#005f40'
  on-tertiary-container: '#4edea3'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#a4f3c5'
  primary-fixed-dim: '#88d7aa'
  on-primary-fixed: '#002112'
  on-primary-fixed-variant: '#005233'
  secondary-fixed: '#7df8d4'
  secondary-fixed-dim: '#5edbb9'
  on-secondary-fixed: '#002018'
  on-secondary-fixed-variant: '#005140'
  tertiary-fixed: '#6ffbbe'
  tertiary-fixed-dim: '#4edea3'
  on-tertiary-fixed: '#002113'
  on-tertiary-fixed-variant: '#005236'
  background: '#edfdf3'
  on-background: '#111e18'
  surface-variant: '#d6e6dc'
typography:
  eyebrow:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
  headline-xl:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  container-padding: 32px
  gutter: 24px
  section-gap: 48px
  component-gap: 16px
---

## Brand & Style

The design system is engineered for high-stakes facility management, where clarity and calm are paramount. The brand personality is rooted in environmental stewardship and operational precision, projecting an image of a premium, modern utility. 

The aesthetic combines **Minimalism** with subtle **Glassmorphism** to evoke a sense of transparency and high-end technology. It leverages heavy whitespace and a restricted botanical palette to reduce cognitive load for operators managing complex data. The result is a professional environment that feels trustworthy and impeccably organized.

## Colors

This design system utilizes a sophisticated green-monochromatic scheme to reinforce the "Clean" aspect of the brand. 

- **Primary & Secondary:** Dark Emerald (#005f3c) is reserved for core branding and primary actions. The **Bright Teal** (#26b090) secondary color is used for secondary actions and navigational highlights, providing a more vibrant and energetic secondary tier compared to the previous deep tones.
- **Accent:** Emerald Accent (#10b981) is used sparingly for success states, active indicators, and calls to action that require immediate attention.
- **Backgrounds:** The Soft Off-White provides a low-strain canvas, while the Muted Sage (#66756d) ensures that secondary text information remains legible without competing with primary headings.
- **Borders:** A polished, low-contrast border color is used to define structure without creating visual noise.

## Typography

The typography strategy focuses on a rigorous hierarchy to guide the user through dense facility data. **Inter** is utilized for its exceptional legibility in technical interfaces.

The "Eyebrow" style is a critical component of this system, used above large titles to provide immediate context or category classification. Large, bold headlines create clear entry points for each page, while tight letter spacing on larger sizes maintains a polished, "SaaS-premium" feel.

## Layout & Spacing

The layout follows a **Fixed Grid** philosophy within a fluid container, ensuring that data-heavy consoles remain readable across ultra-wide monitors. A 12-column system is used for dashboard layouts, with generous 24px gutters.

The spacing rhythm is expansive, favoring "breathability" over density. Large 48px gaps separate major functional sections, while consistent 16px internal padding is used for cards and modules to maintain a clean, uncluttered appearance.

## Elevation & Depth

Depth in this design system is achieved through a combination of **Tonal Layering** and **Subtle Glassmorphism**. 

1.  **Level 0 (Base):** The Soft Off-White background.
2.  **Level 1 (Cards):** Solid white surfaces with a 1px border and a very soft, diffused ambient shadow (8% opacity using the Neutral palette).
3.  **Level 2 (Overlays/Navigation):** Semi-transparent white (bg-white/80) with a 12px backdrop blur. This glass effect is used for sticky headers and sidebars to maintain a sense of environmental awareness.
4.  **Level 3 (Modals):** High-diffusion shadows with sharp 1px borders to separate critical interactions from the background.

## Shapes

The shape language is refined and approachable. A **Rounded (2)** setting is applied across the system to soften the "industrial" nature of facility management. 

Buttons and input fields utilize a 0.5rem radius, while large dashboard cards and containers use 1rem (rounded-lg) to create a distinct modular look. This consistency in curvature ensures that even the most complex data visualizations feel integrated into the premium SaaS aesthetic.

## Components

### Buttons
Primary buttons use the **Dark Emerald** background with white text, featuring a subtle inner-glow on hover. Secondary buttons utilize the **Bright Teal** background or outline to provide clear visual distinction from primary actions.

### Cards
Following the "shadcn" style: white backgrounds, 1px borders, and 1rem corner radius. Headers within cards should use the **Eyebrow** typography for section titles.

### Input Fields
Inputs feature a subtle background tint and transition to a 2px **Emerald Accent** border on focus.

### Chips & Badges
Used for facility status (e.g., "Active," "Maintenance," "Alert"). These use a high-chroma background of the **Emerald Accent** or **Bright Teal** at 10% opacity with full-saturation text for readability.

### Side Navigation
The primary navigation resides in a glassmorphic sidebar on the left, using **Dark Emerald** for active icon states and the **Muted Sage** or **Bright Teal** for hover and inactive labels.

### Data Tables
Tables should avoid heavy row striping. Instead, use thin 1px horizontal dividers and generous vertical cell padding (16px) to maintain the "large spacing" vibe.