"""Coordinate mapping between screenshot pixels and global X11 coordinates.

xdotool and the i3 tree both speak *global* X coordinates — one plane spanning
every output. Screenshots we hand the model are cropped to a single output (or
window) and downscaled to fit the vision API's image budget. This module records
the last capture's frame so the click/move/scroll tools can accept coordinates
*as measured in the screenshot the model was just shown* and translate them back
to the real screen. That indirection is the whole reason a model can reliably
click on a multi-output desktop without doing arithmetic itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class CaptureFrame:
    """The mapping from one screenshot's pixel space back to global X pixels."""

    region_x: int  # global-X origin of the captured region
    region_y: int
    region_w: int  # size of the captured region in global px (pre-scale)
    region_h: int
    scale: float  # screenshot_px = global_px * scale  (<= 1.0)
    shot_w: int  # resulting screenshot size in px
    shot_h: int
    label: str  # human label, e.g. "output DP-0" or "window 94 (Slack)"

    def to_global(self, sx: float, sy: float) -> tuple[int, int]:
        """Map a screenshot-pixel coordinate to a global X coord, clamped to region."""
        gx = self.region_x + sx / self.scale
        gy = self.region_y + sy / self.scale
        gx = min(max(gx, self.region_x), self.region_x + self.region_w - 1)
        gy = min(max(gy, self.region_y), self.region_y + self.region_h - 1)
        return int(round(gx)), int(round(gy))

    def as_dict(self) -> dict:
        return {
            "region": {
                "x": self.region_x,
                "y": self.region_y,
                "w": self.region_w,
                "h": self.region_h,
            },
            "scale": round(self.scale, 5),
            "screenshot_size": {"w": self.shot_w, "h": self.shot_h},
            "captured": self.label,
        }


_lock = Lock()
_last: CaptureFrame | None = None


def set_last(frame: CaptureFrame) -> None:
    global _last
    with _lock:
        _last = frame


def get_last() -> CaptureFrame | None:
    with _lock:
        return _last
