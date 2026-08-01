"""Screenshot capture: ImageMagick `import` -> Pillow crop/downscale -> PNG bytes.

We grab the whole X root (all outputs) once, then crop to the requested region
in Pillow. Cropping in-process (rather than asking `import` to grab a geometry)
keeps a single, well-defined source of truth for the pixel->global mapping.
"""
from __future__ import annotations

import io
import subprocess
from dataclasses import dataclass

from PIL import Image as PILImage

from .coords import CaptureFrame

# Vision-API image budget. Stay under the long-edge and total-pixel limits that
# would trigger *server-side* downsampling, so the pixels the model reasons about
# are exactly the pixels we scaled and mapped.
MAX_LONG_EDGE = 1568
MAX_PIXELS = 1_150_000


@dataclass
class Shot:
    png: bytes
    frame: CaptureFrame


def _grab_root() -> PILImage.Image:
    """Grab the entire X root window (all outputs) as a Pillow image."""
    proc = subprocess.run(
        ["import", "-silent", "-window", "root", "png:-"],
        capture_output=True,
        check=True,
    )
    return PILImage.open(io.BytesIO(proc.stdout)).convert("RGB")


def _fit_scale(w: int, h: int) -> float:
    """Largest scale <= 1.0 that fits both the long-edge and total-pixel budgets."""
    scale = min(1.0, MAX_LONG_EDGE / max(w, h))
    if w * h * scale * scale > MAX_PIXELS:
        scale = (MAX_PIXELS / (w * h)) ** 0.5
    return scale


def capture_region(rx: int, ry: int, rw: int, rh: int, label: str) -> Shot:
    """Capture the global-X rectangle (rx,ry,rw,rh), downscaled to the API budget."""
    root = _grab_root()

    # Clamp the crop box to the real framebuffer to avoid Pillow padding.
    x0, y0 = max(0, rx), max(0, ry)
    x1 = min(root.width, rx + rw)
    y1 = min(root.height, ry + rh)
    crop = root.crop((x0, y0, x1, y1))
    cw, ch = crop.size

    scale = _fit_scale(cw, ch)
    if scale < 1.0:
        crop = crop.resize(
            (max(1, round(cw * scale)), max(1, round(ch * scale))),
            PILImage.LANCZOS,
        )

    buf = io.BytesIO()
    crop.save(buf, format="PNG", optimize=True)

    frame = CaptureFrame(
        region_x=x0,
        region_y=y0,
        region_w=cw,
        region_h=ch,
        scale=scale,
        shot_w=crop.width,
        shot_h=crop.height,
        label=label,
    )
    return Shot(png=buf.getvalue(), frame=frame)
