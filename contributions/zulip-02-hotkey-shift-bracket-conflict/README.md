# zulip/zulip #40112 — Cmd/Ctrl+Shift+bracket no longer triggers list indent

**Upstream repo:** https://github.com/zulip/zulip
**Issue:** https://github.com/zulip/zulip/issues/40112
**Area:** frontend (TypeScript), compose box keyboard shortcuts
**Difficulty:** moderate (subtle root cause, trivial fix, priority: high)

## The bug

Zulip binds `Cmd+]` / `Ctrl+]` (and `[`) in the compose box to increase/decrease
list indentation (see the shortcut reference in `web/src/info_overlay.ts`,
which documents it as `Ctrl+]` / `Ctrl+[` with no Shift).

On macOS, `Cmd+Shift+]` and `Cmd+Shift+[` are the *browser's own* "switch to
next/previous tab" shortcuts. Some browsers still deliver the corresponding
`keydown` event to the focused page element even though they also handle the
tab switch themselves. `handle_keydown` in `web/src/compose_ui.ts` checked
only `isCmdOrCtrl && (key === "]" || key === "[")`, with no check on
`event.shiftKey` — so every time a user switched browser tabs while the
compose box was focused, Zulip *also* indented (or outdented) whatever list
item the cursor was in. Repeated tab-switching caused progressively deeper
indentation, silently corrupting the message being composed.

Notably, the same function already excludes Shift for a sibling shortcut two
lines earlier (`key === "i" && !event.shiftKey`, for italic vs. the
Shift-using "link"/"code" shortcuts) — the bracket-key branch was just
missing the equivalent guard.

## The fix

Added `!event.shiftKey` to the condition, matching the documented shortcut
(no Shift) and the existing style used elsewhere in the same function:

```ts
if (isCmdOrCtrl && !event.shiftKey && (key === "]" || key === "[")) {
```

Added a regression test in `web/tests/compose_ui.test.cjs`:
`handle_keydown ignores Cmd/Ctrl+Shift+bracket` — simulates a Mac keyboard,
fires a `Cmd+Shift+]` keydown on a textarea containing a list item, and
asserts the textarea content is untouched; then fires the same event
without Shift and asserts the list *is* indented, as a sanity check that the
fix doesn't disable the real shortcut.

## Verification performed

- `node --check` on both changed files (syntax only, since the project's
  TypeScript toolchain requires `node_modules` that aren't installed in
  this sandbox).
- `npx prettier` (with a minimal config, since the project's actual
  config references a plugin — `prettier-plugin-astro` — not installed
  here) against both files: the only formatting diff found was a
  pre-existing, unrelated block at a different line, confirmed via
  `git diff` to not be part of this change; the new lines matched
  Prettier's formatting.
- `npx eslint` could not run at all — `eslint.config.js` imports
  `@eslint/eslintrc`, which isn't installed without a full `pnpm install`.
- Manually traced `handle_keydown` → `handle_list_indent` step by step for
  both the buggy and fixed condition against a small textarea fixture
  (`"- Item 1"` with the cursor at the end) to confirm the exact resulting
  string and cursor position the new test asserts.
- Searched the existing test suite for any other test exercising
  `handle_keydown` with bracket keys: none exist, so this fix doesn't
  contradict established coverage.
- **Not run:** the actual JS test runner (`tools/test-js-with-node`) or a
  real browser — this sandbox has no `node_modules` installed for the
  `web/` package. A maintainer or CI should confirm:
  `tools/test-js-with-node web/tests/compose_ui.test.cjs`

## Status

**Not yet submitted upstream.** See the top-level `contributions/README.md`
for why, and what's needed to open the actual PR against `zulip/zulip`.

`fix.patch` in this directory is the exact `git diff` to apply (from the
root of a `zulip/zulip` checkout) with `git apply fix.patch`.
