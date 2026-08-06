# frontend/src/styles

Global CSS for the dashboard.

## Contents

- `README.md` — this file.
- `components.css` — component styles.
- `dashboard.css` — top-level dashboard styles.
- `layout.css` — page/layout structure, plus the base element defaults for the app frame (`body`, `#root`, `a`, `button`, `::file-selector-button`). The element-level `button`/`a` rules are deliberately low specificity: any component class or inline style overrides them, so they only reach controls nothing else styles.
- `motion.css` — `prefers-reduced-motion: reduce` overrides: collapses the `--t-*` motion tokens to zero and disables animations/transitions globally (imported after `tokens.css` so the `:root` override wins).
- `responsive.css` — responsive/media-query overrides.
- `tokens.css` — design tokens (colors, spacing).
- `widgets.css` — widget-specific styles.
