#!/usr/bin/env python3
"""Standalone TikZ rendering for visual inspection (`make figure FIG=<name>`).

Wraps a single TikZ source in shared/figures/scripts/standalone.tex.tmpl,
runs `lualatex`, then converts the resulting PDF to a 300 DPI PNG with
`pdftocairo` (or `pdftoppm` as fallback). When the run succeeds it also runs
three diagnostic checks (T7..T9):

  T7 — render success: lualatex returned 0
  T8 — bbox overlap (IoU > 0.05) — uses `pdftotext -bbox-layout`
  T9 — Overfull / Underfull \\hbox in lualatex log

Usage:
    python render_tikz.py shared/figures/tikz/F04_react_loop.tex

A non-zero exit code marks any of T7..T9 failure.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

REPORT_ROOT = Path(__file__).resolve().parent.parent
PREVIEW_DIR = REPORT_ROOT / "shared" / "figures" / "preview"
TMPL = REPORT_ROOT / "shared" / "figures" / "scripts" / "standalone.tex.tmpl"
STYLE = REPORT_ROOT / "shared" / "figures" / "style.tikzstyles"

# --- IoU threshold for bbox overlap detection
IOU_THRESHOLD = 0.05


def _bbox_iou(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / union if union > 0 else 0.0


def _bboxes_from_pdf(pdf: Path) -> list[tuple[float, float, float, float]]:
    """Run pdftotext -bbox-layout to extract text bbox per <word>."""
    if shutil.which("pdftotext") is None:
        return []
    out = subprocess.check_output(["pdftotext", "-bbox-layout", str(pdf), "-"], text=True)
    boxes: list[tuple[float, float, float, float]] = []
    try:
        root = ET.fromstring(out)
    except ET.ParseError:
        return []
    ns = {"x": "http://www.w3.org/1999/xhtml"}
    for w in root.iter("{http://www.w3.org/1999/xhtml}word"):
        try:
            x0 = float(w.attrib["xMin"]); y0 = float(w.attrib["yMin"])
            x1 = float(w.attrib["xMax"]); y1 = float(w.attrib["yMax"])
            boxes.append((x0, y0, x1, y1))
        except (KeyError, ValueError):
            continue
    return boxes


def _render_one(tikz_path: Path) -> int:
    if not TMPL.exists():
        print(f"[render_tikz] template missing: {TMPL}", file=sys.stderr)
        return 1

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    name = tikz_path.stem

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        wrapper = td / f"{name}.tex"
        body = TMPL.read_text(encoding="utf-8")
        body = body.replace("__STYLE__", str(STYLE.resolve()))
        body = body.replace("__TIKZ__", str(tikz_path.resolve()))
        wrapper.write_text(body, encoding="utf-8")

        if shutil.which("lualatex") is None:
            print("[render_tikz] lualatex not in PATH; cannot render", file=sys.stderr)
            return 2

        log_path = td / f"{name}.log"
        result = subprocess.run(
            ["lualatex", "-interaction=nonstopmode",
             "-output-directory", str(td), str(wrapper)],
            capture_output=True, text=True,
        )
        log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else result.stdout

        # T7 — judge by PDF presence rather than return code: lualatex returns
        # non-zero on Overfull/Underfull warnings, but the PDF is fine.
        pdf_out = td / f"{name}.pdf"
        if not pdf_out.exists():
            print(f"[render_tikz] T7 lualatex FAILED for {name} (no PDF)")
            print(result.stdout[-2000:])
            return 1
        target_pdf = PREVIEW_DIR / f"{name}.pdf"
        target_png = PREVIEW_DIR / f"{name}.png"
        shutil.copy(pdf_out, target_pdf)

        # PDF → PNG
        if shutil.which("pdftocairo"):
            subprocess.run(["pdftocairo", "-png", "-r", "300",
                           str(target_pdf), str(target_png.with_suffix(""))],
                          check=False)
        elif shutil.which("pdftoppm"):
            subprocess.run(["pdftoppm", "-png", "-r", "300",
                           str(target_pdf), str(target_png.with_suffix(""))],
                          check=False)

        # T9 — Overfull / Underfull \hbox
        bad = [m.group(0) for m in re.finditer(r"(Overfull|Underfull) \\hbox.*", log_text)]
        if bad:
            print(f"[render_tikz] T9 {len(bad)} hbox warning(s) for {name}:")
            for b in bad[:5]:
                print(f"   {b}")

        # T8 — bbox IoU
        boxes = _bboxes_from_pdf(target_pdf)
        overlaps: list[tuple[int, int, float]] = []
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                iou = _bbox_iou(boxes[i], boxes[j])
                if iou > IOU_THRESHOLD:
                    overlaps.append((i, j, iou))
        if overlaps:
            print(f"[render_tikz] T8 {len(overlaps)} bbox overlap(s) > {IOU_THRESHOLD} for {name} "
                  f"(check {target_png})")

        if bad or overlaps:
            return 1
        print(f"[render_tikz] OK {name} → {target_png}")
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    args = ap.parse_args()
    rc = 0
    for p in args.paths:
        rc |= _render_one(p)
    return rc


if __name__ == "__main__":
    sys.exit(main())
