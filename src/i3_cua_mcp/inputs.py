"""Input synthesis via xdotool. All coordinates here are *global* X pixels."""
from __future__ import annotations

import subprocess

_BUTTON = {"left": 1, "middle": 2, "right": 3}


def _run(args: list[str]) -> None:
    r = subprocess.run(["xdotool", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"xdotool {' '.join(args)} failed: {r.stderr.strip()}")


def move(gx: int, gy: int) -> None:
    _run(["mousemove", "--sync", str(gx), str(gy)])


def click(gx: int, gy: int, button: str = "left", count: int = 1) -> None:
    b = _BUTTON.get(button, 1)
    args = ["mousemove", "--sync", str(gx), str(gy), "click"]
    if count > 1:
        args += ["--repeat", str(count), "--delay", "120"]
    args.append(str(b))
    _run(args)


def drag(gx1: int, gy1: int, gx2: int, gy2: int, button: str = "left") -> None:
    b = _BUTTON.get(button, 1)
    _run(["mousemove", "--sync", str(gx1), str(gy1)])
    _run(["mousedown", str(b)])
    _run(["mousemove", "--sync", str(gx2), str(gy2)])
    _run(["mouseup", str(b)])


def scroll(gx: int, gy: int, direction: str = "down", amount: int = 3) -> None:
    # X buttons 4/5 are wheel up/down.
    b = 5 if direction == "down" else 4
    _run(
        ["mousemove", "--sync", str(gx), str(gy),
         "click", "--repeat", str(max(1, amount)), str(b)]
    )


def type_text(text: str) -> None:
    _run(["type", "--clearmodifiers", "--", text])


def key(keyseq: str) -> None:
    # xdotool key syntax, e.g. "ctrl+s", "Return", "Escape", "alt+Tab".
    _run(["key", "--clearmodifiers", keyseq])


def mouse_location() -> dict:
    r = subprocess.run(
        ["xdotool", "getmouselocation", "--shell"],
        capture_output=True,
        text=True,
        check=True,
    )
    d: dict = {}
    for line in r.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.lower()] = int(v) if v.lstrip("-").isdigit() else v
    return d
