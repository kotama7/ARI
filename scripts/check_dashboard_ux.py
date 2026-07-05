#!/usr/bin/env python3
"""Guard the dashboard-UX invariants no existing gate covers (warning-mode-first).

The ARI dashboard is a React 18 + TypeScript SPA (``ari-core/ari/viz/frontend/``)
served by the stdlib ``http.server`` backend. Two UX invariants have no machine
gate today:

  (A) **React i18n key-set parity** across
      ``src/i18n/{en,ja,zh}.ts``. The only existing i18n gate,
      ``scripts/docs/check_i18n_js.py``, targets the landing-page JS
      (``docs/i18n/landing.{en,ja,zh}.js``) whose keys are *single-quoted*
      (``'key': '...'``, regex ``^\\s*'([^']+)'\\s*:`` at check_i18n_js.py:42);
      that regex matches **nothing** in the React dictionaries, which use
      **unquoted identifier keys** (``nav_home: 'Home'``, en.ts:3). So the React
      locales are unguarded. This checker mirrors ``check_i18n_js``'s
      *algorithm* (union-diff parity + duplicate detection) with a React-aware
      key regex.

      GROUNDING NOTE (verified 2026-07-01, corrects docs 000/014/067 + this
      subtask's own §1/§2/§6): the "444 vs 441 line" delta is NOT key drift.
      Parsed at key-set granularity the three dictionaries are **identical**
      (407/407/407 keys — 404 unquoted + 3 quoted ``'experiments.*'`` keys —
      zero duplicates, zero missing in any direction). The line-count
      difference is wrapped English value continuations + shorter
      localized comment text. The docs' "~387/391/391 keys" figure came from a
      value-delimiter-sensitive probe (``^\\s*[A-Za-z0-9_]+:\\s*'``) that skips
      keys whose value is not a same-line single-quoted string. This checker
      therefore reports i18n parity as **clean** today and guards only against
      *future* divergence (a key added to one locale but not the others).

  (B) **Always-on raw/debug exposure inventory** — a warning-first, line-
      independent inventory of raw dumps and unconfirmed dangerous UI
      (``dangerouslySetInnerHTML``/``innerHTML``, the ``{ } Raw`` node-JSON tab,
      ``JSON.stringify`` render dumps, the ``/api/env-keys`` secret readback, and
      the hardcoded ``confirmed: true`` SLURM auto-resubmit bypass). Each current
      hit is seeded into the frozen allowlist so today's run is clean; a NEW hit
      (a fresh raw dump, or a re-exposure after 070/071 gate the known ones)
      trips ``--fail-on-regression``. These surfaces are **REVIEW_REQUIRED**,
      owned by 070 (developer-mode gate) and 071 (dangerous-op hardening); this
      checker only *detects* — it never gates, hides, or removes anything.

  (C) **Route <-> nav parity** (advisory) — extract the ``PAGE_MAP`` route keys
      from ``App.tsx`` and the ``NAV_ITEMS`` keys from ``Layout/Sidebar.tsx`` and
      report routes with no nav entry that are not on the hidden-route allowlist
      (the ``paperbench/*`` sub-routes + the ``new``->``wizard`` alias target).

It **guards**, never **redefines**, the dashboard UX / i18n contract (preserved
per docs/refactoring/010_contract_preservation_policy.md §4/§5/§9-D). "deprecated"
is reserved for external contracts; a flagged raw dump is a "REVIEW_REQUIRED
candidate for developer-mode gating", never "deprecated".

Determinism (design principle P2): stdlib + PyYAML only. No LLM, no network, and
crucially **no** ``node``/``npm``/``pnpm`` — the ``*.ts``/``*.tsx`` files are
parsed statically in Python (``pnpm`` is not installed; ``npm`` is used only by
the separate Vitest suite that carries the behavioral half of these checks).
NOT wired into any workflow here (CI integration is the workflow-integration
track's job, subtask 046); intended future job: a warning-first step in an
additive dashboard/UX-hygiene workflow.

Design: docs/refactoring/014_dashboard_ux_refactoring_plan.md §14 (the
``check_dashboard_ux.py`` design row) + §13 (a11y/i18n acceptance);
docs/refactoring/000_master_refactoring_plan.md §8 ST-12-6;
docs/refactoring/009_quality_scripts_plan.md §3/§6/§8 (common CLI/allowlist/exit
contract, warning-mode-first rollout, ``scripts/quality/`` + ``_common.py``);
docs/refactoring/subtasks/073_add_dashboard_ux_regression_checks.md (§7 design,
§13 acceptance); consumes the frozen settings baseline in
docs/refactoring/reports/067_dashboard_visible_settings_inventory.md.

Exit convention (matches scripts/docs/check_doc_sources.py + the scripts/quality/
family): ``0`` = clean, default/``--warning-only`` posture, or
``--fail-on-regression`` with no net-new finding; ``1`` = net-new finding under
``--fail-on-regression``; ``2`` = usage/environment error (missing PyYAML,
missing target file/dir).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

# scripts/check_dashboard_ux.py -> parents[1] == repo root (top-level scripts/
# checker level, per 009 §8 / readme_sync.py:31); NOT parents[2] (scripts/docs/).
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FRONTEND = REPO_ROOT / "ari-core" / "ari" / "viz" / "frontend" / "src"
DEFAULT_CONFIG = REPO_ROOT / "scripts" / "quality" / "check_dashboard_ux.yaml"
DEFAULT_ALLOW = REPO_ROOT / "scripts" / "quality" / "check_dashboard_ux.allow.yaml"

CHECKER_NAME = "check_dashboard_ux"
SCHEMA_VERSION = 1

# React dictionaries use mostly UNQUOTED identifier keys (``nav_home: 'Home'``),
# which check_i18n_js.py's quoted-key regex cannot see, plus a few QUOTED keys
# (``'experiments.lineage': 'Lineage'``, en.ts:352-354). This regex captures both
# so the extracted set matches the runtime ``Object.keys`` (407 today), not just
# the 404 unquoted ones. Comment/header/brace/keyword lines are filtered
# separately.
I18N_KEY_RE = re.compile(
    r"^\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_$][\w$]*))\s*:"
)
# Identifiers that open a non-key statement in these files (header / re-export).
_NON_KEY_IDENTS = frozenset(
    {"const", "let", "var", "export", "import", "default", "function",
     "return", "interface", "type", "enum", "class"}
)

DEFAULT_LANGS = ("en", "ja", "zh")

# Default raw/dangerous-exposure patterns (subtask §2/§7.3(B)/§17). Each spec is
# ``{kind, scope, regex}``; ``scope`` is a subpath under the frontend root ("."
# = whole tree). Findings are keyed line-independently as ``<kind>::<repo-rel
# file>`` so the allowlist survives the 070/071 refactors that move these lines.
DEFAULT_RAW_PATTERNS = (
    {"kind": "dangerous_html", "scope": ".",
     "regex": r"dangerouslySetInnerHTML|\.innerHTML\s*="},
    {"kind": "raw_json_tab", "scope": ".", "regex": r"\{ \} Raw"},
    {"kind": "env_secret_readback", "scope": ".",
     "regex": r"getEnvKeys\b|/api/env-keys"},
    {"kind": "confirm_bypass", "scope": ".", "regex": r"confirmed:\s*true"},
    # JSON.stringify is scoped to the render tree (components/) so that benign
    # request-body serialization in services/api.ts is not miscounted as a dump.
    {"kind": "json_dump", "scope": "components", "regex": r"JSON\.stringify\("},
)

DEFAULT_ROUTE_NAV = {
    "app_file": "App.tsx",
    "sidebar_file": "components/Layout/Sidebar.tsx",
    # Routes intentionally reachable without a sidebar entry (App.tsx:37/47-56).
    "hidden_routes": ["wizard", "paperbench/import", "paperbench/run",
                      "paperbench/results"],
}

_SCAN_EXTS = (".ts", ".tsx")
_SKIP_DIR_SEGMENTS = frozenset({"__tests__", "node_modules", "dist", ".vite"})


def _import_common():
    """Load scripts/quality/_common.py without a package (avoids E402).

    Mirrors check_viz_api_schema.py / check_complexity.py. The import also
    triggers _common's own SystemExit(2) PyYAML guard, satisfying the house-style
    requirement that a missing PyYAML exits 2 (like check_doc_sources.py:29-35).
    """
    common_path = REPO_ROOT / "scripts" / "quality" / "_common.py"
    spec = importlib.util.spec_from_file_location("quality_common", common_path)
    if spec is None or spec.loader is None:  # pragma: no cover - env guard
        sys.stderr.write(
            "check_dashboard_ux: cannot locate scripts/quality/_common.py\n"
        )
        raise SystemExit(2)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_common = _import_common()
Finding = _common.Finding


# ── (A) i18n key-set parity ──────────────────────────────────────────────────


def i18n_keys_of(text: str) -> list[str]:
    """Extract unquoted-identifier dictionary keys from a React i18n ``.ts`` file.

    Skips ``//``/``/*``/``*`` comment lines, the ``const X: Record<...> = {``
    header, the closing brace, and ``export``/``import`` statement openers. This
    is the gap ``check_i18n_js.py`` cannot cover (its regex assumes quoted keys).
    """
    out: list[str] = []
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith(("//", "/*", "*", "}", "]")):
            continue
        m = I18N_KEY_RE.match(raw)
        if not m:
            continue
        key = m.group(1) or m.group(2) or m.group(3)
        if key in _NON_KEY_IDENTS:
            continue
        out.append(key)
    return out


def duplicates(keys: list[str]) -> list[str]:
    """Keys that appear more than once, in first-seen order (mirrors check_i18n_js)."""
    seen: set[str] = set()
    dups: list[str] = []
    for k in keys:
        if k in seen and k not in dups:
            dups.append(k)
        seen.add(k)
    return dups


def i18n_parity_findings(i18n_dir: Path, langs: tuple[str, ...]) -> list[Finding]:
    """Union-diff parity + duplicate detection over ``i18n/{lang}.ts`` (check A)."""
    findings: list[Finding] = []
    files = {lang: i18n_dir / f"{lang}.ts" for lang in langs}
    missing_files = [lang for lang, p in files.items() if not p.exists()]
    if missing_files:
        for lang in missing_files:
            findings.append(Finding(
                id=f"i18n:{lang}.ts:missing-file", severity="error",
                file=_rel(files[lang]), line=0, kind="i18n-missing-file",
                message=f"i18n dictionary {lang}.ts does not exist",
            ))
        return findings

    keys = {lang: i18n_keys_of(files[lang].read_text(encoding="utf-8"))
            for lang in langs}
    sets = {lang: set(keys[lang]) for lang in langs}
    union: set[str] = set().union(*sets.values()) if sets else set()
    for lang in langs:
        for dup in duplicates(keys[lang]):
            findings.append(Finding(
                id=f"i18n:{lang}.ts:duplicate:{dup}", severity="warning",
                file=_rel(files[lang]), line=0, kind="i18n-duplicate",
                message=f"{lang}.ts declares duplicate key {dup!r}",
            ))
        for miss in sorted(union - sets[lang]):
            findings.append(Finding(
                id=f"i18n:{lang}.ts:missing:{miss}", severity="warning",
                file=_rel(files[lang]), line=0, kind="i18n-missing-key",
                message=(f"{lang}.ts is missing key {miss!r} present in another "
                         f"locale (renders as blank/fallback)"),
            ))
    return findings


# ── (B) always-on raw/debug exposure inventory ───────────────────────────────


def _iter_source_files(root: Path):
    """Yield ``*.ts``/``*.tsx`` files under ``root``, skipping tests/build dirs."""
    for path in sorted(root.rglob("*")):
        if path.suffix not in _SCAN_EXTS or not path.is_file():
            continue
        if any(seg in _SKIP_DIR_SEGMENTS for seg in path.parts):
            continue
        yield path


def raw_dump_findings(frontend: Path, patterns) -> list[Finding]:
    """Line-independent per-file inventory of the raw/dangerous patterns (check B).

    A finding's ``id`` is ``<kind>::<repo-rel file>`` (never line-keyed) so it
    survives the 070/071 refactors; the first matching line is recorded in the
    ``line``/``message`` for human triage only.
    """
    findings: list[Finding] = []
    seen: set[str] = set()
    for spec in patterns:
        kind = spec["kind"]
        rx = re.compile(spec["regex"])
        scope = spec.get("scope", ".")
        scope_root = frontend if scope in (".", "", None) else frontend / scope
        if not scope_root.exists():
            continue
        for path in _iter_source_files(scope_root):
            first_line = _first_match_line(path, rx)
            if first_line is None:
                continue
            fid = f"{kind}::{_rel(path)}"
            if fid in seen:
                continue
            seen.add(fid)
            findings.append(Finding(
                id=fid, severity="warning", file=_rel(path), line=first_line,
                kind=kind,
                message=(f"{kind}: always-on raw/dangerous surface "
                         f"(REVIEW_REQUIRED; owned by 070/071)"),
            ))
    return findings


def _first_match_line(path: Path, rx: re.Pattern) -> int | None:
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if rx.search(line):
            return i
    return None


# ── (C) route <-> nav parity (advisory) ──────────────────────────────────────

_PAGE_MAP_KEY_RE = re.compile(r"^\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_$][\w$]*))\s*:")
_NAV_KEY_RE = re.compile(r"(?<![A-Za-z])key\s*:\s*'([^']+)'")


def _extract_block(text: str, anchor: str, close: str) -> str:
    start = text.find(anchor)
    if start == -1:
        return ""
    end = text.find(close, start)
    return text[start:end] if end != -1 else text[start:]


def page_map_keys(app_text: str) -> list[str]:
    """Route keys declared in ``const PAGE_MAP ... = { ... }`` (App.tsx)."""
    block = _extract_block(app_text, "PAGE_MAP", "};")
    keys: list[str] = []
    for line in block.splitlines():
        m = _PAGE_MAP_KEY_RE.match(line)
        if not m:
            continue
        key = m.group(1) or m.group(2) or m.group(3)
        if key in _NON_KEY_IDENTS or key == "PAGE_MAP":
            continue
        keys.append(key)
    return keys


def nav_item_keys(sidebar_text: str) -> list[str]:
    """``key: '...'`` values inside the ``NAV_ITEMS`` array (Sidebar.tsx)."""
    block = _extract_block(sidebar_text, "NAV_ITEMS", "];")
    return _NAV_KEY_RE.findall(block)


def route_nav_findings(frontend: Path, cfg: dict) -> list[Finding]:
    app_file = frontend / cfg.get("app_file", DEFAULT_ROUTE_NAV["app_file"])
    sidebar_file = frontend / cfg.get(
        "sidebar_file", DEFAULT_ROUTE_NAV["sidebar_file"])
    if not app_file.exists() or not sidebar_file.exists():
        return []
    hidden = set(cfg.get("hidden_routes", DEFAULT_ROUTE_NAV["hidden_routes"]))
    routes = page_map_keys(app_file.read_text(encoding="utf-8"))
    nav = set(nav_item_keys(sidebar_file.read_text(encoding="utf-8")))
    findings: list[Finding] = []
    for route in routes:
        if route in nav or route in hidden:
            continue
        findings.append(Finding(
            id=f"route-nav:{route}", severity="warning",
            file=_rel(app_file), line=0, kind="route-nav-orphan",
            message=(f"route {route!r} in PAGE_MAP has no NAV_ITEMS entry and is "
                     f"not on the hidden-route allowlist"),
        ))
    return findings


# ── config / allowlist ───────────────────────────────────────────────────────


def load_config(path: Path) -> dict:
    cfg: dict = {
        "i18n_dir": "i18n",
        "langs": list(DEFAULT_LANGS),
        "raw_patterns": [dict(p) for p in DEFAULT_RAW_PATTERNS],
        "route_nav": dict(DEFAULT_ROUTE_NAV),
    }
    if path and path.exists():
        data = _common.load_yaml(path)
        i18n = data.get("i18n") or {}
        if isinstance(i18n, dict):
            if i18n.get("dir"):
                cfg["i18n_dir"] = i18n["dir"]
            if i18n.get("langs"):
                cfg["langs"] = list(i18n["langs"])
        if isinstance(data.get("raw_patterns"), list) and data["raw_patterns"]:
            cfg["raw_patterns"] = data["raw_patterns"]
        if isinstance(data.get("route_nav"), dict):
            cfg["route_nav"] = {**cfg["route_nav"], **data["route_nav"]}
    return cfg


def load_allow(path: Path | None) -> tuple[set[str], dict[str, str]]:
    """Load the frozen baseline (mirrors check_viz_api_schema.load_allow)."""
    ids: set[str] = set()
    notes: dict[str, str] = {}
    if path is None or not path.exists():
        return ids, notes
    data = _common.load_yaml(path)
    for entry in data.get("known", []) or []:
        if isinstance(entry, str):
            ids.add(entry)
        elif isinstance(entry, dict) and entry.get("id"):
            ids.add(entry["id"])
            if entry.get("note"):
                notes[entry["id"]] = entry["note"]
    return ids, notes


# ── findings / reporting ──────────────────────────────────────────────────────


def apply_allowlist(findings: list[Finding], allow_ids: set[str]) -> list[Finding]:
    for f in findings:
        f.allowlisted = f.id in allow_ids
    findings.sort(key=lambda f: (f.kind, f.id))
    return findings


def build_report(target_rel: str, findings: list[Finding]) -> dict:
    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    known = sum(1 for f in findings if f.allowlisted)
    new = sum(1 for f in findings if not f.allowlisted)
    summary = {
        "total": len(findings),
        "known": known,
        "new": new,
        "by_kind": by_kind,
    }
    return json.loads(_common.emit_json(
        CHECKER_NAME, SCHEMA_VERSION, target_rel, summary, findings,
    ))


def render_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"# {CHECKER_NAME}",
        "",
        f"Target: `{report['target']}`",
        "",
        f"- findings: **{s['total']}**  (known: {s['known']}  ·  new: **{s['new']}**)",
    ]
    if s["by_kind"]:
        kinds = ", ".join(f"{k}={v}" for k, v in sorted(s["by_kind"].items()))
        lines.append(f"- by kind: {kinds}")
    lines.append("")
    if not report["findings"]:
        lines.append("No dashboard-UX findings: i18n locales are in key-set "
                     "parity and no new raw/dangerous surface was introduced.")
        return "\n".join(lines) + "\n"
    headers = ["Kind", "Severity", "Finding", "Location", "Status"]
    rows = []
    for f in report["findings"]:
        status = "known" if f["allowlisted"] else "**new**"
        loc = f"`{f['file']}`" + (f":{f['line']}" if f["line"] else "")
        rows.append([f["kind"], f["severity"], f"`{f['id']}`", loc, status])
    lines.append(_common.render_markdown_table(headers, rows))
    return "\n".join(lines) + "\n"


# ── cli ────────────────────────────────────────────────────────────────────────


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--frontend", default=str(DEFAULT_FRONTEND),
                    help="frontend src root (default: ari-core/ari/viz/frontend/src)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="checker config YAML (default: scripts/quality/%(prog)s.yaml)")
    ap.add_argument("--allow", default=str(DEFAULT_ALLOW),
                    help="frozen allowlist YAML (default: scripts/quality/...allow.yaml)")
    ap.add_argument("--output", default=None,
                    help="write the report to a file instead of stdout")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown",
                    help="report format (default: markdown)")
    ap.add_argument("--json", action="store_true", help="alias for --format json")
    ap.add_argument("--warning-only", action="store_true",
                    help="force exit 0 regardless of findings (rollout default posture)")
    ap.add_argument("--fail-on-regression", action="store_true",
                    help="exit 1 only on findings not in the allowlist (ratchet)")
    return ap


def collect_findings(frontend: Path, cfg: dict) -> list[Finding]:
    i18n_dir = frontend / cfg["i18n_dir"]
    findings: list[Finding] = []
    findings += i18n_parity_findings(i18n_dir, tuple(cfg["langs"]))
    findings += raw_dump_findings(frontend, cfg["raw_patterns"])
    findings += route_nav_findings(frontend, cfg["route_nav"])
    return findings


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    frontend = Path(args.frontend).resolve()
    if not frontend.is_dir():
        sys.stderr.write(f"check_dashboard_ux: frontend dir not found: {frontend}\n")
        raise SystemExit(2)

    cfg = load_config(Path(args.config))
    allow_ids, _notes = load_allow(Path(args.allow) if args.allow else None)

    findings = apply_allowlist(collect_findings(frontend, cfg), allow_ids)
    report = build_report(_rel(frontend), findings)

    fmt = "json" if args.json else args.format
    text = json.dumps(report, indent=2, ensure_ascii=False) if fmt == "json" \
        else render_markdown(report)
    _common.write_output(text.rstrip("\n"), args.output)

    if args.warning_only:
        return 0
    if args.fail_on_regression:
        return 1 if any(not f.allowlisted for f in findings) else 0
    # Warning-mode-first (009 §6 / subtask §7.6): report, exit 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
