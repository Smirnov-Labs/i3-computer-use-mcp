# Build notes — what we did and how

A record of how this server came to be, so future-us remembers the reasoning and
the verification, not just the code.

## Goal

Let an MCP client (Claude Code) drive the **whole** X11 desktop on hexane —
screenshot on its own, click UI elements, type — not just a browser. i3-aware,
because a tiling WM with a three-output framebuffer makes blind pixel-guessing a
bad bet.

## Prior-art check (before building)

Searched for an existing X11 + i3-tree computer-use MCP. The two halves exist,
but not the clean combination:

- **`caninja/i3wm-mcp`** — real i3 IPC control (workspaces/layout/gaps), but *no*
  screenshots or pixel clicking, and self-described "vibecoded/experimental."
- **`agent-sh/computer-use-linux`** — screenshot + click + compositor-aware
  *including* i3 IPC, but Wayland-first, X11 "best-effort," and its own docs say
  i3 window list/focus is degraded. Screenshot path leans on GNOME/portals.
- Generic X11 servers (Baltes, felipethecosta, zavora) do vision+click but are
  blind to the i3 tree.

Conclusion: worth building a focused X11 + i3-tree server. We did borrow ideas —
Baltes' coordinate-scaling to fit API image limits, and agent-sh's lesson that
input lands in the wrong window unless you target explicitly (which the i3 tree
fixes).

## Decisions

- **Python + uv** (i3ipc is cleanest here; matches the user's tooling), pinned to
  3.12 to avoid system-Python 3.14 wheel gaps.
- **Xephyr-sandboxed first** — the server is `$DISPLAY`-configurable; a nested
  `:1` X server is the default so it can't touch the real desktop until trusted.
- **Scope = read + focus + input.** Full i3 control scoped separately
  (`DESIGN-i3-control-extension.md`).

## How we verified (evidence, not assertions)

1. **Read-only selftest on live `:0`** — i3 tree + outputs + one primary-output
   capture (3840×2160 → 1430×804 @ scale 0.372) + mouse query. No clicks.
2. **Sandbox isolation** — with `$I3SOCK` still pointing at `:0`, the server
   resolved the *nested* `:1` socket, saw only the `default` output, and never
   the real windows. This is the check that caught the fail-open i3ipc bug.
3. **Coordinate mapping** — `move_mouse` to a screenshot-center landed the
   pointer at the exact expected global pixel.
4. **Full input loop in the sandbox** — `click` focused a target, and
   `focus_window` → `type_text` → `key("Return")` drove a sandboxed shell to
   create a proof file.
5. **MCP stdio transport** — a real client did `initialize` + `tools/list` (13
   tools) + `tools/call`, confirming the `screenshot` image serializes as an
   `image` + `text` pair.
6. **Live multi-window test** — opened four tiled xterms running `top`, a `watch`
   clock, and a counter; `list_windows` reported correct 320px geometry, a
   `screenshot` showed the live output, and `click`→`key(M)` targeted and
   controlled a specific `top` instance.

Every bug in `gotchas.md` was found *during* this verification, not guessed at.

## Operational model

- Sandbox tools: MCP `i3-cua` (wrapper defaults `DISPLAY=:1`). Start the sandbox
  with `sandbox/run-xephyr.sh`.
- Live tools: MCP `i3-cua-live` (`-e I3CUA_DISPLAY=:0`) — added separately,
  realized on the next Claude Code restart.
- On `:0`, prefer read-only tools; input reflows i3 and steals focus, so treat it
  with care around live work.
