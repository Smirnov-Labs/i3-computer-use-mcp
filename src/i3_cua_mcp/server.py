"""i3-aware computer-use MCP server (X11).

Tools let a model SEE the desktop (per-output / per-window screenshots),
UNDERSTAND it (i3 tree: windows, geometry, focus), and DRIVE it
(click / type / key / scroll) — with pointer coordinates measured in the
*screenshot the model was just handed*, which the server maps back to the real
multi-output screen.

Scope: read + focus + input. Layout mutation (move/resize/relayout/workspaces)
is intentionally out of scope — see DESIGN-i3-control-extension.md.
"""
from __future__ import annotations

import json
import os
import sys

from mcp.server.mcpserver import MCPServer, Image

from . import capture, i3tree, inputs
from .coords import get_last, set_last

mcp = MCPServer("i3-cua", version="0.1.0")


def _shot_response(shot: capture.Shot):
    """Store the mapping and return [image, caption] for the model."""
    set_last(shot.frame)
    meta = shot.frame.as_dict()
    caption = (
        f"Screenshot of {meta['captured']} — "
        f"{meta['screenshot_size']['w']}x{meta['screenshot_size']['h']}px "
        f"(scale {meta['scale']}). Give click/move/scroll/drag coordinates in "
        "THIS image's pixel space (top-left = 0,0); the server maps them to the "
        "real screen.\n" + json.dumps(meta)
    )
    return [Image(data=shot.png, format="png"), caption]


# --- perception -------------------------------------------------------------

@mcp.tool()
def list_windows() -> str:
    """List all i3-managed windows: con id, class, title, workspace, output,
    global geometry, focus/visibility. Use the `id` for focus/screenshot tools."""
    return json.dumps(i3tree.list_windows(), indent=2)


@mcp.tool()
def get_outputs() -> str:
    """List active outputs (monitors) with their global geometry and workspace."""
    return json.dumps(i3tree.get_outputs(), indent=2)


@mcp.tool(structured_output=False)
def screenshot(output: str | None = None):
    """Screenshot one output (monitor); defaults to the primary output.

    Pass an output name from get_outputs (e.g. "DP-0") to target another monitor.
    A full-desktop grab would span every monitor and downscale badly, so this is
    per-output by design.
    """
    outs = i3tree.get_outputs()
    if output:
        target = next((o for o in outs if o["name"] == output), None)
        if target is None:
            return f"No such output {output!r}. Available: {[o['name'] for o in outs]}"
    else:
        target = i3tree.primary_output(outs)
    if target is None:
        return "No active outputs found."
    r = target["rect"]
    shot = capture.capture_region(r["x"], r["y"], r["w"], r["h"], f"output {target['name']}")
    return _shot_response(shot)


@mcp.tool(structured_output=False)
def screenshot_window(con_id: int):
    """Full-resolution screenshot cropped to a single window (by i3 con id).

    Great for reading small text: a window crop is usually under the scale budget
    so you see it 1:1.
    """
    w = i3tree.find_window(con_id)
    if w is None:
        return f"No window with con id {con_id}. Call list_windows first."
    if not w["visible"]:
        return (
            f"Window {con_id} ({w['wm_class']}) is on non-visible workspace "
            f"{w['workspace']!r}. focus_window it first, or screenshot its output."
        )
    r = w["rect"]
    label = f"window {con_id} ({w['wm_class'] or '?'}: {w['title'] or ''})".strip()
    shot = capture.capture_region(r["x"], r["y"], r["w"], r["h"], label)
    return _shot_response(shot)


# --- pointer (coordinates are in the last screenshot's pixel space) ----------

def _map(x: float, y: float):
    frame = get_last()
    if frame is None:
        return int(round(x)), int(round(y)), "global (no prior screenshot)"
    gx, gy = frame.to_global(x, y)
    return gx, gy, frame.label


@mcp.tool()
def click(x: float, y: float, button: str = "left") -> str:
    """Click at (x,y) measured in the last screenshot's pixels. button: left|middle|right."""
    gx, gy, ref = _map(x, y)
    inputs.click(gx, gy, button)
    return f"{button} click at screenshot({x},{y}) -> screen({gx},{gy}) [ref: {ref}]"


@mcp.tool()
def double_click(x: float, y: float, button: str = "left") -> str:
    """Double-click at (x,y) in the last screenshot's pixel space."""
    gx, gy, ref = _map(x, y)
    inputs.click(gx, gy, button, count=2)
    return f"double {button} click at screen({gx},{gy}) [ref: {ref}]"


@mcp.tool()
def move_mouse(x: float, y: float) -> str:
    """Move the pointer to (x,y) in the last screenshot's pixel space."""
    gx, gy, ref = _map(x, y)
    inputs.move(gx, gy)
    return f"moved to screen({gx},{gy}) [ref: {ref}]"


@mcp.tool()
def drag(x1: float, y1: float, x2: float, y2: float, button: str = "left") -> str:
    """Drag from (x1,y1) to (x2,y2); coords in the last screenshot's pixel space."""
    gx1, gy1, ref = _map(x1, y1)
    gx2, gy2, _ = _map(x2, y2)
    inputs.drag(gx1, gy1, gx2, gy2, button)
    return f"dragged screen({gx1},{gy1})->({gx2},{gy2}) [ref: {ref}]"


@mcp.tool()
def scroll(x: float, y: float, direction: str = "down", amount: int = 3) -> str:
    """Scroll at (x,y) (last-screenshot pixel space). direction: up|down."""
    gx, gy, ref = _map(x, y)
    inputs.scroll(gx, gy, direction, amount)
    return f"scrolled {direction} x{amount} at screen({gx},{gy}) [ref: {ref}]"


# --- keyboard + focus -------------------------------------------------------

@mcp.tool()
def focus_window(con_id: int) -> str:
    """Give i3 keyboard focus to a window (by con id) before typing into it."""
    if i3tree.find_window(con_id) is None:
        return f"No window with con id {con_id}."
    ok = i3tree.focus_window(con_id)
    return f"focus {'ok' if ok else 'FAILED'} for con {con_id}"


@mcp.tool()
def type_text(text: str, con_id: int | None = None) -> str:
    """Type text into the focused window. If con_id is given, focus it first.

    Typing goes to whatever window has focus — always focus_window (or pass
    con_id) first, or the text lands in the wrong place.
    """
    if con_id is not None:
        i3tree.focus_window(con_id)
    inputs.type_text(text)
    return f"typed {len(text)} chars" + (f" into con {con_id}" if con_id is not None else "")


@mcp.tool()
def key(keys: str, con_id: int | None = None) -> str:
    """Press a key/chord in xdotool syntax (e.g. 'ctrl+s', 'Return', 'alt+Tab')."""
    if con_id is not None:
        i3tree.focus_window(con_id)
    inputs.key(keys)
    return f"pressed {keys}"


@mcp.tool()
def get_mouse() -> str:
    """Current global pointer location."""
    return json.dumps(inputs.mouse_location())


# --- entry point ------------------------------------------------------------

def selftest() -> int:
    """Read-only smoke test: i3 tree + outputs + one capture + mouse query. No clicks."""
    print(f"DISPLAY={os.environ.get('DISPLAY')!r}")
    outs = i3tree.get_outputs()
    print(f"outputs: {[o['name'] for o in outs]}")
    wins = i3tree.list_windows()
    focused = [w["title"] for w in wins if w["focused"]]
    print(f"windows: {len(wins)} (focused: {focused})")
    prim = i3tree.primary_output(outs)
    if prim:
        r = prim["rect"]
        shot = capture.capture_region(r["x"], r["y"], r["w"], r["h"], f"output {prim['name']}")
        f = shot.frame
        print(
            f"capture {prim['name']}: {f.shot_w}x{f.shot_h} scale={f.scale:.4f} "
            f"png={len(shot.png)}B region={f.as_dict()['region']}"
        )
    print(f"mouse: {inputs.mouse_location()}")
    print("selftest OK")
    return 0


def main() -> None:
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
