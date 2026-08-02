# Option 2 — full i3 control (BUILT: native extension)

**Status: built** as `src/i3_cua_mcp/i3control.py` (2026-08-01) — tools `launch`,
`goto_workspace`, `move_window_to_workspace`, `set_floating`, `set_layout`, and
the guarded `run_i3` escape hatch (blocks `exit`). We took **option A** (native).
The discussion below is kept for the record.

---

This note scoped the extension to full i3 *control* (move/resize/relayout/
workspaces/gaps) and weighed building it natively vs pairing with an existing i3
MCP server.

## Two ways to get there

### A. Native extension (add tools to this server)

Everything routes through one i3ipc `Connection.command(...)` call, so the code
is small. Proposed tools, each a thin wrapper over an i3 command:

| Tool | i3 command |
|------|-----------|
| `run_i3(command)` | escape hatch: run any i3 command, return per-op success |
| `move_window(con_id, target)` | `[con_id=…] move {left\|right\|up\|down\|workspace N\|to output …}` |
| `resize_window(con_id, dim, px)` | `[con_id=…] resize set …` |
| `set_layout(con_id, layout)` | `[con_id=…] layout {splith\|splitv\|tabbed\|stacking\|toggle split}` |
| `set_floating(con_id, on)` | `[con_id=…] floating {enable\|disable}` |
| `goto_workspace(name)` / `move_to_workspace(con_id, name)` | `workspace …` / `move container to workspace …` |
| `set_gaps(scope, px)` | `gaps inner/outer …` |
| `subscribe_events()` | stream window/workspace events (needs a long-lived conn + async) |

**Pros:** one server, one dependency set, shared coordinate/selftest machinery,
the same `con_id` identity used by the input tools — no impedance mismatch.
**Cons:** more surface area for a model to misuse (a stray `move to output` or
`exit` is disruptive); `run_i3` is a foot-gun worth gating or omitting.

**Guardrails if built:** allowlist command verbs (drop `exit`, `restart`,
`exec`, `shutdown`); make destructive verbs opt-in via an env flag; keep the
sandbox-first default so relayout experiments happen in Xephyr.

Estimated effort: ~an afternoon (mostly the tool docstrings + an allowlist);
`i3tree.py` already holds the `Connection`, so it slots in beside `focus_window`.

### B. Pair with `caninja/i3wm-mcp`

Run [`caninja/i3wm-mcp`](https://github.com/caninja/i3wm-mcp) alongside this
server — it already exposes workspace/layout/gaps control as MCP tools. Register
both; the model uses this one to see + click and that one to manage layout.

**Pros:** zero extra code here; keeps this server's scope tight and auditable.
**Cons:** it's self-described "vibecoded/experimental" (review before trusting);
two servers to manage; **no shared identity** — its window handles won't be our
`con_id`, so "move the window I just clicked" needs the model to re-match by
class/title across two tools. That cross-tool coordination is the real cost.

## Recommendation

If layout control is used *occasionally and interactively*, start with **B** —
nothing to build, and you can vet caninja's behavior in the sandbox. If the model
needs to *fluidly* relayout as part of a task (place this window here, tab those
two, move to the empty workspace), go **A** so it shares `con_id` identity with
the click/type tools — the coordination tax of B shows up fast. Either way, keep
the `run_i3` escape hatch gated behind an env flag and the allowlist above.
