---
name: X Draft Desk
description: A quiet black workspace for watching accounts and shaping drafts.
colors:
  bg: "#080808"
  surface: "#111"
  raised: "#191919"
  text: "#ededed"
  muted: "#969696"
  line: "#282828"
  green: "#92d8a3"
  error: "#ffaca6"
  white: "#ffffff"
  button-ink: "#0a0a0a"
  control-hover: "#1b1b1b"
  focus: "#ddd"
  attention: "#e8ae7e"
typography:
  title:
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "25px"
    fontWeight: 500
    lineHeight: 1.5
    letterSpacing: "-0.03em"
  status:
    fontSize: "20px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "-0.025em"
  body:
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "16px"
    lineHeight: 1.5
  source:
    fontSize: "18px"
    lineHeight: 1.65
  draft:
    fontSize: "17px"
    lineHeight: 1.7
  label:
    fontSize: "14px"
  metadata:
    fontSize: "13px"
  compact:
    fontSize: "12px"
rounded:
  control: "8px"
  search: "10px"
  surface: "12px"
  chip: "24px"
  circle: "50%"
spacing:
  compact: "8px"
  small: "12px"
  medium: "16px"
  group: "20px"
  section: "28px"
  gutter: "36px"
components:
  button-primary:
    backgroundColor: "{colors.text}"
    textColor: "{colors.button-ink}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
  button-text:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    padding: "8px 0"
  button-icon:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    padding: "9px"
    width: "40px"
  field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "11px 12px"
  watch-chip:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.chip}"
    padding: "5px 8px 5px 6px"
  search-result:
    backgroundColor: "{colors.raised}"
    rounded: "{rounded.surface}"
    padding: "18px"
    width: "330px"
  footer:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.muted}"
---

# Design System: X Draft Desk

## Overview

**Creative North Star: "The Quiet Monitoring Desk"**

A quiet black workspace for watching accounts and responding when a post arrives. Neutral surfaces, compact sans-serif controls, and generous unoccupied space keep monitoring calm and useful. Color appears only when it communicates operational state.

This system records the user-approved black one-page direction and the implemented interface. It supersedes the earlier green-and-ivory editorial direction. The desktop and mobile empty states are evidenced by the current review captures; there is no decorative imagery or visual-comp dependency.

**Key Characteristics:**
- Neutral black field with restrained gray hierarchy.
- Account chips above the workspace; persistent status and actions below.
- Quiet centered monitoring state and same-page settings revealed on demand.
- Flat surfaces, thin separators, and explicit operational status.

## Colors

The palette is neutral black and gray, with pale neutral actions. The frontmatter values are extracted from the current stylesheet and are normative.

### Primary

- **Soft White:** primary action surfaces and readable working text.
- **Bright White:** hovered actions, active draft tabs, and input carets.

### Neutral

- **Black Field:** page, top strip, and fixed footer.
- **Near-Black Surface:** account chips and form fields.
- **Raised Charcoal:** search results and selected post options.
- **Quiet Gray:** secondary text, footer controls, and metadata.
- **Charcoal Divider:** region separators and chip borders.
- **Hover Charcoal:** supporting control hover surfaces.
- **Focus Silver:** visible keyboard focus.
- **Button Ink:** text on pale primary buttons.

The green, error, and attention tokens are semantic exceptions: running/completed state, error copy, and monitoring needing attention. They are not brand accents.

**The Neutral Field Rule.** Keep navigation and primary actions neutral; reserve chromatic color for operational status.

## Typography

The UI stack is Inter followed by platform sans-serif fallbacks. No local or remote font asset is loaded; platform fallback rendering is expected. There is no decorative display or serif role.

Titles use the title token. The centered monitoring message uses the lighter status role, reduced to (19px) on mobile. Source copy and draft editing have their own generous line heights. Labels use the compact label role; footer and secondary details use metadata, reduced to (12px) in the mobile footer. Reply counts and progress numbers use tabular numerals.

**The Quiet State Rule.** Let empty space carry the monitoring state; add explanatory text only when the user needs to act.

## Layout

The single page has a horizontal account strip (86px tall), an open main field, and a fixed footer (minimum 76px tall). Desktop top and bottom gutters follow the gutter token. Watched-account chips scroll horizontally inside available space. The plus action remains on the right and expands exact-handle search within the top strip; results appear directly below it.

The empty state is centered inside a viewport-relative field, with minimum height `calc(100svh - 196px)`. The main element reserves bottom space (110px) for the footer. A populated inbox is a centered column (maximum 740px); its post selector scrolls horizontally above the source and editor. Same-page settings replace the main content while open, using a wider region (maximum 920px) and two columns separated by (54px).

At widths up to (800px), the top strip becomes (76px) tall with (20px) gutters and the brand word is hidden. Account chips tighten; the expanded search anchors inside the top strip at its right edge. Main gutters become (20px), bottom clearance becomes (130px), and settings stack with (36px) between columns. The reminder summary stacks vertically, footer icon controls narrow, and the reply-tracking form remains within the viewport. Footer padding includes `env(safe-area-inset-bottom)`.

## Elevation & Depth

Thin borders and subtle changes of black establish most structure. Search results are tonal overlays without a desktop shadow. The mobile expanded search uses `0 5px 20px #0009`; transient toasts use `0 8px 24px #0008`. These are soft overlay shadows, not permanent card elevation.

**The Flat Workspace Rule.** Use thin dividers and tonal surfaces for structure; reserve shadows for temporary overlays and feedback.

## Shapes

Controls and fields use gently rounded rectangles; expanded search and toasts are slightly rounder, and result panels use the surface radius. Account chips use pill-like corners, while initials and status dots are circles. Region separators remain straight. Functional icons are inline stroked SVG with rounded caps and joins, generally (22px) with stroke width (1.6); they are not decorative imagery.

## Components

### Buttons

Primary actions use a pale surface and dark text, minimum height (42px), and medium weight (500). Secondary actions use transparent fills and gray borders; text actions stay muted until hover. Small buttons use (36px) minimum height. Disabled controls reduce opacity to (0.45). Icon buttons use transparent resting surfaces and shared hover treatment; accessible names identify their actions.

Controls share a visible focus outline (2px) offset (4px). The account-search field currently suppresses that outline; this is implementation drift, not a reusable focus rule.

### Account Chips

Chips combine a circular initials marker, an account link, and a remove control. They remain a single horizontally scrolling strip. Error borders communicate a problem alongside account-error text in settings. The link and remove button retain separate accessible actions.

### Inputs / Fields

Fields use dark surfaces, restrained borders, visible labels or accessible hidden labels, and muted placeholders. Exact-handle search expands next to the plus; the plus rotates into a close action, and Escape closes the search. Search results identify one account and offer Watch. Draft fields use a slightly darker surface, minimum height (160px), vertical resizing, and comfortable reading line height.

### Navigation and Footer

The watched-account strip provides source access. The fixed footer exposes monitoring on the left, daily reply progress and pace in the center, and a notification icon and a labelled API keys action opening settings on the right. The reply progress control opens the goal settings and automatic counts; no posting acknowledgement is required. Monitoring labels and dots distinguish running, paused, offline, and attention states. Settings remain hidden until requested and open within this page.

### Monitoring State

A small three-bar listening mark sits over “Monitoring posts…”. A disconnected account, empty watchlist, paused monitoring, or account errors changes the message and supplies brief next-step guidance. The mark flattens when paused. It is a compact status indicator, not an illustration.

### Draft Workspace

Post options form a horizontal selector with tonal selection. Source metadata and source text precede the draft tabs. The active draft tab receives a pale underline; the editor and actions remain in one column. Opening X hands the draft to the composer; the interface does not claim publication.

### Feedback and Motion

A pale toast with dark text appears above the footer; errors use a pale red tint. Search expansion and plus rotation use (0.2s ease-out). The three listening bars pulse over (1.8s ease-in-out), staggered by (0.2s). These animations only run when reduced motion is not requested.

## Do's and Don'ts

### Do:

- Do keep the main field quiet while monitoring has no posts to show.
- Do use color sparingly for status and keep its meaning in adjacent text.
- Do preserve keyboard focus, accessible icon labels, and truthful paused, disconnected, and error states.
- Do retain horizontal account scrolling and footer safe-area spacing on narrow screens.

### Don't:

- Don't restore the obsolete green-and-ivory palette, serif headings, or sidebar layout.
- Don't introduce decorative imagery, hero copy, or card grids into the monitoring field.
- Don't imply that opening X confirms publication or that monitoring continues when the server is unavailable.

### Draft angles

Above the draft editor, a wrapping row of neutral outlined buttons offers Auto, Agreeable, Disagree, Controversial and Provocative. The saved angle uses a light border and `aria-pressed`; each button rewrites both draft types. Helper text states that one AI attempt is used. Buttons retain 44px minimum height and wrap on narrow screens. Failed or skipped generation preserves the previous draft and its selected angle.
