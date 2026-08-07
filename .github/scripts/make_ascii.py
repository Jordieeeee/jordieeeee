#!/usr/bin/env python3
"""
Turn a photo into the ASCII portrait used by the profile card.

    pip install pillow numpy
    python3 .github/scripts/make_ascii.py src/assets/me/portrait.png

Writes .github/assets/portrait.txt. Re-run generate_card.py afterwards.

Tuning
------
The defaults are tuned for a low-key, single-source-lit portrait: the darkest
`--floor` percent of pixels become blank space, so the subject emerges out of
an empty background instead of being drawn as a solid silhouette. On a bright,
evenly lit photo you will want a much lower --floor (try 25-40).

    --cols    output width in characters (34 keeps the card compact)
    --floor   percentile below which pixels are blank      (default 73)
    --gamma   <1 lifts midtones, >1 crushes them           (default 0.85)
    --crop    left,right,top,bottom as fractions of the image
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / ".github" / "assets" / "portrait.txt"

# Dense-to-sparse. A short ramp reads better than a long one at small sizes:
# with 70 glyphs the eye sees texture, with 10 it sees form.
RAMP = " .:-=+*#%@"

# Character cells are about twice as tall as they are wide, so rows must be
# sampled at roughly half the rate of columns or the face comes out stretched.
CELL_ASPECT = 0.52


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=pathlib.Path)
    ap.add_argument("--cols", type=int, default=48)
    ap.add_argument("--floor", type=float, default=73.0)
    ap.add_argument("--gamma", type=float, default=0.85)
    ap.add_argument("--crop", default="0.18,0.92,0.01,0.92")
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    args = ap.parse_args()

    x0, x1, y0, y1 = (float(v) for v in args.crop.split(","))
    img = Image.open(args.image).convert("L")
    w, h = img.size
    img = img.crop((int(w * x0), int(h * y0), int(w * x1), int(h * y1)))

    cols = args.cols
    rows = max(1, int(img.size[1] / img.size[0] * cols * CELL_ASPECT))
    small = np.asarray(img.resize((cols, rows), Image.LANCZOS), dtype=np.float32)

    lo = np.percentile(small, args.floor)
    hi = np.percentile(small, 99.6)
    v = np.clip((small - lo) / max(hi - lo, 1e-6), 0, 1) ** args.gamma

    lines = [
        "".join(" " if x <= 0.001 else RAMP[min(len(RAMP) - 1, 1 + int(x * (len(RAMP) - 1)))]
                for x in row).rstrip()
        for row in v
    ]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n-> {args.out.relative_to(ROOT)} "
          f"({max(len(l) for l in lines)}x{len(lines)} chars)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
