"""Compares CI screenshots against the golden images in .github/ci/golden.

Usage: compare_screenshots.py SCREENSHOT_DIR GOLDEN_DIR

A pixel counts as changed when any channel differs by more than CHANNEL_TOLERANCE. An example
fails when more than PIXEL_TOLERANCE of its pixels changed. For each example with changes, a
diff image (changed pixels in magenta over a dimmed golden) is written next to the screenshots.
Each result becomes a GitHub annotation. Exits non-zero if any example fails.

To accept new output, copy the screenshots from the `ci-screenshots` branch into
.github/ci/golden.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Small per-channel noise is allowed so dithering or driver rounding doesn't fail CI.
CHANNEL_TOLERANCE = 8
# Fraction of pixels allowed to change beyond CHANNEL_TOLERANCE.
PIXEL_TOLERANCE = 0.001


def load(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)


def main() -> int:
    shots, golden = Path(sys.argv[1]), Path(sys.argv[2])
    failed = False
    for shot_path in sorted(shots.glob("*.png")):
        name = shot_path.stem
        if name.startswith("diff-"):
            continue
        golden_path = golden / shot_path.name
        if not golden_path.exists():
            print(f"::warning::{name}: no golden image; add {shot_path.name} to {golden}")
            continue

        shot, ref = load(shot_path), load(golden_path)
        if shot.shape != ref.shape:
            print(f"::error::{name}: size {shot.shape[1]}x{shot.shape[0]} differs from golden {ref.shape[1]}x{ref.shape[0]}")
            failed = True
            continue

        delta = np.abs(shot - ref).max(axis=2)
        changed = delta > CHANNEL_TOLERANCE
        fraction = changed.mean()
        summary = f"{name}: {changed.sum()} pixels ({fraction:.4%}) changed, max channel delta {delta.max()}"

        if changed.any():
            diff = (ref // 3).astype(np.uint8)
            diff[changed] = (255, 0, 255)
            Image.fromarray(diff).save(shots / f"diff-{name}.png")

        if fraction > PIXEL_TOLERANCE:
            print(f"::error::{summary} (limit {PIXEL_TOLERANCE:.2%})")
            failed = True
        else:
            print(f"::notice::{summary}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
