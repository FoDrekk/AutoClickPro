# AutoClick Pro Full UI Refinement

## Goal

Modernize the full AutoClick Pro interface with clearer hierarchy and comfortable spacing while preserving every existing workflow and feature.

## Scope

Retain the current single-column application structure: header, status panel, primary actions, Clicker/Sequence/Settings tabs, and footer. Do not introduce a sidebar or change navigation behavior.

Refine the dark and light themes together. Preserve System theme behavior. Improve surfaces, typography, control styling, focus and disabled states, spacing, scrolling, and readable labels. No feature additions or behavioral redesign.

## Visual system

- Professional utility aesthetic with restrained blue accents.
- Neutral window background and distinct, softly rounded card surfaces.
- Comfortable 4/8-based spacing rhythm.
- Strong status hierarchy without excessive decoration.
- Normal text contrast of at least 4.5:1 and visible keyboard focus.
- Use native Qt controls and the bundled application icon. Add no UI framework or icon dependency.

## Implementation boundaries

Centralize visual tokens and shared styling in `autoclick_pro/ui/theme.py`. Make targeted layout and semantic adjustments in existing UI files only where needed. Preserve widget object names, public methods, signals, settings keys, hotkeys, and engine behavior.

The existing floating HUD and its screenshot-exclusion behavior remain unchanged.

## Verification

- Add or adjust UI tests for any changed structure or theme behavior.
- Run the complete pytest suite, lint, and type checks.
- Inspect dark and light screenshots at the default window size and a smaller supported size.
- Rebuild the PyInstaller executable and smoke-test it.
- Update the executable used by the Desktop AutoClick Pro shortcut after verification.
