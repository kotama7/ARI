#!/usr/bin/env python3
"""Bundle-weight budget gate for the dashboard SPA build.

Formalizes the CI-provable half of the dashboard performance budgets: bundle
weight is measurable headless from the committed ``npm run build`` output, so it
becomes a scripts checker; browser metrics (LCP/INP/CLS) stay deferred, and
docs/guides/gui_cutover_runbook.md "2. Pre-cutover checklist" carries that split
as a hand-signed gate. The budgets below and the reasoning behind each class are
documented in docs/guides/testing.md "What gets tested at PR time".

Measured surface: ``ari-core/ari/viz/static/dist/assets/*.js`` (the build Vite
emits into the served static tree). Each chunk is gzip-compressed in-process
and compared against its class budget:

  * **entry**  — the ``<script type="module">`` chunk(s) referenced by
    ``dist/index.html`` — ≤ **100 KiB** gzip.
  * **route**  — lazy route chunks, filename ``<Name>Page-<hash>.js`` — ≤
    **150 KiB** gzip each (final budget);
    ``SettingsPage``/``WizardPage`` are tightened to ≤ **50 KiB** each.
  * **shared** — every other ``.js`` chunk (vendor splits, locale dictionaries,
    shared components) — ≤ **150 KiB** gzip each. Only route chunks were ever
    budgeted individually; extending the same cap to shared chunks is a
    deliberate conservative superset (largest shared chunk today: zoom at
    ~15 KiB) so a mis-split vendor bundle cannot hide outside the route class.
  * **total** — sum of all ``.js`` gzip sizes — ≤ **600 KiB**.

TOTAL BUDGET RATIONALE (600 KiB): the 2026-07-26 build totals ~261 KiB gzip
across 46 chunks (main 59.4 KiB). 600 KiB ≈ 2.3× headroom covers the planned
G4-G6 growth (Workflow Studio, Config Studio, Governance/lineage views) while
still catching the failure mode this aggregate uniquely guards: per-chunk
budgets cannot see a dependency duplicated across many chunks or a slow fleet
of new sub-budget chunks. It is a ratchet ceiling, not a target — tighten it
at G6 once the surface is complete.

MEASUREMENT PROTOCOL: ``gzip.compress(data, compresslevel=6, mtime=0)`` —
level 6 is the zlib default that Vite's build reporter uses, so numbers here
stay comparable with the bundle baselines recorded in g0_review_record.md
(index 69.91 → Wave 4d diet → 60.72 kB Vite-style decimal kB). Budgets are
expressed in KiB (1024 bytes), matching the budget table in
docs/guides/testing.md "What gets tested at PR time". ``mtime=0`` keeps
the output byte-identical across runs (P2 determinism).

Finding ids are content-hash independent (``bundle:<class>:<stem>`` where
``<stem>`` strips the trailing ``-<8-char Vite hash>``), so an allowlist entry
survives rebuilds. Per-chunk measurements are ALWAYS emitted (in the JSON
``summary.chunks`` and the Markdown table); ``Finding`` records are reserved
for budget violations so ``--fail-on-regression`` keeps the family's ratchet
semantics (findings == violations, allowlist == accepted debt).

Determinism (design principle P2): stdlib + PyYAML only — no LLM, no network,
and no node/npm (the checker reads the already-built dist; it never builds).

Exit convention (matches the scripts/quality family): ``0`` = clean, default /
``--warning-only`` posture, or ``--fail-on-regression`` with no net-new
finding; ``1`` = net-new finding under ``--fail-on-regression``; ``2`` =
usage/environment error (missing PyYAML, missing dist directory — an absent
build is an environment problem, not a budget regression).
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import re
import sys
from pathlib import Path

# scripts/check_bundle_budget.py -> parents[1] == repo root (top-level
# scripts/ checker level, same as check_dashboard_ux.py:86).
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = REPO_ROOT / "ari-core" / "ari" / "viz" / "static" / "dist"
DEFAULT_CONFIG = REPO_ROOT / "scripts" / "quality" / "check_bundle_budget.yaml"
DEFAULT_ALLOW = REPO_ROOT / "scripts" / "quality" / "check_bundle_budget.allow.yaml"

CHECKER_NAME = "check_bundle_budget"
SCHEMA_VERSION = 1

KIB = 1024

# Default budgets (KiB gzip); scripts/quality/check_bundle_budget.yaml overrides.
DEFAULT_BUDGETS = {
    "entry_kib": 100,   # the index.html module chunk(s)
    "route_kib": 150,   # each lazy route chunk (final budget)
    "shared_kib": 150,  # conservative superset (see module docstring)
    "total_kib": 600,   # derived aggregate ceiling (see rationale above)
    # Per-route overrides keyed by hash-stripped stem (the tightened rows).
    "route_overrides": {"SettingsPage": 50, "WizardPage": 50},
}

# Vite chunk naming: ``<stem>-<8-char base64url hash>.js`` (hash may contain
# ``-``, e.g. StatusBadge-D-8zhWMR.js — the {8} quantifier disambiguates).
_HASHED_NAME_RE = re.compile(r"^(?P<stem>.+)-(?P<hash>[A-Za-z0-9_-]{8})\.js$")
# Lazy route chunks are the page components: ``<Name>Page-<hash>.js``.
DEFAULT_ROUTE_RE = r"^[A-Z][A-Za-z0-9]*Page$"
# The module entry chunk(s) referenced by dist/index.html.
_ENTRY_SCRIPT_RE = re.compile(
    r"<script[^>]*type=\"module\"[^>]*src=\"[^\"]*/assets/([^\"/]+\.js)\"")

GZIP_LEVEL = 6  # zlib default == Vite reporter's level (see module docstring)


def _import_common():
    """Load scripts/quality/_common.py without a package (avoids E402).

    Mirrors check_dashboard_ux.py / check_viz_api_schema.py; the import also
    triggers _common's SystemExit(2) PyYAML guard.
    """
    common_path = REPO_ROOT / "scripts" / "quality" / "_common.py"
    spec = importlib.util.spec_from_file_location("quality_common", common_path)
    if spec is None or spec.loader is None:  # pragma: no cover - env guard
        sys.stderr.write(
            "check_bundle_budget: cannot locate scripts/quality/_common.py\n")
        raise SystemExit(2)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_common = _import_common()
Finding = _common.Finding


# ── measurement ──────────────────────────────────────────────────────────────


def gzip_size(path: Path, level: int = GZIP_LEVEL) -> int:
    """Deterministic gzip size in bytes (fixed level, mtime=0 → stable header)."""
    return len(gzip.compress(path.read_bytes(), compresslevel=level, mtime=0))


def chunk_stem(name: str) -> str:
    """Hash-independent chunk identity: strip the trailing ``-<8-char>`` hash.

    ``index-XMaqroN9.js`` -> ``index``; ``StatusBadge-D-8zhWMR.js`` ->
    ``StatusBadge``; an unhashed name falls back to its basename sans ``.js``.
    """
    m = _HASHED_NAME_RE.match(name)
    if m:
        return m.group("stem")
    return name[:-3] if name.endswith(".js") else name


def entry_chunk_names(dist: Path) -> list[str]:
    """Chunk filenames referenced as ``<script type="module">`` by index.html."""
    index_html = dist / "index.html"
    if not index_html.exists():
        return []
    return _ENTRY_SCRIPT_RE.findall(index_html.read_text(encoding="utf-8"))


def classify(name: str, entries: set[str], route_re: re.Pattern) -> str:
    if name in entries:
        return "entry"
    if route_re.match(chunk_stem(name)):
        return "route"
    return "shared"


def budget_kib_for(cls: str, stem: str, budgets: dict) -> int:
    if cls == "entry":
        return int(budgets["entry_kib"])
    if cls == "route":
        override = (budgets.get("route_overrides") or {}).get(stem)
        return int(override) if override is not None else int(budgets["route_kib"])
    return int(budgets["shared_kib"])


# ── collection ───────────────────────────────────────────────────────────────


def measure_chunks(dist: Path, budgets: dict, route_re: re.Pattern) -> list[dict]:
    """Per-chunk measurement rows for every ``assets/*.js`` (sorted by size)."""
    entries = set(entry_chunk_names(dist))
    rows: list[dict] = []
    assets = dist / "assets"
    for path in sorted(assets.glob("*.js")):
        cls = classify(path.name, entries, route_re)
        stem = chunk_stem(path.name)
        gz = gzip_size(path)
        budget = budget_kib_for(cls, stem, budgets)
        rows.append({
            "name": path.name,
            "stem": stem,
            "class": cls,
            "raw_bytes": path.stat().st_size,
            "gzip_bytes": gz,
            "gzip_kib": round(gz / KIB, 1),
            "budget_kib": budget,
            "within": gz <= budget * KIB,
        })
    rows.sort(key=lambda r: (-r["gzip_bytes"], r["name"]))
    return rows


def collect_findings(dist: Path, chunks: list[dict], budgets: dict) -> list[Finding]:
    findings: list[Finding] = []
    dist_rel = _rel(dist)

    if not entry_chunk_names(dist):
        findings.append(Finding(
            id="bundle:entry:unresolved", severity="error",
            file=_rel(dist / "index.html"), line=0, kind="entry-unresolved",
            message=("no <script type=\"module\"> asset reference found in "
                     "dist/index.html — cannot identify the entry chunk"),
        ))

    for row in chunks:
        if row["within"]:
            continue
        kind = f"{row['class']}-over-budget"
        findings.append(Finding(
            id=f"bundle:{row['class']}:{row['stem']}", severity="error",
            file=f"{dist_rel}/assets/{row['name']}", line=0, kind=kind,
            message=(f"{row['class']} chunk {row['name']} is "
                     f"{row['gzip_kib']} KiB gzip, over its "
                     f"{row['budget_kib']} KiB budget"),
        ))

    total = sum(r["gzip_bytes"] for r in chunks)
    total_budget = int(budgets["total_kib"])
    if total > total_budget * KIB:
        findings.append(Finding(
            id="bundle:total:js", severity="error",
            file=f"{dist_rel}/assets", line=0, kind="total-over-budget",
            message=(f"total JS is {round(total / KIB, 1)} KiB gzip, over the "
                     f"{total_budget} KiB aggregate budget"),
        ))
    return findings


# ── config / allowlist ───────────────────────────────────────────────────────


def load_config(path: Path) -> dict:
    cfg = {
        "dist": str(DEFAULT_DIST),
        "budgets": {**DEFAULT_BUDGETS,
                    "route_overrides": dict(DEFAULT_BUDGETS["route_overrides"])},
        "route_regex": DEFAULT_ROUTE_RE,
    }
    if path and path.exists():
        data = _common.load_yaml(path)
        if data.get("dist"):
            raw = Path(str(data["dist"]))
            cfg["dist"] = str(raw if raw.is_absolute() else REPO_ROOT / raw)
        budgets = data.get("budgets") or {}
        if isinstance(budgets, dict):
            overrides = budgets.pop("route_overrides", None)
            cfg["budgets"].update(budgets)
            if isinstance(overrides, dict):
                cfg["budgets"]["route_overrides"] = dict(overrides)
        if data.get("route_regex"):
            cfg["route_regex"] = str(data["route_regex"])
    return cfg


def load_allow(path: Path | None) -> set[str]:
    """Frozen baseline ids (mirrors check_dashboard_ux.load_allow; empty today —
    every budget is green, so no allow.yaml file is seeded)."""
    ids: set[str] = set()
    if path is None or not path.exists():
        return ids
    data = _common.load_yaml(path)
    for entry in data.get("known", []) or []:
        if isinstance(entry, str):
            ids.add(entry)
        elif isinstance(entry, dict) and entry.get("id"):
            ids.add(entry["id"])
    return ids


# ── findings / reporting ─────────────────────────────────────────────────────


def apply_allowlist(findings: list[Finding], allow_ids: set[str]) -> list[Finding]:
    for f in findings:
        f.allowlisted = f.id in allow_ids
    findings.sort(key=lambda f: (f.kind, f.id))
    return findings


def build_report(target_rel: str, chunks: list[dict],
                 findings: list[Finding], budgets: dict) -> dict:
    total = sum(r["gzip_bytes"] for r in chunks)
    by_class: dict[str, int] = {}
    for r in chunks:
        by_class[r["class"]] = by_class.get(r["class"], 0) + 1
    summary = {
        "total": len(findings),
        "known": sum(1 for f in findings if f.allowlisted),
        "new": sum(1 for f in findings if not f.allowlisted),
        "chunk_count": len(chunks),
        "chunks_by_class": by_class,
        "total_js_gzip_bytes": total,
        "total_js_gzip_kib": round(total / KIB, 1),
        "budgets_kib": {k: v for k, v in budgets.items() if k != "route_overrides"},
        "route_overrides_kib": dict(budgets.get("route_overrides") or {}),
        "chunks": chunks,
    }
    return json.loads(_common.emit_json(
        CHECKER_NAME, SCHEMA_VERSION, target_rel, summary, findings))


def render_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"# {CHECKER_NAME}",
        "",
        f"Target: `{report['target']}`",
        "",
        f"- findings: **{s['total']}**  (known: {s['known']}  ·  new: **{s['new']}**)",
        (f"- total JS: **{s['total_js_gzip_kib']} KiB gzip** across "
         f"{s['chunk_count']} chunks (budget {s['budgets_kib']['total_kib']} KiB)"),
        (f"- budgets (KiB gzip): entry ≤ {s['budgets_kib']['entry_kib']}, route ≤ "
         f"{s['budgets_kib']['route_kib']}, shared ≤ {s['budgets_kib']['shared_kib']}"
         + (f", overrides: {s['route_overrides_kib']}"
            if s["route_overrides_kib"] else "")),
        "",
    ]
    if not report["findings"]:
        lines.append("All chunks and the aggregate total are within budget.")
    else:
        headers = ["Kind", "Severity", "Finding", "Location", "Status"]
        rows = [[f["kind"], f["severity"], f"`{f['id']}`", f"`{f['file']}`",
                 "known" if f["allowlisted"] else "**new**"]
                for f in report["findings"]]
        lines.append(_common.render_markdown_table(headers, rows))
    lines += ["", "## Per-chunk measurements", ""]
    headers = ["Chunk", "Class", "gzip KiB", "Budget KiB", "Within"]
    rows = [[r["name"], r["class"], f"{r['gzip_kib']}", f"{r['budget_kib']}",
             "yes" if r["within"] else "**NO**"] for r in s["chunks"]]
    lines.append(_common.render_markdown_table(headers, rows))
    return "\n".join(lines) + "\n"


# ── cli ──────────────────────────────────────────────────────────────────────


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dist", default=None,
                    help="built dist root (default: ari-core/ari/viz/static/dist)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="budget config YAML (default: scripts/quality/check_bundle_budget.yaml)")
    ap.add_argument("--allow", default=str(DEFAULT_ALLOW),
                    help="frozen allowlist YAML (missing file -> empty allowlist)")
    ap.add_argument("--output", default=None,
                    help="write the report to a file instead of stdout")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown",
                    help="report format (default: markdown)")
    ap.add_argument("--json", action="store_true", help="alias for --format json")
    ap.add_argument("--warning-only", action="store_true",
                    help="force exit 0 regardless of findings")
    ap.add_argument("--fail-on-regression", action="store_true",
                    help="exit 1 only on findings not in the allowlist (ratchet)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    cfg = load_config(Path(args.config))
    dist = Path(args.dist).resolve() if args.dist else Path(cfg["dist"]).resolve()
    if not (dist / "assets").is_dir():
        sys.stderr.write(
            f"check_bundle_budget: dist assets dir not found: {dist}/assets "
            f"(run `npm run build` in ari-core/ari/viz/frontend first)\n")
        raise SystemExit(2)

    route_re = re.compile(cfg["route_regex"])
    allow_ids = load_allow(Path(args.allow) if args.allow else None)

    chunks = measure_chunks(dist, cfg["budgets"], route_re)
    findings = apply_allowlist(
        collect_findings(dist, chunks, cfg["budgets"]), allow_ids)
    report = build_report(_rel(dist), chunks, findings, cfg["budgets"])

    fmt = "json" if args.json else args.format
    text = json.dumps(report, indent=2, ensure_ascii=False) if fmt == "json" \
        else render_markdown(report)
    _common.write_output(text.rstrip("\n"), args.output)

    if args.warning_only:
        return 0
    if args.fail_on_regression:
        return 1 if any(not f.allowlisted for f in findings) else 0
    # Warning-mode-first family posture: report, exit 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
