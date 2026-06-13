#!/usr/bin/env python3
"""Validate the ``sources`` front-matter declared by docs against the tree.

Each live doc under ``docs/`` declares, in a leading YAML front-matter block,
which source files (code / config / schema / prompt / ...) it documents.  This
script verifies those declarations so that a refactor that moves or deletes a
source surfaces as a failing docs gate rather than a silently stale doc.

Design: docs/ソース対応機構設計書.md §3 (schema) / §4 (this spec).
Integration gate: docs/最終統合計画書.md §4 item 4.

Checks (any failure -> exit 1):
  1. YAML parse       front-matter, if present, is valid YAML.
  2. sources non-empty a present front-matter block declares a non-empty list.
  3. path exists      every ``sources[].path`` resolves under the repo root.
  4. role valid       ``role``, if given, is one of the known vocabulary.
  5. coverage         live (non-exempt) docs declare front-matter
                      -- enforced only with --require-all (staged rollout).

``generated: true`` without a generator-looking source emits a warning only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write(
        "check_doc_sources: PyYAML is required (pip install pyyaml).\n"
    )
    raise SystemExit(2)

# role vocabulary -- docs/ソース対応機構設計書.md §3.
VALID_ROLES = {
    "implementation",
    "schema",
    "config",
    "prompt",
    "test",
    "vendor",
    "doc",
}

# Live docs that legitimately have no `sources` -- §3 "配置ルール / 免除リスト".
# Paths are repo-root relative, posix style.  Plus everything under _archive/.
# (The reorg planning docs were removed in the [plan-deletion] commit.)
EXEMPT_FILES = {
    "docs/README.md",
    # VitePress locale home pages (navigation indexes, not sourced docs).
    "docs/index.md",
    "docs/ja/index.md",
    "docs/zh/index.md",
}
# matched as a path segment so translations (docs/ja/_archive/...) are covered too.
# node_modules / .vitepress are VitePress dependency / build artifacts.
EXEMPT_DIR_SEGMENTS = ("_archive", "node_modules", ".vitepress")

REPO_ROOT = Path(__file__).resolve().parents[2]


def is_translation(rel: str) -> bool:
    return rel.startswith("docs/ja/") or rel.startswith("docs/zh/")


def is_exempt(rel: str) -> bool:
    if rel in EXEMPT_FILES:
        return True
    parts = rel.split("/")
    return any(seg in parts for seg in EXEMPT_DIR_SEGMENTS)


def split_front_matter(text: str):
    """Return (front_matter_str or None, had_block)."""
    if not text.startswith("---"):
        return None, False
    lines = text.splitlines()
    # first line must be exactly the opening fence
    if lines[0].strip() != "---":
        return None, False
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), True
    return None, False  # unterminated fence -> treat as no front-matter


class Finding:
    __slots__ = ("doc", "level", "message")

    def __init__(self, doc: str, level: str, message: str):
        self.doc = doc
        self.level = level  # "error" | "warning" | "coverage"
        self.message = message

    def as_dict(self):
        return {"doc": self.doc, "level": self.level, "message": self.message}

    def __str__(self):
        return f"{self.doc}: [{self.level}] {self.message}"


def check_doc(path: Path, require_all: bool) -> list[Finding]:
    rel = path.relative_to(REPO_ROOT).as_posix()
    findings: list[Finding] = []
    text = path.read_text(encoding="utf-8")
    fm_str, had_block = split_front_matter(text)

    if not had_block:
        if not is_exempt(rel):
            level = "error" if require_all else "coverage"
            findings.append(
                Finding(rel, level, "no front-matter `sources` declared")
            )
        return findings

    try:
        data = yaml.safe_load(fm_str) or {}
    except yaml.YAMLError as exc:
        findings.append(Finding(rel, "error", f"invalid YAML front-matter: {exc}"))
        return findings
    if not isinstance(data, dict):
        findings.append(Finding(rel, "error", "front-matter is not a mapping"))
        return findings

    sources = data.get("sources")
    if not sources:
        if not is_exempt(rel):
            findings.append(
                Finding(rel, "error", "front-matter present but `sources` empty/missing")
            )
        return findings
    if not isinstance(sources, list):
        findings.append(Finding(rel, "error", "`sources` must be a list"))
        return findings

    paths_seen: list[str] = []
    for idx, entry in enumerate(sources):
        if not isinstance(entry, dict) or "path" not in entry:
            findings.append(
                Finding(rel, "error", f"sources[{idx}] must be a mapping with `path`")
            )
            continue
        spath = str(entry["path"])
        paths_seen.append(spath)
        if not (REPO_ROOT / spath).exists():
            findings.append(Finding(rel, "error", f"source path not found: {spath}"))
        role = entry.get("role")
        if role is not None and role not in VALID_ROLES:
            findings.append(
                Finding(rel, "error", f"invalid role '{role}' for {spath}")
            )

    if data.get("generated") is True:
        looks_generated = any(
            s.endswith(".py") or "script" in s or "generator" in s
            for s in paths_seen
        )
        if not looks_generated:
            findings.append(
                Finding(rel, "warning", "generated: true but no generator-like source listed")
            )

    return findings


def collect_docs(lang: str) -> list[Path]:
    docs_dir = REPO_ROOT / "docs"
    out = []
    for p in sorted(docs_dir.rglob("*.md")):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if lang == "en" and is_translation(rel):
            continue
        out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--lang", choices=["en", "all"], default="all",
        help="en: skip ja/zh translations; all (default): every docs/**/*.md",
    )
    parser.add_argument(
        "--require-all", action="store_true",
        help="fail if any non-exempt live doc lacks `sources` (full-rollout gate)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    findings: list[Finding] = []
    docs = collect_docs(args.lang)
    for path in docs:
        findings.extend(check_doc(path, args.require_all))

    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warning"]
    coverage = [f for f in findings if f.level == "coverage"]

    if args.json:
        print(json.dumps({
            "scanned": len(docs),
            "errors": [f.as_dict() for f in errors],
            "warnings": [f.as_dict() for f in warnings],
            "coverage": [f.as_dict() for f in coverage],
        }, ensure_ascii=False, indent=2))
    else:
        for f in errors + warnings + coverage:
            print(f)
        print(
            f"\nscanned {len(docs)} docs: "
            f"{len(errors)} error(s), {len(warnings)} warning(s), "
            f"{len(coverage)} without sources"
            + ("" if args.require_all else " (coverage not enforced)")
        )

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
