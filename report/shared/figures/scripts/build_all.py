#!/usr/bin/env python3
"""Regenerate all data-driven figures (PGF + dot) under shared/figures/.

Usage:
    python build_all.py            # rebuild everything
    python build_all.py --only F08 # rebuild a single figure

Idempotency: scripts seed RNGs and pin matplotlib style, so repeated runs produce
byte-identical PGF/dot output. CI uses `git diff --exit-code` after this script
to detect drift.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent.parent  # report/shared
sys.path.insert(0, str(THIS_DIR))

# (module_name, callable) — order matters only for shared caches
GENERATORS = [
    ("tree_render",   "render_tree"),       # F02
    ("rubric_render", "render_rubric"),     # F07
    ("tree_curve",    "render_curve"),      # F08
    ("rubric_dist",   "render_distribution"),  # F09
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild all data-driven figures.")
    ap.add_argument("--only", help="Run only the generator whose module contains this token (e.g. F08).")
    args = ap.parse_args()

    failures: list[str] = []
    for mod_name, fn_name in GENERATORS:
        if args.only and args.only.lower() not in mod_name.lower():
            continue
        try:
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, fn_name)
            print(f"[build_all] running {mod_name}.{fn_name}", flush=True)
            fn(out_dir=ROOT / "figures")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{mod_name}: {exc}")
            print(f"[build_all] FAILED {mod_name}: {exc}", flush=True)

    if failures:
        print(f"[build_all] {len(failures)} generator(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[build_all] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
