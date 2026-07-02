#!/usr/bin/env python3
"""Aggregate the ``scripts/quality/*`` checker JSON into one quality report.

Design: ``docs/refactoring/009_quality_scripts_plan.md`` §5.11 (aggregator spec)
+ ``docs/refactoring/subtasks/031_add_quality_report_generator.md``.

This is the *aggregator* (subtask 031) — it **detects nothing itself**. It merges
the stable §3 JSON envelope

    {"checker": str, "version": int, "target": str,
     "summary": {...}, "findings": [{id, severity, file, line, kind,
                                     message, allowlisted}, ...]}

emitted by the sibling source-quality checkers (``check_complexity``,
``check_import_boundaries``, ``check_public_api_contracts``, ``check_prompts``,
``check_viz_api_schema``, ``check_dead_code``, …) into a single roll-up in two
forms: a human **Markdown** report and a machine **JSON** report (so the report
itself can be diffed / ratcheted). The only self-computed numbers are per-area
LOC (a trivial stdlib newline walk) which reproduce
``docs/refactoring/reports/001_complexity_baseline.md`` (viz 8131, public 148,
core 30277, skills-src 25495).

Graceful degradation is the core requirement: at delivery most Phase-8 checkers
do not exist yet, so a missing checker / missing JSON / unparseable JSON /
unsupported schema version is recorded as ``unavailable``/``error`` and the run
continues. A valid report is produced from **zero** available checkers.

Determinism (design principle P2): stdlib + PyYAML only (PyYAML solely for the
YAML config, guarded via ``scripts/quality/_common.py``), no LLM, no network.
House style mirrors ``scripts/docs/`` (``argparse``, ``--json``/``--format json``,
``REPO_ROOT`` via ``parents[N]``, ``SystemExit(2)`` on environment error).

Exit convention (matches ``scripts/docs/``):
  ``0`` = clean / ``--warning-only``; ``1`` = net-new findings vs ``--baseline``
  under ``--fail-on-regression``; ``2`` = usage / environment error.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# scripts/generate_quality_report.py -> parents[1] == repo root (top-level
# scripts/ checker level, per 009 §8 / readme_sync.py:31); NOT parents[2].
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "scripts" / "quality" / "generate_quality_report.yaml"

REPORT_NAME = "quality"
REPORT_VERSION = 1
SUPPORTED_INPUT_VERSIONS = {1}
DEFAULT_TIMEOUT = 180

# ── dead-code section (subtask 058) ──────────────────────────────────────────
# Fold scripts/check_dead_code.py's 013 §7 classification counts into the roll-up
# and compute a before/after delta vs a frozen pre-057 snapshot so subtask 057's
# deletion is auditable (013 §9 step 5 / §6.3; subtask 058 §7.2/§7.3). The seven
# buckets are the 013 §7 vocabulary; LIVE is the checker's internal live class and
# is not a candidate bucket, so it is excluded here (recorded in the baseline).
DEAD_CODE_CHECKER = "check_dead_code"
DEAD_CODE_CLASSES = (
    "SAFE_DELETE_CANDIDATE",
    "QUARANTINE_CANDIDATE",
    "TEST_ONLY",
    "DOCS_ONLY",
    "DYNAMIC_REFERENCE_RISK",
    "PUBLIC_CONTRACT",
    "REVIEW_REQUIRED",
)
DEFAULT_DEAD_CODE_BASELINE = (
    REPO_ROOT / "docs" / "refactoring" / "reports" / "dead_code_baseline.json"
)


def _import_common():
    """Load ``scripts/quality/_common.py`` without a package (avoids E402).

    Mirrors ``scripts/check_complexity.py`` / ``check_viz_api_schema.py``. The
    import triggers ``_common``'s own ``SystemExit(2)`` PyYAML guard, satisfying
    the house-style requirement that a missing PyYAML exits 2 (like
    ``scripts/docs/check_doc_sources.py:29-35``).
    """
    common_path = REPO_ROOT / "scripts" / "quality" / "_common.py"
    spec = importlib.util.spec_from_file_location("quality_common", common_path)
    if spec is None or spec.loader is None:  # pragma: no cover - env guard
        sys.stderr.write(
            "generate_quality_report: cannot locate scripts/quality/_common.py\n"
        )
        raise SystemExit(2)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_common = _import_common()


# ── config ──────────────────────────────────────────────────────────────────


@dataclass
class CheckerSpec:
    """One configured checker: how to find / invoke it and read its JSON."""

    name: str
    path: str = ""
    argv: list[str] = field(default_factory=list)
    json_flag: list[str] = field(default_factory=lambda: ["--format", "json"])
    weight: float = 1.0
    required: bool = False


@dataclass
class Config:
    checkers: list[CheckerSpec]
    areas: list[str] | None  # repo-relative dir paths; None => auto-discover


def load_config(path: Path, explicit: bool) -> Config:
    """Parse the aggregator config.

    A missing *explicit* ``--config`` is an environment error (exit 2); a missing
    *default* config degrades to a zero-checker report so a bare run still works.
    """
    if not path.exists():
        if explicit:
            sys.stderr.write(f"generate_quality_report: config not found: {path}\n")
            raise SystemExit(2)
        return Config(checkers=[], areas=None)

    data = _common.load_yaml(path)  # raises SystemExit(2) if not a mapping
    specs: list[CheckerSpec] = []
    for entry in data.get("checkers") or []:
        if not isinstance(entry, dict) or "name" not in entry:
            continue
        jf = entry.get("json_flag") or ["--format", "json"]
        specs.append(
            CheckerSpec(
                name=str(entry["name"]),
                path=str(entry.get("module_or_path") or entry.get("path") or ""),
                argv=[str(a) for a in (entry.get("argv") or [])],
                json_flag=[str(a) for a in jf],
                weight=float(entry.get("weight", 1.0)),
                required=bool(entry.get("required", False)),
            )
        )
    areas = data.get("areas")
    area_list = [str(a) for a in areas] if isinstance(areas, list) and areas else None
    return Config(checkers=specs, areas=area_list)


# ── checker result + collection (graceful degradation) ───────────────────────


@dataclass
class CheckerResult:
    name: str
    status: str  # "ok" | "unavailable" | "error"
    reason: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    weight: float = 1.0

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def allowlisted_count(self) -> int:
        return sum(1 for f in self.findings if f.get("allowlisted"))


def _ingest_payload(spec: CheckerSpec, payload: Any) -> CheckerResult:
    """Validate a parsed §3 payload; tolerate a missing (but not an unknown) version."""
    if not isinstance(payload, dict):
        return CheckerResult(spec.name, "error", "payload is not a JSON object",
                             weight=spec.weight)
    version = payload.get("version")
    if version is not None and version not in SUPPORTED_INPUT_VERSIONS:
        return CheckerResult(spec.name, "error", f"schema v{version} unsupported",
                             weight=spec.weight)
    summary = payload.get("summary")
    findings = payload.get("findings")
    return CheckerResult(
        spec.name,
        "ok",
        summary=summary if isinstance(summary, dict) else {},
        findings=[f for f in findings if isinstance(f, dict)]
        if isinstance(findings, list)
        else [],
        weight=spec.weight,
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_from_target(spec: CheckerSpec, target: Path) -> CheckerResult:
    """Read ``<target>/<name>.json`` (fallback: any *.json whose ``checker`` matches)."""
    chosen: Path | None = None
    candidate = target / f"{spec.name}.json"
    if candidate.exists():
        chosen = candidate
    else:
        for jf in sorted(target.glob("*.json")):
            try:
                data = _read_json(jf)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("checker") == spec.name:
                chosen = jf
                break
    if chosen is None:
        return CheckerResult(spec.name, "unavailable",
                             f"no JSON for {spec.name} in {target}", weight=spec.weight)
    try:
        payload = _read_json(chosen)
    except (OSError, json.JSONDecodeError) as exc:
        return CheckerResult(spec.name, "error",
                             f"unparseable JSON ({chosen.name}): {exc}", weight=spec.weight)
    return _ingest_payload(spec, payload)


def collect_by_running(spec: CheckerSpec, timeout: int) -> CheckerResult:
    """Invoke the checker as a subprocess and parse its JSON stdout."""
    if not spec.path:
        return CheckerResult(spec.name, "error", "no module_or_path configured",
                             weight=spec.weight)
    script = REPO_ROOT / spec.path
    if not script.exists():
        return CheckerResult(spec.name, "unavailable",
                             f"checker not found: {spec.path}", weight=spec.weight)
    cmd = [sys.executable, str(script), *spec.argv, *spec.json_flag]
    try:
        proc = subprocess.run(
            cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:  # pragma: no cover - interpreter guard
        return CheckerResult(spec.name, "unavailable", "interpreter/script not found",
                             weight=spec.weight)
    except subprocess.TimeoutExpired:
        return CheckerResult(spec.name, "error", f"timeout after {timeout}s",
                             weight=spec.weight)
    if proc.returncode not in (0, 1):
        return CheckerResult(spec.name, "error",
                             f"exit {proc.returncode}: {proc.stderr.strip()[:200]}",
                             weight=spec.weight)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return CheckerResult(spec.name, "error", f"unparseable stdout JSON: {exc}",
                             weight=spec.weight)
    return _ingest_payload(spec, payload)


def collect(
    specs: list[CheckerSpec], target: Path | None, run_checkers: bool, timeout: int
) -> list[CheckerResult]:
    results: list[CheckerResult] = []
    for spec in specs:
        if target is not None:
            results.append(collect_from_target(spec, target))
        elif run_checkers:
            results.append(collect_by_running(spec, timeout))
        else:
            results.append(
                CheckerResult(spec.name, "unavailable",
                              "no input (pass --target <dir> or --run-checkers)",
                              weight=spec.weight)
            )
    return results


# ── per-area LOC (self-computed; matches 001) ────────────────────────────────


def _loc_of_py_tree(d: Path) -> int:
    total = 0
    for p in d.rglob("*.py"):
        if not p.is_file():
            continue
        parts = p.parts
        if "__pycache__" in parts or "node_modules" in parts:
            continue
        try:
            total += p.read_text(encoding="utf-8", errors="replace").count("\n")
        except OSError:  # pragma: no cover - fs guard
            continue
    return total


def discover_areas(repo_root: Path) -> list[str]:
    """Auto-discover areas: each ari-core/ari subdir + every ari-skill-*/src."""
    areas: list[str] = []
    core = repo_root / "ari-core" / "ari"
    if core.is_dir():
        for sub in sorted(core.iterdir()):
            if sub.is_dir() and sub.name != "__pycache__":
                areas.append(sub.relative_to(repo_root).as_posix())
    for skill in sorted(repo_root.glob("ari-skill-*")):
        src = skill / "src"
        if src.is_dir():
            areas.append(src.relative_to(repo_root).as_posix())
    return areas


def _rel_finding_path(repo_root: Path, raw: Any) -> str:
    fp = str(raw or "").replace("\\", "/")
    root = str(repo_root)
    if fp.startswith(root):
        fp = fp[len(root):]
    return fp.lstrip("./")


def compute_areas(
    repo_root: Path, area_globs: list[str] | None, results: list[CheckerResult]
) -> list[dict[str, Any]]:
    area_rels = list(area_globs) if area_globs else discover_areas(repo_root)
    # Longest-first so a finding under ari-core/ari/viz is not stolen by ari-core/ari.
    ordered = sorted(set(area_rels), key=len, reverse=True)
    counts: dict[str, int] = {a: 0 for a in area_rels}
    for res in results:
        if res.status != "ok":
            continue
        for f in res.findings:
            fp = _rel_finding_path(repo_root, f.get("file"))
            if not fp:
                continue
            for a in ordered:
                if fp == a or fp.startswith(a + "/"):
                    counts[a] += 1
                    break
    rows: list[dict[str, Any]] = []
    for a in area_rels:
        d = repo_root / a
        rows.append(
            {"area": a, "loc": _loc_of_py_tree(d) if d.is_dir() else 0,
             "finding_count": counts.get(a, 0)}
        )
    return rows


# ── merge + render ───────────────────────────────────────────────────────────


def _baseline_ids(baseline: Any) -> set[tuple[str, str]]:
    ids: set[tuple[str, str]] = set()
    if not isinstance(baseline, dict):
        return ids
    for ck in baseline.get("checkers") or []:
        if not isinstance(ck, dict):
            continue
        name = str(ck.get("checker", ""))
        for f in ck.get("findings") or []:
            if isinstance(f, dict):
                ids.add((name, str(f.get("id", ""))))
    return ids


# ── dead-code rollup (subtask 058) ────────────────────────────────────────────


def _dead_code_baseline_counts(payload: Any) -> dict[str, int]:
    """Per-classification counts from a frozen snapshot or a raw checker report.

    Accepts either the compact ``docs/refactoring/reports/dead_code_baseline.json``
    snapshot (a ``by_classification`` mapping) or, for robustness, a raw
    ``check_dead_code --format json`` report (whose ``summary`` carries the same
    per-classification counts).
    """
    if not isinstance(payload, dict):
        return {}
    src = payload.get("by_classification")
    if not isinstance(src, dict):
        src = payload.get("summary")
    if not isinstance(src, dict):
        return {}
    counts: dict[str, int] = {}
    for cls, val in src.items():
        # bool is an int subclass in Python; exclude it explicitly.
        if isinstance(val, bool) or not isinstance(val, int):
            continue
        counts[str(cls)] = val
    return counts


def load_dead_code_baseline(
    path_str: str | None,
) -> tuple[dict[str, int] | None, str | None]:
    """Load the frozen pre-057 dead-code snapshot (058 §7.3).

    A missing/unreadable snapshot degrades to ``(None, None)`` so the dead-code
    section still renders (without a delta). Never raises.
    """
    path = Path(path_str) if path_str else DEFAULT_DEAD_CODE_BASELINE
    if not path.exists():
        return None, None
    try:
        payload = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(
            f"generate_quality_report: dead-code baseline unreadable ({exc}); "
            "proceeding without a delta\n"
        )
        return None, None
    counts = _dead_code_baseline_counts(payload)
    return counts, _rel_finding_path(REPO_ROOT, str(path)) or str(path)


def build_dead_code(
    results: list[CheckerResult],
    baseline_counts: dict[str, int] | None,
    baseline_path: str | None,
) -> dict[str, Any]:
    """Fold check_dead_code's classification counts + a before/after delta.

    Groups the checker's ``findings[]`` by their ``classification`` field into
    the seven 013 §7 buckets and computes ``delta = current - baseline`` per
    class (058 §7.2). Renders even when the checker is absent / unparseable
    (all-zero counts, ``status: unavailable``/``error``) so the dead-code
    section never crashes the aggregator (031 graceful-degradation policy).
    """
    result = next((r for r in results if r.name == DEAD_CODE_CHECKER), None)
    by_class = {c: 0 for c in DEAD_CODE_CLASSES}
    if result is None:
        status, reason = "unavailable", "check_dead_code not configured"
    else:
        status, reason = result.status, result.reason
        if status == "ok":
            for f in result.findings:
                cls = str(f.get("classification", ""))
                if cls in by_class:
                    by_class[cls] += 1
    # Headline: SAFE_DELETE candidates still awaiting deletion (013 §6.2).
    safe_delete_new = by_class["SAFE_DELETE_CANDIDATE"]
    if result is not None and isinstance(result.summary.get("safe_delete_new"), int):
        safe_delete_new = int(result.summary["safe_delete_new"])

    delta: dict[str, int] = {}
    if status == "ok" and baseline_counts is not None:
        delta = {
            c: by_class[c] - int(baseline_counts.get(c, 0)) for c in DEAD_CODE_CLASSES
        }

    return {
        "status": status,
        "reason": reason,
        "by_classification": by_class,
        "baseline": baseline_path,
        "baseline_available": baseline_counts is not None,
        "delta": delta,
        "safe_delete_new": safe_delete_new,
    }


def merge(
    results: list[CheckerResult],
    areas: list[dict[str, Any]],
    baseline: Any,
    baseline_path: str | None,
    generated_at: str,
    repo_root: Path,
    dead_code: dict[str, Any],
) -> dict[str, Any]:
    have_baseline = baseline is not None
    base_ids = _baseline_ids(baseline)

    new_findings: list[dict[str, Any]] = []
    if have_baseline:
        for res in results:
            if res.status != "ok":
                continue
            for f in res.findings:
                if f.get("allowlisted"):
                    continue  # known debt (per checker allowlist) is never net-new
                if (res.name, str(f.get("id", ""))) not in base_ids:
                    new_findings.append(
                        {
                            "checker": res.name,
                            "id": f.get("id"),
                            "severity": f.get("severity"),
                            "file": f.get("file"),
                            "line": f.get("line"),
                            "kind": f.get("kind"),
                            "message": f.get("message"),
                        }
                    )

    checkers_json: list[dict[str, Any]] = []
    total_findings = 0
    for res in results:
        if res.status == "ok":
            total_findings += res.finding_count
        n_new = sum(1 for nf in new_findings if nf["checker"] == res.name)
        checkers_json.append(
            {
                "checker": res.name,
                "status": res.status,
                "reason": res.reason,
                "weight": res.weight,
                "summary": res.summary,
                "finding_count": res.finding_count,
                "allowlisted_count": res.allowlisted_count,
                "new_vs_baseline": n_new,
                # Embed the §3 findings so this roll-up is a valid --baseline input.
                "findings": res.findings,
            }
        )

    run = sum(1 for r in results if r.status == "ok")
    unavailable = sum(1 for r in results if r.status != "ok")
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "generated_at": generated_at,
        "repo_root": str(repo_root),
        "checkers": checkers_json,
        "areas": areas,
        "dead_code": dead_code,
        "totals": {
            "checkers_run": run,
            "checkers_unavailable": unavailable,
            "findings": total_findings,
            "new_vs_baseline": len(new_findings),
        },
        "regression": {
            "baseline": baseline_path if have_baseline else None,
            "new_findings": new_findings,
        },
    }


def render_json(model: dict[str, Any]) -> str:
    return json.dumps(model, indent=2, ensure_ascii=False)


def _dead_code_markdown(dc: dict[str, Any]) -> list[str]:
    """Render the dead-code subsection (058 §7.2): seven 013 §7 buckets + delta."""
    if not dc:
        return []
    lines = ["", "## Dead code", ""]
    lines.append(
        f"- Source: {DEAD_CODE_CHECKER} (status: {dc.get('status', 'unavailable')})"
    )
    if dc.get("reason"):
        lines.append(f"- Note: {str(dc['reason'])[:80]}")
    lines.append(f"- Baseline: {dc.get('baseline') or '(none)'}")
    lines.append(
        f"- Safe-to-delete surviving human review: {dc.get('safe_delete_new', 0)}"
    )
    lines.append("")
    by_class = dc.get("by_classification") or {}
    delta = dc.get("delta") or {}
    has_delta = bool(delta)
    header = (
        ["classification", "count", "Δ vs baseline"]
        if has_delta
        else ["classification", "count"]
    )
    rows: list[list[str]] = []
    for c in DEAD_CODE_CLASSES:
        count = int(by_class.get(c, 0))
        if has_delta:
            rows.append([c, str(count), f"{int(delta.get(c, 0)):+d}"])
        else:
            rows.append([c, str(count)])
    lines.append(_common.render_markdown_table(header, rows))
    return lines


def render_markdown(model: dict[str, Any]) -> str:
    t = model["totals"]
    lines = [
        "# Quality Report",
        "",
        f"- Generated (UTC): {model['generated_at']}",
        f"- Repo: {model['repo_root']}",
        f"- Checkers: {t['checkers_run']} run, {t['checkers_unavailable']} unavailable",
        f"- Findings: {t['findings']} total; {t['new_vs_baseline']} net-new vs baseline",
        "",
        "## Checkers",
        "",
    ]
    crows = [
        [
            ck["checker"],
            ck["status"],
            str(ck["finding_count"]),
            str(ck["allowlisted_count"]),
            str(ck["new_vs_baseline"]),
            (ck["reason"] or "")[:60],
        ]
        for ck in model["checkers"]
    ]
    lines.append(
        _common.render_markdown_table(
            ["checker", "status", "findings", "allowlisted", "Δ new", "note"], crows
        )
    )
    lines += ["", "## Areas", ""]
    arows = [[a["area"], str(a["loc"]), str(a["finding_count"])] for a in model["areas"]]
    lines.append(_common.render_markdown_table(["area", "LOC", "findings"], arows))

    lines += _dead_code_markdown(model.get("dead_code") or {})

    nf = model["regression"]["new_findings"]
    if nf:
        lines += ["", "## New since baseline", ""]
        nrows = [
            [
                x["checker"],
                str(x.get("id", "")),
                str(x.get("severity", "")),
                f"{x.get('file', '')}:{x.get('line', '')}",
            ]
            for x in nf
        ]
        lines.append(
            _common.render_markdown_table(
                ["checker", "id", "severity", "location"], nrows
            )
        )
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--target", default=None,
                   help="directory of pre-generated per-checker JSON files to merge")
    p.add_argument("--config", default=None,
                   help=f"aggregator config YAML (default: {DEFAULT_CONFIG})")
    p.add_argument("--output", default=None,
                   help="write the report to a file instead of stdout")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown",
                   help="report format (default: markdown)")
    p.add_argument("--json", action="store_true", help="alias for --format json")
    p.add_argument("--run-checkers", action="store_true",
                   help="invoke each configured checker (subprocess) instead of --target")
    p.add_argument("--baseline", default=None,
                   help="previous JSON roll-up to diff against for regression deltas")
    p.add_argument("--dead-code-baseline", default=None,
                   help="frozen pre-057 dead-code snapshot for the before/after "
                        f"delta (default: {DEFAULT_DEAD_CODE_BASELINE})")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"per-checker subprocess timeout, seconds (default {DEFAULT_TIMEOUT})")
    p.add_argument("--warning-only", action="store_true",
                   help="force exit 0 regardless of findings (rollout default posture)")
    p.add_argument("--fail-on-regression", action="store_true",
                   help="exit 1 only on net-new findings vs --baseline (ratchet)")
    p.add_argument("--base-ref", default="origin/main",
                   help="accepted for CLI uniformity with the checker family; unused here")
    return p


def _load_baseline(path_str: str | None) -> tuple[Any, str | None]:
    if not path_str:
        return None, None
    try:
        return _read_json(Path(path_str)), path_str
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(
            f"generate_quality_report: baseline unreadable ({exc}); "
            "proceeding without it\n"
        )
        return None, None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    cfg = load_config(config_path, explicit=args.config is not None)

    target = Path(args.target) if args.target else None
    if target is not None and not target.is_dir():
        sys.stderr.write(f"generate_quality_report: --target not a directory: {target}\n")
        raise SystemExit(2)

    baseline, baseline_path = _load_baseline(args.baseline)
    dc_baseline, dc_baseline_path = load_dead_code_baseline(args.dead_code_baseline)
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    results = collect(cfg.checkers, target, args.run_checkers, args.timeout)
    areas = compute_areas(REPO_ROOT, cfg.areas, results)
    dead_code = build_dead_code(results, dc_baseline, dc_baseline_path)
    model = merge(
        results, areas, baseline, baseline_path, generated_at, REPO_ROOT, dead_code
    )

    out_format = "json" if args.json else args.format
    text = render_json(model) if out_format == "json" else render_markdown(model)
    _common.write_output(text, args.output)

    if args.warning_only:
        return 0
    if args.fail_on_regression:
        return 1 if model["totals"]["new_vs_baseline"] > 0 else 0
    # Warning-mode-first (009 §6): report, never block by default.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
