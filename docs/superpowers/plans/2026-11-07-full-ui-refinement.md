# Full UI Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modernize AutoClick Pro's dark and light interfaces without changing workflows or features.

**Architecture:** Preserve MainWindow's header, hero, actions, tabs, and footer. Centralize visual tokens in theme.py, apply targeted spacing/layout adjustments in main_window.py, and style the existing SequenceEditor through shared Qt rules.

**Tech Stack:** Python 3, PySide6, Qt Style Sheets, pytest, pytest-qt, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-11-07-full-ui-refinement-design.md`

## Global Constraints

- Keep the current application structure and navigation behavior.
- Preserve every existing control, setting, signal, object name, and engine behavior.
- Refine dark and light themes together; preserve System theme behavior.
- Use native Qt controls and add no dependencies.
- Maintain at least 4.5:1 normal-text contrast and visible keyboard focus.
- Keep HUD and screenshot exclusion unchanged.

## Review Focus

- Small window: content must remain scrollable without horizontal clipping; test at minimum size.
- Disabled controls: text and boundaries must remain distinguishable; test dark/light stylesheet selectors and palette.
- System theme: must continue returning native styling without hardcoded dark text; test existing behavior.
- Long status messages: wrapping must not hide main actions; test at minimum width.
- Active tab: selected state must remain visually clear in dark and light themes; test style tokens and screenshots.

---

### Task 1: Theme Tokens and Component Styling

**Files:**
- Modify: `autoclick_pro/ui/theme.py`
- Test: `tests/test_theme.py`

**Interfaces:**
- Produces: shared `_DARK_QSS`, generated `_LIGHT_QSS`, `set_app_theme(...)`, `label_styles(...)`, and `status_style(...)` with unchanged signatures.
- Consumes: existing theme API used by MainWindow and SequenceEditor.

- [ ] **Step 1: Write failing theme tests** asserting both generated styles contain rounded tab selection, visible two-pixel focus outlines, disabled foreground tokens, and comfortable card radii; assert System remains an empty stylesheet.
- [ ] **Step 2: Run `python -m pytest tests/test_theme.py -q` and confirm failures identify missing styles.**
- [ ] **Step 3: Replace hardcoded visual duplication with dark/light semantic color mappings and refined QSS for cards, tabs, fields, checkboxes, sliders, buttons, tables, scrollbars, tooltips, and progress.** Use 8px card/control radii, 12px page spacing increments, visible 2px focus, and restrained blue selection. Preserve existing exported API.
- [ ] **Step 4: Run `python -m pytest tests/test_theme.py tests/test_main_window.py -q` and confirm PASS.**

### Task 2: Main Layout Hierarchy

**Files:**
- Modify: `autoclick_pro/ui/main_window.py:249-361`
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: unchanged theme functions.
- Produces: same MainWindow widgets and signals with refined geometry and accessible labels.

- [ ] **Step 1: Add failing tests** for 20/24px outer margins, 16px section spacing, 48px primary actions, wrapped hotkey note, and unchanged tab order Clicker/Sequence/Settings.
- [ ] **Step 2: Run targeted tests and confirm geometry assertion failures.**
- [ ] **Step 3: Refine header, hero, controls, tab content margins, and footer spacing.** Keep widgets and behavior; set useful accessible names where native labels do not provide them.
- [ ] **Step 4: Run `python -m pytest tests/test_main_window.py tests/test_sequence_editor.py -q` and confirm PASS.**

### Task 3: Visual and Full Verification

**Files:**
- Modify only files from Tasks 1–2 if visual defects are found.
- Test: `tests/test_theme.py`, `tests/test_main_window.py`, `tests/test_sequence_editor.py`

**Interfaces:**
- Consumes: completed shared theme and MainWindow layout.
- Produces: verified desktop-linked executable.

- [ ] **Step 1: Add minimum-size and long-status tests** proving actions stay visible and pages remain usable without horizontal overflow.
- [ ] **Step 2: Run the new tests; fix only demonstrated clipping or contrast defects.**
- [ ] **Step 3: Capture and inspect dark/light screenshots at default and minimum sizes using the existing Qt offscreen/grab support.** Verify both themes, selected tabs, focus, disabled controls, and Sequence table.
- [ ] **Step 4: Run `python -m pytest -q`, `ruff check .`, and `mypy`; all must pass.**
- [ ] **Step 5: Stop the running app, run `python -m PyInstaller --noconfirm AutoClickPro.spec`, smoke-test the built EXE, and verify the Desktop shortcut still targets `dist/AutoClickPro/AutoClickPro.exe`.**
