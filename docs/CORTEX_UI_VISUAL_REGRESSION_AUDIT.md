# CORTEX AGENT — P0 FRONTEND VISUAL REGRESSION & ROOT CAUSE AUDIT

**Date:** 2026-11-13  
**Status:** ROOT CAUSE IDENTIFIED & REMEDIATION PLAN INITIATED  
**Target:** Electron Desktop App (`apps/desktop`)  

---

## 1. Executive Summary & Problem Diagnosis

Following the integration of `@assistant-ui/react`, the running Electron application exhibited severe visual breakage:
1. The main layout collapsed into the top-left corner of the window.
2. The sidebar and header were vertically stacked or improperly aligned rather than positioned in a full-height, full-width flex workspace.
3. Most of the desktop window (>70% of available viewport real estate) was left blank and unrendered.
4. The native HTML file input element (`<input type="file" multiple>`) was rendered in the center of the composer.
5. Interactive buttons, spacing scale, font hierarchies, and card containers lost their styles and fell back to standard unstyled HTML elements.

Our systematic inspection of the Electron renderer entry point, Vite configuration, stylesheet loading order, and PostCSS pipeline has isolated the exact root cause.

---

## 2. Root Cause Analysis

### A. Missing Tailwind & PostCSS Processing Pipeline (Primary Root Cause)
- **Investigation:**  
  All newly constructed components (`App.jsx`, `CortexSidebar.jsx`, `CortexHeader.jsx`, `CortexThread.jsx`, `CortexComposer.jsx`, and all toolcards) were authored using Tailwind CSS utility classes:
  - Layout: `flex`, `h-screen`, `w-screen`, `w-64`, `flex-1`, `flex-col`, `grid`, `col-span-1`
  - Dimensions: `h-full`, `max-w-3xl`, `min-h-[60vh]`, `overflow-hidden`
  - Surfaces: `bg-slate-950`, `bg-black/40`, `border-white/10`, `rounded-2xl`
  - Visibility: `className="hidden"` on `<input type="file" />`
- **The Defect:**  
  Neither `postcss.config.cjs` nor `tailwind.config.cjs` was configured in `apps/desktop`. Furthermore, `@tailwind base; @tailwind components; @tailwind utilities;` was not imported in any stylesheet.
- **The Result:**  
  When Vite built or served the frontend, **zero Tailwind CSS rules were emitted**.
  - `flex`, `w-screen`, and `h-screen` did not exist in computed CSS, leaving `#root` and `<div className="flex h-screen w-screen">` as default unstyled block elements with `height: auto; width: auto`.
  - The entire application collapsed to its intrinsic text width in the top-left corner.
  - The native file input's `className="hidden"` had no corresponding CSS rule (`display: none`), rendering the raw browser file input widget.
  - Border radii, background colors, paddings, and alignment rules were completely absent.

### B. Unstyled Mount Root (`#root`)
- **Investigation:**  
  In `index.html`, React mounts into `<div id="root"></div>`.
- **The Defect:**  
  `src/styles.css` set `html, body { height: 100%; overflow: hidden; }` but omitted `#root`.
- **The Result:**  
  Without `#root { height: 100%; width: 100%; }`, children attempting to fill `100%` height or viewport height encountered collapsing parent dimensions.

### C. Theme Token Disconnection (Dark & Light Theme Inconsistency)
- **Investigation:**  
  `styles.css` defines rich CSS custom properties for dark (`:root`) and light (`[data-theme="light"]`) modes:
  - `--bg`, `--surface`, `--surface-2`, `--border`, `--text`, `--accent`, etc.
- **The Defect:**  
  The newly introduced components used hardcoded Tailwind slate colors (`bg-slate-950`, `text-slate-100`, `border-slate-800`) instead of semantic tokens mapping to `--bg`, `--surface`, `--text`, and `--border`.
- **The Result:**  
  Toggling light theme in `CortexHeader.jsx` switched the `data-theme="light"` attribute on `<html>`, but the interface remained stubbornly dark and mismatched because the components used hardcoded slate classes.

### D. Composer Floating Geometry & Z-Index Layering
- **Investigation:**  
  The composer was placed inside an unconstrained flex item with a linear background gradient.
- **The Defect:**  
  It lacked a fixed maximum width container, smooth bottom anchoring, and responsive media constraints for lower resolutions (1024×768).

---

## 3. Affected Files Matrix

| File Path | Defect Observed | Remediation Required |
| :--- | :--- | :--- |
| `apps/desktop/postcss.config.cjs` | Missing file | Create configuration with `tailwindcss: {}` plugin. |
| `apps/desktop/tailwind.config.cjs` | Missing file | Create config mapping content paths and theme extensions to Cortex CSS tokens. |
| `apps/desktop/src/styles.css` | Missing `@tailwind` directives & `#root` 100% sizing | Prepend `@tailwind` directives, style `#root`, and bind design system tokens. |
| `apps/desktop/src/App.jsx` | Unconstrained root wrapper, hardcoded slate colors | Bind to Cortex theme tokens (`var(--bg)`, `var(--surface)`), support responsive viewports. |
| `apps/desktop/src/components/CortexSidebar.jsx` | Fixed hardcoded colors, theme mismatch in light mode | Refactor to design system tokens with subtle borders, fluid scroll, and collapse animation. |
| `apps/desktop/src/components/CortexHeader.jsx` | Hardcoded colors, potential clipping at narrow widths | Integrate clean icon buttons with tooltips and responsive collapse. |
| `apps/desktop/src/components/CortexComposer.jsx` | Exposed native file input, unconstrained popup menus | Fully hide file input (`display: none`), style attachment button, refine floating card geometry. |
| `apps/desktop/src/components/CortexThread.jsx` | Hardcoded slate colors, unstyled welcome cards in light mode | Refactor welcome cards, message bubbles, and action bars with adaptive dark/light tokens. |
| `apps/desktop/src/components/tools/*.jsx` | Tool cards used hardcoded dark slate colors | Harmonize all 7 toolcards with Cortex surface tokens, crisp status borders, and readable typography. |

---

## 4. Remediation Plan & Design System Architecture

1. **Build Pipeline:**
   - Inject `postcss.config.cjs` and `tailwind.config.cjs`.
   - Ensure `@tailwind base; @tailwind components; @tailwind utilities;` is compiled in `styles.css`.
   - Set `#root { height: 100%; width: 100%; overflow: hidden; }`.
2. **Design Tokens & Theme Harmonization:**
   - Map Tailwind colors (`cortex-bg`, `cortex-surface`, `cortex-border`, `cortex-text`, `cortex-accent`) to existing CSS variables.
   - Ensure light theme (`data-theme="light"`) renders beautiful warm parchment surfaces (`#f5f4ed`, `#faf9f5`) and dark theme renders deep anthropic near-black (`#141413`, `#1e1e1c`).
3. **Layout Reconstruction:**
   - **Sidebar:** Width 260px, fixed or collapsed to 56px, independent vertical scroll, active thread indicator.
   - **Header:** Height 52px, flex alignment with title, status pill, language dropdown, and action icons.
   - **Conversation Thread:** Flex-1, auto-scroll, beautiful welcome screen with 5 suggested prompt cards, code block copy, responsive typography.
   - **Floating Composer:** Anchored bottom card, max-width 768px, styled file attachment trigger with hidden input, microphone pulse effect, send/stop button.
4. **Tool Card Polish:**
   - Standardize `TaskPlanCard`, `MailDraftCard`, `WebResearchCard`, `DesktopActionCard`, `ScreenVisionCard`, `ApprovalCard`, and `ToolErrorCard` with consistent headers, badges, and button styling.
5. **Empirical Screenshot Acceptance:**
   - Execute automated headless Chromium verification across 1440×900, 1280×800, and 1024×768 viewports in both Dark and Light themes.
