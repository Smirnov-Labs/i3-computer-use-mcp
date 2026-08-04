# Clipboard Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `read_clipboard` / `write_clipboard` MCP tools so the agent can move exact text (e.g. an API token) between apps without OCR.

**Architecture:** A new self-contained `clipboard.py` module shells out to `xclip` (DISPLAY-faithful), exposing read/write over the `CLIPBOARD` and `PRIMARY` X selections. `server.py` wraps them as two `@mcp.tool()`s. `write_clipboard` returns only a length summary and never echoes the value. Same subprocess-timeout + subprocess-mocked-test conventions as `inputs.py`.

**Tech Stack:** Python ≥3.11, `mcp>=2.0,<3`, `xclip` (system dep), `pytest`, `uv`, Xephyr sandbox.

## Global Constraints

- Python floor: `requires-python = ">=3.11"` (repo pins 3.12 via `.python-version`). Do **not** raise the floor.
- No new **pip** dependency. `xclip` is a **system** dependency (documented in README next to `xdotool`/`imagemagick`), not added to `pyproject.toml`.
- Style: every module starts `from __future__ import annotations`. Error classes subclass `RuntimeError` (precedent: `i3control.I3CommandError`).
- Every subprocess call passes `timeout=CMD_TIMEOUT` (`= 5`) and `text=True`.
- Tests are subprocess-mocked via `monkeypatch` — they must pass with **no X server and no xclip installed**. Never spawn real `xclip` in a unit test.
- Test runner: `uv run pytest` (config: `-q`, `testpaths=["tests"]`). Single file: `uv run pytest tests/test_clipboard.py -v`.
- Tools are registered with a plain `@mcp.tool()` (string return; not `structured_output=False`, which is only for image tools).
- **Secrecy invariant:** `write_clipboard`'s return string and any exception it raises MUST NOT contain the written value.
- **DISPLAY-faithful:** rely on `$DISPLAY` (xclip honors it); no ambient fallback, no `$I3SOCK`-style shortcuts.
- `read_clipboard` / `write_clipboard` do **not** call `inputs.reset_idle()` — they are not pointer/keyboard activity.
- Branch: `feat/clipboard-primitives` (already checked out). End every commit message with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 1: `clipboard.py` — read path + helpers

**Files:**
- Create: `src/i3_cua_mcp/clipboard.py`
- Test: `tests/test_clipboard.py`

**Interfaces:**
- Produces:
  - `ClipboardError(RuntimeError)`
  - `_sel(selection: str) -> str` — lowercases and validates against `("clipboard", "primary")`; raises `ValueError` otherwise.
  - `_run(args: list[str], *, input: str | None = None, capture: bool = True) -> subprocess.CompletedProcess` — runs `["xclip", *args]` with `timeout=CMD_TIMEOUT`, `text=True`; `capture=True` pipes stdout/stderr, `capture=False` routes them to `DEVNULL`; raises `ClipboardError` if xclip is missing.
  - `read_clipboard(selection: str = "clipboard") -> str` — returns selection text, or `""` when unowned.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_clipboard.py`:

```python
"""Tests for clipboard read + helpers (subprocess mocked; no X, no xclip needed)."""
import subprocess

import pytest

from i3_cua_mcp import clipboard


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["xclip"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_read_returns_stdout_on_success(monkeypatch):
    monkeypatch.setattr(clipboard, "_run", lambda args, **kw: _completed(0, stdout="cfut_ABC"))
    assert clipboard.read_clipboard() == "cfut_ABC"


def test_read_returns_empty_on_nonzero(monkeypatch):
    monkeypatch.setattr(clipboard, "_run", lambda args, **kw: _completed(1, stderr="no owner"))
    assert clipboard.read_clipboard() == ""


def test_read_passes_selection(monkeypatch):
    seen = {}
    monkeypatch.setattr(clipboard, "_run",
                        lambda args, **kw: seen.update(args=args) or _completed(0, "x"))
    clipboard.read_clipboard("primary")
    assert seen["args"] == ["-selection", "primary", "-o"]


def test_read_rejects_invalid_selection():
    with pytest.raises(ValueError):
        clipboard.read_clipboard("middle")


def test_run_sets_a_timeout(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw)
        return _completed(0, "ok")

    monkeypatch.setattr(subprocess, "run", fake_run)
    clipboard._run(["-selection", "clipboard", "-o"])
    assert seen.get("timeout")


def test_run_raises_when_xclip_missing(monkeypatch):
    def missing(argv, **kw):
        raise FileNotFoundError("no xclip")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(clipboard.ClipboardError):
        clipboard._run(["-selection", "clipboard", "-o"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_clipboard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'i3_cua_mcp.clipboard'`.

- [ ] **Step 3: Write the module (read path)**

Create `src/i3_cua_mcp/clipboard.py`:

```python
"""X clipboard I/O via xclip — exact text in/out across apps (no OCR).

Kept separate from inputs.py: this is X-selection I/O, not xdotool input
synthesis. DISPLAY-faithful (xclip targets $DISPLAY). write_clipboard never
echoes the value it wrote.
"""
from __future__ import annotations

import subprocess

CMD_TIMEOUT = 5  # seconds; bound a hung xclip so it can't wedge a worker thread
_SELECTIONS = ("clipboard", "primary")


class ClipboardError(RuntimeError):
    """An xclip clipboard operation failed."""


def _sel(selection: str) -> str:
    s = str(selection).lower()
    if s not in _SELECTIONS:
        raise ValueError(
            f"selection must be one of {list(_SELECTIONS)}, got {selection!r}"
        )
    return s


def _run(args: list[str], *, input: str | None = None, capture: bool = True):
    """Run xclip. capture=True pipes stdout/stderr (read path); capture=False
    routes them to DEVNULL (write path) so xclip's backgrounded selection-holder
    can't keep a captured pipe open and hang us until timeout."""
    pipe = subprocess.PIPE if capture else subprocess.DEVNULL
    try:
        return subprocess.run(
            ["xclip", *args],
            input=input,
            text=True,
            stdout=pipe,
            stderr=pipe,
            timeout=CMD_TIMEOUT,
        )
    except FileNotFoundError:
        raise ClipboardError("xclip not found; install it (e.g. `pacman -S xclip`)")


def read_clipboard(selection: str = "clipboard") -> str:
    """Return the text of an X selection ('clipboard' or 'primary').

    Returns "" when the selection is empty or unowned (xclip exits non-zero with
    no owner; treated as empty, not an error).
    """
    sel = _sel(selection)
    r = _run(["-selection", sel, "-o"])
    return r.stdout if r.returncode == 0 else ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_clipboard.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/i3_cua_mcp/clipboard.py tests/test_clipboard.py
git commit -m "feat: clipboard read path (xclip, selection validation, timeout)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `clipboard.py` — write path (secret-safe, no-hang)

**Files:**
- Modify: `src/i3_cua_mcp/clipboard.py` (append `write_clipboard`)
- Test: `tests/test_clipboard.py` (append write tests)

**Interfaces:**
- Consumes: `_sel`, `_run`, `ClipboardError` from Task 1.
- Produces: `write_clipboard(text: str, selection: str = "clipboard", secret: bool = False) -> str` — sets the selection via `_run([... "-i"], input=text, capture=False)`; returns `f"wrote {len(text)} chars to {SEL}"` (+ `" [secret]"` when `secret`); raises `ClipboardError` on non-zero exit without including `text`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_clipboard.py`:

```python
def test_write_returns_char_count_and_excludes_value(monkeypatch):
    monkeypatch.setattr(clipboard, "_run", lambda args, **kw: _completed(0))
    out = clipboard.write_clipboard("s3kr3t-token")
    assert "12 chars" in out
    assert "s3kr3t-token" not in out


def test_write_secret_marks_and_excludes_value(monkeypatch):
    monkeypatch.setattr(clipboard, "_run", lambda args, **kw: _completed(0))
    out = clipboard.write_clipboard("s3kr3t", secret=True)
    assert "[secret]" in out
    assert "s3kr3t" not in out


def test_write_passes_selection_input_and_devnull(monkeypatch):
    seen = {}

    def fake(args, **kw):
        seen.update(args=args, input=kw.get("input"), capture=kw.get("capture"))
        return _completed(0)

    monkeypatch.setattr(clipboard, "_run", fake)
    clipboard.write_clipboard("hello", selection="primary")
    assert seen["args"] == ["-selection", "primary", "-i"]
    assert seen["input"] == "hello"
    assert seen["capture"] is False  # DEVNULL path so the holder can't hang us


def test_write_rejects_invalid_selection():
    with pytest.raises(ValueError):
        clipboard.write_clipboard("x", selection="middle")


def test_write_raises_on_nonzero_without_leaking_text(monkeypatch):
    monkeypatch.setattr(clipboard, "_run", lambda args, **kw: _completed(2, stderr="boom"))
    with pytest.raises(clipboard.ClipboardError) as e:
        clipboard.write_clipboard("s3kr3t-value")
    assert "s3kr3t-value" not in str(e.value)


def test_write_routes_subprocess_to_devnull(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw)
        return _completed(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    clipboard.write_clipboard("x")
    assert seen.get("stdout") is subprocess.DEVNULL
    assert seen.get("stderr") is subprocess.DEVNULL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_clipboard.py -v`
Expected: FAIL — `AttributeError: module 'i3_cua_mcp.clipboard' has no attribute 'write_clipboard'`.

- [ ] **Step 3: Implement `write_clipboard`**

Append to `src/i3_cua_mcp/clipboard.py`:

```python
def write_clipboard(text: str, selection: str = "clipboard", secret: bool = False) -> str:
    """Set an X selection ('clipboard' or 'primary') to text; paste it with
    key()/click() afterward.

    Returns a length summary only — never the value. secret=True guarantees the
    value is excluded from all logging (honored by the future task-runner action
    log) and appends a [secret] marker.
    """
    sel = _sel(selection)
    r = _run(["-selection", sel, "-i"], input=text, capture=False)
    if r.returncode != 0:
        raise ClipboardError(f"xclip write to {sel} failed (exit {r.returncode})")
    return f"wrote {len(text)} chars to {sel.upper()}" + (" [secret]" if secret else "")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_clipboard.py -v`
Expected: PASS (12 tests total).

- [ ] **Step 5: Commit**

```bash
git add src/i3_cua_mcp/clipboard.py tests/test_clipboard.py
git commit -m "feat: clipboard write path (secret-safe return, DEVNULL no-hang)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Wire tools into the MCP server + README

**Files:**
- Modify: `src/i3_cua_mcp/server.py` (import `clipboard`; add two tools)
- Modify: `tests/test_server.py` (import `clipboard`; add delegation tests)
- Modify: `README.md` (tool table row; `xclip` system dep)

**Interfaces:**
- Consumes: `clipboard.read_clipboard`, `clipboard.write_clipboard` from Tasks 1–2.
- Produces: `server.read_clipboard(selection="clipboard") -> str`, `server.write_clipboard(text, selection="clipboard", secret=False) -> str` (thin delegators; no `reset_idle`).

- [ ] **Step 1: Write the failing delegation tests**

In `tests/test_server.py`, change the import line:

```python
from i3_cua_mcp import coords, i3control, i3tree, inputs, server
```
to:
```python
from i3_cua_mcp import clipboard, coords, i3control, i3tree, inputs, server
```

Append these tests:

```python
# --- clipboard wiring (delegate; write muzzles the value) ---

def test_read_clipboard_delegates(monkeypatch):
    seen = {}
    monkeypatch.setattr(clipboard, "read_clipboard",
                        lambda sel: seen.setdefault("sel", sel) or "cfut_X")
    assert server.read_clipboard("primary") == "cfut_X"
    assert seen == {"sel": "primary"}


def test_write_clipboard_delegates_and_hides_value(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        clipboard, "write_clipboard",
        lambda text, sel, secret: seen.update(text=text, sel=sel, secret=secret)
        or "wrote 3 chars to CLIPBOARD [secret]",
    )
    out = server.write_clipboard("abc", selection="clipboard", secret=True)
    assert seen == {"text": "abc", "sel": "clipboard", "secret": True}
    assert "abc" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL — `AttributeError: module 'i3_cua_mcp.server' has no attribute 'read_clipboard'`.

- [ ] **Step 3: Add the import in `server.py`**

Change:
```python
from . import capture, coords, i3control, i3tree, inputs
```
to:
```python
from . import capture, clipboard, coords, i3control, i3tree, inputs
```

- [ ] **Step 4: Add the two tools in `server.py`**

Insert immediately **after** the `get_mouse` tool (end of the keyboard+focus section, before the `# --- i3 control` banner):

```python
# --- clipboard (exact text in/out; no OCR) ----------------------------------

@mcp.tool()
def read_clipboard(selection: str = "clipboard") -> str:
    """Read the text of an X selection: 'clipboard' (Ctrl-C / Ctrl-Shift-V) or
    'primary' (select / middle-click). Returns '' if empty or unowned."""
    return clipboard.read_clipboard(selection)


@mcp.tool()
def write_clipboard(text: str, selection: str = "clipboard", secret: bool = False) -> str:
    """Set an X selection ('clipboard' or 'primary') to text, then paste with
    key('ctrl+v' or 'ctrl+shift+v') or a middle-click. Returns only a length
    summary — never the value. Pass secret=True for credentials so the value is
    never logged."""
    return clipboard.write_clipboard(text, selection, secret)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: PASS (existing tests + 2 new).

- [ ] **Step 6: Update README**

In `README.md`, in the tool table, add a row after the `get_mouse` row:

```markdown
| `read_clipboard(selection?)` / `write_clipboard(text, selection?, secret?)` | Exact text in/out of the X `clipboard`/`primary` selection (no OCR); `write` returns only a length, never the value |
```

And in the **Requirements** section, change:
```markdown
System: `xdotool`, `imagemagick` (`import`), `i3`, and for the sandbox `Xephyr`
```
to:
```markdown
System: `xdotool`, `imagemagick` (`import`), `xclip`, `i3`, and for the sandbox `Xephyr`
```

- [ ] **Step 7: Commit**

```bash
git add src/i3_cua_mcp/server.py tests/test_server.py README.md
git commit -m "feat: expose read_clipboard/write_clipboard MCP tools + docs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Sandbox round-trip verification + full suite

**Files:** none (verification + memory note only)

**Interfaces:** Consumes the shipped `clipboard` module and MCP tools.

- [ ] **Step 1: Ensure a sandbox X server on `:1`**

Run (skip if `:1` already up): `./sandbox/run-xephyr.sh &`
Verify: `DISPLAY=:1 xdpyinfo >/dev/null && echo ":1 ok"`
Expected: `:1 ok`.

- [ ] **Step 2: Round-trip both selections + secret, against `:1`**

Run:
```bash
DISPLAY=:1 uv run python -c "
from i3_cua_mcp import clipboard
print(clipboard.write_clipboard('hello-clip'))
assert clipboard.read_clipboard() == 'hello-clip', 'clipboard round-trip'
print(clipboard.write_clipboard('prim-val', selection='primary'))
assert clipboard.read_clipboard('primary') == 'prim-val', 'primary round-trip'
assert clipboard.read_clipboard() == 'hello-clip', 'selections independent'
print(clipboard.write_clipboard('s3kr3t', secret=True))
assert clipboard.read_clipboard('primary') == 'prim-val'
print('ROUND-TRIP OK')
"
```
Expected: prints three `wrote N chars to …` lines (the `secret=True` one ends `[secret]`, none print the value), then `ROUND-TRIP OK`. **The command must return promptly** — if it hangs ~5s then errors with a timeout, xclip on this box is not backgrounding its holder; fix by detaching the writer with `subprocess.Popen([...], stdin=PIPE)` + `proc.stdin.write/close()` (no `wait`) instead of `subprocess.run`, keeping stdout/stderr on `DEVNULL`, and re-run.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest`
Expected: PASS (all prior tests + the new clipboard/server tests), exit 0.

- [ ] **Step 4: Update project memory**

Edit `/home/vania/.claude/projects/-home-vania/memory/project_i3_cua_mcp.md`: add a dated bullet noting clipboard primitives shipped (tools `read_clipboard`/`write_clipboard`, `clipboard.py`, xclip backend, `secret=True` muzzle, DEVNULL-avoids-holder-hang gotcha), and that this is sub-project 1 of 4 (next: CDP, then tmux, then task-runner). Update the `MEMORY.md` one-line pointer if the tool count/summary changed.

- [ ] **Step 5: (No commit)** — verification + memory only. Leave the branch ready; integration (merge/PR) is handled separately via `superpowers:finishing-a-development-branch`.

---

## Notes for the implementer

- **Optional live demo (not required to pass):** the north-star flow — copy a value from a real app on `:0`, `read_clipboard()` it, `write_clipboard()` into another window, paste. Do this only on the user's say-so; it touches the live desktop.
- The `secret=True` flag is intentionally near-inert today (it only adds a `[secret]` marker and the no-leak guarantee already holds by default). Its real consumer is sub-project 4's action log — do **not** add logging here.
