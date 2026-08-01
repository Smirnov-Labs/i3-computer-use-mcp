#!/usr/bin/env bash
# Start a sandboxed nested X (Xephyr) + nested i3 + a throwaway xterm.
#
# The MCP server, when run with DISPLAY pointed here (default :1), drives THIS
# nested desktop — not your real :0 session. Everything it can click, type, or
# focus is confined to this window. Close it (Ctrl-C) to tear the sandbox down.
set -euo pipefail

DISP="${1:-:1}"
RES="${XEPHYR_RES:-1280x800}"
HERE="$(cd "$(dirname "$0")" && pwd)"

cleanup() { [[ -n "${XEPHYR_PID:-}" ]] && kill "$XEPHYR_PID" 2>/dev/null || true; }
trap cleanup EXIT

echo "Starting Xephyr on ${DISP} (${RES})..."
Xephyr "$DISP" -screen "$RES" -ac -br -resizeable -no-host-grab \
    -title "i3-cua sandbox (${DISP})" &
XEPHYR_PID=$!
sleep 1

echo "Starting nested i3 + xterm on ${DISP}..."
# env -u I3SOCK is essential: without it the nested i3 inherits the login i3's
# socket path and refuses to start ("Socket is already in use").
env -u I3SOCK DISPLAY="$DISP" i3 -c "$HERE/i3.config" &
sleep 1
# Explicit face, NOT the generic "monospace" alias: on this box fontconfig maps
# monospace -> Noto Color Emoji (no ISO-8859-1 metrics) and xterm refuses to start.
DISPLAY="$DISP" xterm -fa "DejaVu Sans Mono" -fs 11 -geometry 100x30 -title "sandbox-xterm" &

cat <<EOF

Sandbox ready on DISPLAY=${DISP}.
  - The bin/i3-cua-mcp wrapper already defaults to :1, so it targets this.
  - To selftest against it:   DISPLAY=${DISP} uv run i3-cua-mcp --selftest
  - Ctrl-C here tears it all down.
EOF

wait "$XEPHYR_PID"
