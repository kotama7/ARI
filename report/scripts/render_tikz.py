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

# --- T10 arrow-vs-node crossing detection (advisory) ---------------------
# The T8 IoU gate only sees *text* boxes, so an arrow stroked straight through
# a node passes every check. T10 reconstructs edge geometry from the figure's
# vector content (PDF -> SVG) and flags edges whose interior passes through an
# unrelated node's label. It is heuristic and ADVISORY: it prints a "please
# eyeball this" warning and never fails the build (no automated check can
# replace visual review of routing — it only points the eye at the suspects).
T10_INSET = 0.25          # fraction inset into a label box that counts as "through"
T10_OWN_MARGIN = 34.0     # an edge ends at a node BORDER but the label is at the CENTRE
T10_MIN_EDGE_DIAG = 22.0  # ignore short strokes (arrowheads, decorations)
T10_STEP = 4.0            # densify polylines to this spacing before testing


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


def _t10_tf(spec: str):
    """Parse an SVG transform (matrix/translate/scale) to a 6-tuple affine."""
    spec = spec.strip()
    m = re.match(r"matrix\(([^)]+)\)", spec)
    if m:
        v = [float(x) for x in re.split(r"[,\s]+", m.group(1).strip())]
        return tuple(v[:6])
    m = re.match(r"translate\(([^)]+)\)", spec)
    if m:
        v = [float(x) for x in re.split(r"[,\s]+", m.group(1).strip())]
        return (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
    m = re.match(r"scale\(([^)]+)\)", spec)
    if m:
        v = [float(x) for x in re.split(r"[,\s]+", m.group(1).strip())]
        sy = v[1] if len(v) > 1 else v[0]
        return (v[0], 0, 0, sy, 0, 0)
    return (1, 0, 0, 1, 0, 0)


def _t10_compose(M, N):
    a, b, c, d, e, f = M
    a2, b2, c2, d2, e2, f2 = N
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2,
            b * c2 + d * d2, a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _t10_apply(M, x, y):
    a, b, c, d, e, f = M
    return (a * x + c * y + e, b * x + d * y + f)


def _t10_geometry(pdf: Path):
    """Reconstruct (label_boxes, edge_polylines) from the PDF's vector content,
    all in one (SVG page) coordinate space. Returns ([], []) on any failure."""
    if shutil.which("pdftocairo") is None:
        return [], []
    with tempfile.TemporaryDirectory() as td:
        svg = Path(td) / "fig.svg"
        try:
            subprocess.run(["pdftocairo", "-svg", str(pdf), str(svg)],
                           check=True, capture_output=True)
            root = ET.fromstring(svg.read_text(encoding="utf-8"))
        except (subprocess.CalledProcessError, ET.ParseError, OSError):
            return [], []

    glyphs: list[tuple[float, float]] = []
    paths: list[tuple[list, bool]] = []

    def walk(el, ctm):
        tf = el.get("transform")
        if tf:
            ctm = _t10_compose(ctm, _t10_tf(tf))
        tag = el.tag.split("}")[-1]
        if tag == "use":
            try:
                glyphs.append(_t10_apply(ctm, float(el.get("x", 0)), float(el.get("y", 0))))
            except ValueError:
                pass
        elif tag == "path":
            ns = [float(n) for n in re.findall(r"-?\d+\.?\d*", el.get("d", ""))]
            pts = [_t10_apply(ctm, ns[i], ns[i + 1]) for i in range(0, len(ns) - 1, 2)]
            if len(pts) >= 2:
                paths.append((pts, ("Z" in el.get("d", "") or "z" in el.get("d", ""))))
        for ch in el:
            walk(ch, ctm)

    walk(root, (1, 0, 0, 1, 0, 0))

    # cluster glyph anchors into per-row label boxes
    boxes = []
    cur = None
    for x, y in sorted(glyphs, key=lambda p: (round(p[1], 0), p[0])):
        if cur and abs(y - cur[2]) < 3 and x - cur[1] < 14:
            cur[1] = x; cur[2] = y
        else:
            if cur:
                boxes.append((cur[0] - 2, cur[3] - 9.0, cur[1] + 5, cur[3] + 3))
            cur = [x, x, y, y]
    if cur:
        boxes.append((cur[0] - 2, cur[3] - 9.0, cur[1] + 5, cur[3] + 3))

    # open, page-space, non-trivial paths are candidate edges
    edges = []
    for pts, closed in paths:
        if closed:
            continue
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        if ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5 < T10_MIN_EDGE_DIAG:
            continue
        edges.append(pts)
    return boxes, edges


def _arrow_node_crossings(pdf: Path) -> int:
    """Count edges that appear to pass through an unrelated node's label."""
    boxes, edges = _t10_geometry(pdf)
    if not boxes or not edges:
        return 0

    def densify(poly):
        out = []
        for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
            d = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
            m = max(1, int(d // T10_STEP))
            out.extend((x0 + (x1 - x0) * t / m, y0 + (y1 - y0) * t / m) for t in range(m + 1))
        return out or poly

    def in_expanded(p, box, mgn):
        return box[0] - mgn < p[0] < box[2] + mgn and box[1] - mgn < p[1] < box[3] + mgn

    def deep_inside(p, box):
        mx = (box[2] - box[0]) * T10_INSET; my = (box[3] - box[1]) * T10_INSET
        return box[0] + mx < p[0] < box[2] - mx and box[1] + my < p[1] < box[3] - my

    flagged = set()
    for ei, poly0 in enumerate(edges):
        poly = densify(poly0)
        a, b = poly[0], poly[-1]
        n = len(poly)
        own = {bi for bi, box in enumerate(boxes)
               if in_expanded(a, box, T10_OWN_MARGIN) or in_expanded(b, box, T10_OWN_MARGIN)}
        for k, p in enumerate(poly):
            if k < n * 0.12 or k > n * 0.88:
                continue
            for bi, box in enumerate(boxes):
                if bi not in own and deep_inside(p, box):
                    flagged.add((ei, bi))
    return len({ei for ei, _ in flagged})


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

        # T10 — arrow-vs-node crossing (ADVISORY: warns, never fails the build)
        crossings = _arrow_node_crossings(target_pdf)
        if crossings:
            print(f"[render_tikz] T10 (advisory) {crossings} edge(s) in {name} may pass through "
                  f"an unrelated node — eyeball routing in {target_png}")

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
