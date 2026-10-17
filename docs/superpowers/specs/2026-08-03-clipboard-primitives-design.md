# Clipboard primitives — design

- **Date:** 2026-08-03
- **Status:** design approved; pending spec review
- **Repo:** `i3-computer-use-mcp`
- **Sub-project:** 1 of 4

## Roadmap context

This is the first of four staged sub-projects that grow `i3-cua-mcp` from a
look→act primitive toolkit into a "launch a task and watch it run" system:

1. **Clipboard primitives** (this doc) — exact text in/out across apps.
2. **CDP (Chrome) channel** — drive/read the browser by DOM, not pixels.
3. **tmux/pty (terminal) channel** — read scrollback as text, inject input,
   distinguish "busy" from "at a prompt."
4. **Task-runner layer** — launch → observe → supervise, built on top of 1–3,
   with its own scratch workspace, action log, pause/interrupt, and confirm-gates.

Each sub-project gets its own spec → plan → implementation cycle. Clipboard is
first because it is the smallest and it converts the north-star demo — create a
Cloudflare API token in the browser, hand it to a terminal — from "fragile OCR
of a 40-char secret" into "exact."

## Motivation

Pixels are the wrong channel for exact text. Reading a secret token out of a
screenshot risks OCR confusions (`l/1/I`, `O/0`), and a 40-char credential must
be byte-exact. The X clipboard is the app-native path: click an app's *copy*
button → read the clipboard → exact string; set the clipboard → paste → exact
string into another app. It is universal across every X11 app, unlike CDP
(Chrome-only) or tmux (terminal-only).

## Scope

Two new tools on the existing MCP server:

- `read_clipboard(selection="clipboard") -> str`
  Returns the current text of the named X selection. Returns `""` when the
  selection is empty or unowned.

- `write_clipboard(text, selection="clipboard", secret=False) -> str`
  Sets the named X selection to `text`. Returns a summary that **never contains
  the value** (e.g. `wrote 47 chars to CLIPBOARD`).

### Selections

`selection ∈ {"clipboard", "primary"}` (validated; any other value errors).

- `clipboard` — the Ctrl-C / Ctrl-Shift-V selection (most GUI apps).
- `primary` — the select-to-copy / middle-click selection (common in terminals).

Both are exposed because terminals and GUI apps disagree on which they use; the
caller picks. No `secondary`; no `both` convenience yet — call twice if needed.

### Secret handling (approved posture: a + b)

Rationale (user): the server runs locally and the user already trusts it to
drive the machine, so secrecy is convenience, not a security boundary.

- **Default (a, minimal):** `read_clipboard` returns the content plainly (the
  caller needs it to act). `write_clipboard` returns only a length summary and
  **never echoes the value** — not in the return string, not in exception text.
- **`secret=True` (b):** semantically identical no-echo on write, but a hard
  guarantee the value is excluded from *all* logging paths, present and future.
  This is the hook the **task-runner action log (sub-project 4)** will honor — a
  secret write is recorded as `write_clipboard(<redacted>, …)`. Today, with no
  verbose logging, `secret=True` and the default behave the same; the flag
  exists so credential moves are self-labeling.

There is deliberately no redact-by-default `read` (posture *c* was rejected):
reads always return content.

### Non-goals (YAGNI)

- No `paste()` helper — compose `write_clipboard` + existing `key`/`click`
  (paste chords are app-specific: terminal Ctrl-Shift-V vs GUI Ctrl-V vs
  middle-click for `primary`). Revisit only if composing proves clunky.
- No image/rich-target clipboard, no clipboard history, no auto-expiry, no
  Wayland.

## Implementation

- New module `src/i3_cua_mcp/clipboard.py`, kept separate from `inputs.py`:
  clipboard is X-selection I/O, not xdotool input synthesis — matching the
  codebase's one-concern-per-file split (cf. `i3control.py` vs `i3tree.py`).
- Backend: **`xclip`** (add to documented system deps alongside `xdotool`,
  `imagemagick`, `i3`).
  - Read: `xclip -selection <sel> -o` → stdout.
  - Write: `xclip -selection <sel> -i` with `text` on stdin. `xclip` forks a
    resident holder to serve the selection after our call returns, so the value
    survives; we close stdin so the parent exits promptly.
- **DISPLAY-faithful:** `xclip` targets `$DISPLAY`, same contract as the rest of
  the server (no ambient fallback).
- Same subprocess-timeout discipline as `inputs._run` (a `CMD_TIMEOUT`-style
  bound); a private `_run()` raises `ClipboardError` on failure.
- `read`/`write` do **not** call `reset_idle()` — they are not pointer/keyboard
  activity and should not fake idle-timer resets. A subsequent paste (via
  `key()`) already resets idle.

### Error handling

- `xclip` missing → `ClipboardError` with an install hint.
- Read of an unowned/empty selection → `""` (xclip exits non-zero "there is no
  owner"; treat as empty, not an error).
- Timeout → raise (bounded like `inputs`).
- Invalid `selection` → `ValueError` (surfaces as `is_error`) listing allowed
  values.
- `write_clipboard` failures never include `text` in the message.

## Testing

Mirrors the existing suite (subprocess-mocked units + a Xephyr round-trip):

- **Unit** (mock `_run`): correct `xclip` args per selection; stdin carries
  `text` on write; `read` returns stdout; empty/unowned → `""`; the `write`
  return string excludes the value (default and `secret=True`); invalid
  selection raises; missing-`xclip` path.
- **Sandbox** (`DISPLAY=:1`): `write_clipboard("hello")` then
  `read_clipboard() == "hello"`; `primary` vs `clipboard` isolation; a
  `secret=True` write returns no value.

## Acceptance criteria

- Round-trip read/write verified in the sandbox for both selections.
- `write_clipboard` never emits the value (default or secret).
- North-star flow demoable end-to-end: browser copy → `read_clipboard` → exact
  token; `write_clipboard(tok)` + paste → exact into a terminal.
- New unit tests pass; CI stays green; README tool table + system-deps updated.

## Future (later sub-projects may pull these in)

- `paste()` helper; `selection="both"`; image/rich targets; secret auto-expiry;
  action-log redaction wiring (sub-project 4).
