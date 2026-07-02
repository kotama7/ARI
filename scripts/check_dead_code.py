#!/usr/bin/env python3
"""Classify the 053/054 reference graph into dead-code candidates.

This is refactoring subtask **055** (``add_dead_code_candidate_checker``). It is
a *pure classifier / reporter*: it consumes the ``reference_graph.json`` built by
subtask 053 (static reference graph) + 054 (dynamic-edge overlay), applies the
precedence rules of
``docs/refactoring/013_reference_graph_and_dead_code_plan.md`` §7, and emits a
ranked, human-reviewable ``dead_code_candidates.md`` (013 §6.2) plus a stable
JSON form for the 058 aggregator (009 §3). It **deletes, moves, quarantines, and
renames nothing** -- quarantine is subtask 056, deletion is subtask 057, and
this checker is the only class that ever *labels* ``SAFE_DELETE_CANDIDATE``.

Why a naive import graph is dangerous here (013 §2): live code is reachable only
through string keys, filesystem paths, subprocess boundaries, and cross-language
HTTP that a Python AST import graph never records. The classifier therefore
trusts the graph's dynamic overlay and applies the 013 §7 precedence so contract
and dynamic-seam nodes can NEVER fall into ``SAFE_DELETE_CANDIDATE``:

  1. ``PUBLIC_CONTRACT``        -- MCP tools, dashboard routes, ``ari.public.*``,
                                   CLI/checkpoint/config file formats. KEEP.
  2. ``DYNAMIC_REFERENCE_RISK`` -- publish backends, prompt ``.md`` templates,
                                   reviewer rubrics, any dynamic-edge target.
  3. ``TEST_ONLY``              -- e.g. ``ari.schemas.load()`` (tests only).
  4. ``DOCS_ONLY``             -- referenced only by docs prose.
  5. ``QUARANTINE_CANDIDATE``   -- risky/large orphan -> MOVE_TO_LEGACY (056).
  6. ``SAFE_DELETE_CANDIDATE``  -- orphan, small, ruff-corroborated -> 057 only.
  7. ``REVIEW_REQUIRED``        -- the safe default; ambiguity downgrades HERE,
                                   never up to ``SAFE_DELETE_CANDIDATE``.

The **hard downgrade rule** is the safety property: a node reaches
``SAFE_DELETE_CANDIDATE`` only if it fails every liveness test AND ruff
independently flags it unused; on any doubt it is ``REVIEW_REQUIRED``. Because
054's symbol/skill/subprocess reachability is intentionally sparse, symbol
orphans inside a live module are treated as likely-live internal, and
skill-internal / subprocess orphans are ``REVIEW_REQUIRED`` (reason
``under_traced_seam``), never deletable.

Determinism (013 §6.4 / design principle P2): the report is a pure function of
the input graph -- no wall-clock in row bodies (the single top-level timestamp
is copied from the graph), stable ``id`` ordering, no LLM, no network. Two runs
on the same graph produce byte-identical output.

Exit convention (matches ``scripts/docs/check_doc_sources.py``): ``0`` = clean,
default/``--warning-only`` posture, or ``--check`` within budget; ``1`` =
net-new ``SAFE_DELETE_CANDIDATE`` over budget under ``--check``; ``2`` =
usage/environment error (missing/malformed graph, ruff not on PATH).

Design: docs/refactoring/013_reference_graph_and_dead_code_plan.md §7/§8.3;
docs/refactoring/009_quality_scripts_plan.md §5.10.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# scripts/check_dead_code.py -> parents[1] == repo root (beside readme_sync.py).
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "quality"))

# _common imports PyYAML behind its own guard (SystemExit(2) if missing), so this
# checker needs no direct ``import yaml`` -- all YAML I/O goes through _common.
import _common  # noqa: E402  (scripts/quality/_common.py -- shared infrastructure)

CHECKER_NAME = "check_dead_code"
SCHEMA_VERSION = 1
GRAPH_SCHEMA_VERSION = 1

DEFAULT_CONFIG = REPO_ROOT / "scripts" / "quality" / "check_dead_code.yaml"
DEFAULT_ALLOW = REPO_ROOT / "scripts" / "quality" / "check_dead_code.allow.yaml"

# ── classification vocabulary (013 §7) + report ranking (most-confident first)─
PUBLIC_CONTRACT = "PUBLIC_CONTRACT"
DYNAMIC_REFERENCE_RISK = "DYNAMIC_REFERENCE_RISK"
TEST_ONLY = "TEST_ONLY"
DOCS_ONLY = "DOCS_ONLY"
QUARANTINE_CANDIDATE = "QUARANTINE_CANDIDATE"
SAFE_DELETE_CANDIDATE = "SAFE_DELETE_CANDIDATE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
LIVE = "LIVE"  # production-live internal -- kept, not a candidate

# Order the candidate report groups: most-confident deletions first (013 §6.2).
CLASS_RANK = {
    SAFE_DELETE_CANDIDATE: 0,
    QUARANTINE_CANDIDATE: 1,
    REVIEW_REQUIRED: 2,
    DOCS_ONLY: 3,
    TEST_ONLY: 4,
    DYNAMIC_REFERENCE_RISK: 5,
    PUBLIC_CONTRACT: 6,
    LIVE: 7,
}

# Built-in defaults -- every key is overridable via the YAML config so the
# firewall / seam lists can be tuned without editing this script.
DEFAULT_CONFIG_VALUES: dict = {
    "graph": "docs/refactoring/reports/reference_graph.json",
    "output": "docs/refactoring/reports/dead_code_candidates.md",
    "production_roots": ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R11", "R12"],
    "test_roots": ["R9"],
    "docs_roots": ["R10"],
    "public_contract_kinds": ["mcp.tool", "route", "ts.module"],
    "public_contract_paths": [
        "ari-core/ari/public/",
        "ari-core/ari/__init__.py",
        "ari-core/ari/mcp/client.py",
        "ari-core/ari/checkpoint.py",
        "ari-core/ari/paths.py",
        "ari-core/ari/registry/app.py",
    ],
    "dynamic_seam_paths": [
        "ari-core/ari/publish/backends/",
        "ari-core/ari/prompts/",
        "ari-skill-paper-re/src/prompts/",
        "ari-skill-replicate/src/prompts/",
        "ari-core/config/reviewer_rubrics/",
        "ari-core/config/paperbench_rubrics/",
        "ari-core/config/profiles/",
        "ari-core/ari/configs/",
        "ari-core/config/workflow.yaml",
    ],
    "contract_adjacent_review_ids": [],
    "test_only_paths": [
        "ari-core/ari/schemas/__init__.py",
        "ari-core/tests/",
        "tests/",
    ],
    "docs_only_paths": [],
    "under_traced_seam_paths": [
        "ari-skill-benchmark/src/", "ari-skill-coding/src/",
        "ari-skill-evaluator/src/", "ari-skill-hpc/src/", "ari-skill-idea/src/",
        "ari-skill-memory/src/", "ari-skill-orchestrator/src/",
        "ari-skill-paper/src/", "ari-skill-paper-re/src/", "ari-skill-plot/src/",
        "ari-skill-replicate/src/", "ari-skill-transform/src/",
        "ari-skill-vlm/src/", "ari-skill-web/src/",
        "ari-core/ari/llm/cli_server.py", "ari-core/ari/memory/",
    ],
    "quarantine_paths": ["ari-core/ari/migrations/"],
    "quarantine_min_loc": 400,
    "structural_module_names": ["__init__.py", "__main__.py"],
    "safe_delete": {
        "eligible_roots": ["ari-core/ari"],
        "max_loc": 40,
        "require_ruff_corroboration": True,
    },
    "ruff": {"targets": ["ari-core"], "codes": ["F401", "F811", "F841"]},
    "check_budget": 0,
    "markdown_row_cap": 200,
}


# ─────────────────────────── data records ──────────────────────────────────


@dataclass
class Candidate:
    """One classified graph node (013 §6.2 row shape)."""

    id: str
    kind: str
    file: str
    symbol: str
    loc: int
    classification: str
    reachable_from: list[str]
    edges_in: list[str]
    evidence: list[str] = field(default_factory=list)
    rationale: str = ""
    reason: str = ""  # fine-grained sub-reason (e.g. under_traced_seam)
    allowlisted: bool = False

    @property
    def status(self) -> str:
        return "known" if self.allowlisted else "new"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "classification": self.classification,
            "kind": self.kind,
            "file": self.file,
            "symbol": self.symbol,
            "loc": self.loc,
            "reachable_from": self.reachable_from,
            "edges_in": self.edges_in,
            "evidence": self.evidence,
            "rationale": self.rationale,
            "reason": self.reason,
            "allowlisted": self.allowlisted,
            "status": self.status,
        }


# ─────────────────────────── graph loading ─────────────────────────────────


def load_graph(path: Path) -> dict:
    """Load + validate the 053/054 reference graph (013 §6.1 schema).

    Missing/malformed graph or a schema-version mismatch is a ``SystemExit(2)``
    environment error -- 055 never regenerates the graph (that is 053/054) and
    never falls back to a naive import scan (013 §2 false-positive hazard).
    """
    if not path.exists():
        sys.stderr.write(
            f"check_dead_code: reference graph not found: {path}\n"
            "  Build it first with: python scripts/analyze_references.py\n"
        )
        raise SystemExit(2)
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"check_dead_code: malformed graph {path}: {exc}\n")
        raise SystemExit(2)
    if not isinstance(graph, dict):
        sys.stderr.write(f"check_dead_code: graph {path} is not a JSON object.\n")
        raise SystemExit(2)
    if graph.get("schema_version") != GRAPH_SCHEMA_VERSION:
        sys.stderr.write(
            f"check_dead_code: unsupported graph schema_version "
            f"{graph.get('schema_version')!r} (expected {GRAPH_SCHEMA_VERSION}).\n"
        )
        raise SystemExit(2)
    for key in ("nodes", "edges", "roots"):
        if not isinstance(graph.get(key), list):
            sys.stderr.write(f"check_dead_code: graph missing required list '{key}'.\n")
            raise SystemExit(2)
    for node in graph["nodes"]:
        if not isinstance(node, dict) or "id" not in node or "kind" not in node:
            sys.stderr.write("check_dead_code: a graph node is missing id/kind.\n")
            raise SystemExit(2)
    return graph


# ─────────────────────────── ruff corroboration ────────────────────────────

_BACKTICK = re.compile(r"`([^`]+)`")


def run_ruff(targets: list[str], codes: list[str]) -> dict[str, set[str]]:
    """Return ``{file_rel: {unused symbol name, ...}}`` from ruff (F401/F811/F841).

    ruff is the authority on unused imports/locals; the graph is the authority on
    cross-module reachability (013 §8.1). ruff not being on PATH is a
    ``SystemExit(2)`` environment error -- but zero findings is NOT an error.
    """
    code_set = set(codes)
    index: dict[str, set[str]] = {}
    try:
        proc = subprocess.run(
            ["ruff", "check", *targets, "--output-format", "json"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        sys.stderr.write("check_dead_code: ruff is required on PATH (pip install ruff).\n")
        raise SystemExit(2)
    out = proc.stdout.strip()
    if not out:
        return index
    try:
        findings = json.loads(out)
    except json.JSONDecodeError:  # pragma: no cover - ruff version guard
        sys.stderr.write("check_dead_code: could not parse ruff JSON output.\n")
        raise SystemExit(2)
    for f in findings:
        if not isinstance(f, dict) or f.get("code") not in code_set:
            continue
        filename = f.get("filename") or ""
        try:
            rel = Path(filename).resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = filename
        names = index.setdefault(rel, set())
        for tok in _BACKTICK.findall(f.get("message") or ""):
            tok = tok.strip()
            if not tok:
                continue
            names.add(tok)
            names.add(tok.split(".")[-1])  # `typing.Any` -> Any
            names.add(tok.split()[0])
    return index


# ─────────────────────────── classification ────────────────────────────────


def _under(path: str, prefixes: list[str]) -> bool:
    """True if ``path`` is nested under / equal to any prefix.

    A prefix ending ``/`` is a directory match (``path.startswith(prefix)``);
    otherwise it is an exact file OR a slash-delimited directory
    (``path == prefix`` or ``path.startswith(prefix + "/")``). This avoids the
    ``ari-core/ariX`` false-positive a bare ``startswith`` would cause.
    """
    for p in prefixes:
        if not p:
            continue
        if p.endswith("/"):
            if path == p[:-1] or path.startswith(p):
                return True
        elif path == p or path.startswith(p + "/"):
            return True
    return False


def _symbol_of(node: dict) -> str:
    """Human display symbol from the node id (013 §4 id shapes)."""
    nid, kind, file = node["id"], node["kind"], node.get("file", "")
    prefix = kind + ":"
    rest = nid[len(prefix):] if nid.startswith(prefix) else nid
    if file and rest.startswith(file):
        return rest[len(file):].lstrip(":")
    return rest


class Classifier:
    """Apply the 013 §7 precedence (first match wins) to every graph node."""

    def __init__(self, config: dict, ruff_index: dict[str, set[str]]):
        self.cfg = config
        self.ruff = ruff_index
        self.prod_roots = set(config["production_roots"])
        # module-liveness lookup: a py.symbol orphan inside a production-live
        # module is likely-live internal (untraced intra-module edge), NOT a
        # candidate -- the analyzer simply did not resolve the symbol edge.
        self._module_live: dict[str, bool] = {}

    def index_modules(self, nodes: list[dict]) -> None:
        for n in nodes:
            if n["kind"] == "py.module":
                self._module_live[n["file"]] = self._is_reached(n)

    # -- liveness primitives --------------------------------------------------

    def _is_reached(self, node: dict) -> bool:
        """Referenced from any production root or by any static/dynamic edge."""
        if set(node.get("reachable_from") or []) & self.prod_roots:
            return True
        return bool(node.get("edges_in"))

    def _module_is_live(self, file: str) -> bool:
        return self._module_live.get(file, False)

    def _ruff_corroborated(self, file: str, symbol: str) -> bool:
        names = self.ruff.get(file)
        return bool(names and symbol and symbol in names)

    # -- per-rule predicates (013 §7) ----------------------------------------

    def _public_contract(self, node: dict) -> bool:
        if node["kind"] in self.cfg["public_contract_kinds"]:
            return True
        return _under(node.get("file", ""), self.cfg["public_contract_paths"])

    def _dynamic(self, node: dict) -> bool:
        if any(e.startswith(("dynamic.", "cross_lang.")) for e in node.get("edges_in", [])):
            return True
        return _under(node.get("file", ""), self.cfg["dynamic_seam_paths"])

    def _test_only(self, node: dict) -> bool:
        return _under(node.get("file", ""), self.cfg["test_only_paths"])

    def _docs_only(self, node: dict) -> bool:
        return _under(node.get("file", ""), self.cfg["docs_only_paths"])

    def _structural(self, node: dict) -> bool:
        name = node.get("file", "").rsplit("/", 1)[-1]
        return name in self.cfg["structural_module_names"]

    def _under_traced(self, node: dict) -> bool:
        return _under(node.get("file", ""), self.cfg["under_traced_seam_paths"])

    def _quarantine(self, node: dict) -> bool:
        if _under(node.get("file", ""), self.cfg["quarantine_paths"]):
            return True
        return node["kind"] == "py.module" and node.get("loc", 0) >= self.cfg["quarantine_min_loc"]

    def _safe_delete_eligible(self, node: dict) -> bool:
        sd = self.cfg["safe_delete"]
        if node["kind"] not in ("py.symbol", "py.module"):
            return False
        if not _under(node.get("file", ""), sd["eligible_roots"]):
            return False
        if node.get("loc", 0) > sd["max_loc"]:
            return False
        # A py.symbol is only eligible if its containing module is itself an
        # orphan (a dead symbol inside a live module is untraced, not dead).
        if node["kind"] == "py.symbol" and self._module_is_live(node["file"]):
            return False
        return True

    # -- the precedence engine ------------------------------------------------

    def classify(self, node: dict) -> Candidate:
        file = node.get("file", "")
        symbol = _symbol_of(node)
        loc = int(node.get("loc", 0) or 0)
        rf = list(node.get("reachable_from") or [])
        ei = list(node.get("edges_in") or [])

        def cand(cls: str, rationale: str, reason: str = "", evidence=None) -> Candidate:
            return Candidate(
                id=node["id"], kind=node["kind"], file=file, symbol=symbol,
                loc=loc, classification=cls, reachable_from=rf, edges_in=ei,
                evidence=list(evidence or []), rationale=rationale, reason=reason,
            )

        # 1. PUBLIC_CONTRACT -- KEEP, never deletable.
        if self._public_contract(node):
            return cand(PUBLIC_CONTRACT, "contract surface (MCP/route/public/file-format)")
        # 2. DYNAMIC_REFERENCE_RISK -- live-by-string, never deleted.
        if self._dynamic(node):
            ev = [f"inbound {e}" for e in ei if e.startswith(("dynamic.", "cross_lang."))]
            return cand(DYNAMIC_REFERENCE_RISK, "reached by string/path/MCP/HTTP (dynamic seam)", evidence=ev)
        # 3. contract-adjacent REVIEW_REQUIRED (entrypoint noise).
        if node["id"] in set(self.cfg["contract_adjacent_review_ids"]):
            return cand(REVIEW_REQUIRED, "entrypoint noise (unused console script)", reason="entrypoint_noise")
        # 4. TEST_ONLY.
        if self._test_only(node):
            return cand(TEST_ONLY, "reachable only from tests (R9)")
        # 5. DOCS_ONLY.
        if self._docs_only(node):
            return cand(DOCS_ONLY, "referenced only by docs prose (R10)")

        reached = self._is_reached(node)
        # Structural package/entry shells and reached nodes are live.
        if self._structural(node):
            return cand(LIVE, "structural package/entry shell (never dead)")
        if reached:
            return cand(LIVE, "referenced from a production root or by a static/dynamic edge")
        # A py.symbol orphan whose module is live is likely-live internal
        # (untraced intra-module edge), NOT a candidate (013 §7 hard downgrade).
        if node["kind"] == "py.symbol" and self._module_is_live(file):
            return cand(LIVE, "orphan symbol in a production-live module (untraced intra-module edge)")

        # From here the node is a genuine graph orphan.
        # Under-traced seams: skill-internal / subprocess helpers the 054 walk
        # does not follow. Live in reality -> REVIEW_REQUIRED, never deletable.
        if self._under_traced(node):
            return cand(
                REVIEW_REQUIRED,
                "orphan under an analyzer under-traced seam (skill-internal/subprocess); treated live",
                reason="under_traced_seam",
            )
        # 6. QUARANTINE_CANDIDATE -- MOVE_TO_LEGACY (056).
        if self._quarantine(node):
            return cand(QUARANTINE_CANDIDATE, "orphan touching migration/checkpoint code or a large module", reason="quarantine")
        # 7. SAFE_DELETE_CANDIDATE -- the only deletable class (057), gated by ruff.
        if self._safe_delete_eligible(node):
            if not self.cfg["safe_delete"]["require_ruff_corroboration"]:
                return cand(SAFE_DELETE_CANDIDATE, "orphan, small, in a static-authoritative root")
            if self._ruff_corroborated(file, symbol):
                ev = [f"ruff flags `{symbol}` unused"]
                return cand(SAFE_DELETE_CANDIDATE, "orphan + ruff-corroborated unused symbol", evidence=ev)
            # Orphan but not ruff-corroborated -> DOWNGRADE (never up).
            return cand(REVIEW_REQUIRED, "orphan without ruff corroboration (downgraded, not deletable)", reason="unresolved")
        # 8. REVIEW_REQUIRED (default) -- ambiguity downgrades here.
        return cand(REVIEW_REQUIRED, "unresolved orphan (downgraded, not deletable)", reason="unresolved")


def classify_all(graph: dict, config: dict, ruff_index: dict[str, set[str]]) -> list[Candidate]:
    clf = Classifier(config, ruff_index)
    nodes = graph["nodes"]
    clf.index_modules(nodes)
    cands = [clf.classify(n) for n in nodes]
    cands.sort(key=lambda c: (CLASS_RANK[c.classification], c.file, c.symbol, c.id))
    return cands


# ─────────────────────────── allowlist ─────────────────────────────────────


def load_allow(path: Path | None) -> tuple[set[str], dict[str, str]]:
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


def apply_allowlist(cands: list[Candidate], allow_ids: set[str]) -> None:
    for c in cands:
        if c.classification == SAFE_DELETE_CANDIDATE and c.id in allow_ids:
            c.allowlisted = True


# ─────────────────────────── reporting ─────────────────────────────────────


def summarize(cands: list[Candidate]) -> dict[str, int]:
    summary: dict[str, int] = {cls: 0 for cls in CLASS_RANK}
    for c in cands:
        summary[c.classification] += 1
    sd = [c for c in cands if c.classification == SAFE_DELETE_CANDIDATE]
    summary["safe_delete_known"] = sum(1 for c in sd if c.allowlisted)
    summary["safe_delete_new"] = sum(1 for c in sd if not c.allowlisted)
    summary["total_nodes"] = len(cands)
    summary["under_traced_seam_review"] = sum(
        1 for c in cands if c.classification == REVIEW_REQUIRED and c.reason == "under_traced_seam"
    )
    return summary


def firewall_checks(cands: list[Candidate]) -> list[tuple[str, bool, str]]:
    """The 013 §7 / 055 §13.4 verified expectations (the deletion firewall)."""
    by_id = {c.id: c for c in cands}

    def cls_of(pred) -> list[Candidate]:
        return [c for c in cands if pred(c)]

    backends = cls_of(
        lambda c: c.file.startswith("ari-core/ari/publish/backends/")
        and c.file.endswith(".py") and not c.file.endswith("__init__.py")
        and c.kind == "py.module"
    )
    prompts = cls_of(
        lambda c: c.kind == "data.file" and c.file.startswith("ari-core/ari/prompts/")
    )
    rubrics = cls_of(
        lambda c: c.kind == "data.file"
        and c.file.startswith("ari-core/config/reviewer_rubrics/")
        and c.file.endswith(".yaml")
    )
    schemas_loader = by_id.get("py.symbol:ari-core/ari/schemas/__init__.py:load")
    ari_init = by_id.get("py.module:ari-core/ari/__init__.py")
    public_init = by_id.get("py.module:ari-core/ari/public/__init__.py")
    mcp_tools = cls_of(lambda c: c.kind == "mcp.tool")
    routes = cls_of(lambda c: c.kind == "route")

    def all_dyn(items):
        return bool(items) and all(c.classification == DYNAMIC_REFERENCE_RISK for c in items)

    def all_pub(items):
        return bool(items) and all(c.classification == PUBLIC_CONTRACT for c in items)

    def notdead(c):
        return c is not None and c.classification not in (SAFE_DELETE_CANDIDATE, QUARANTINE_CANDIDATE)

    return [
        (f"publish backends DYNAMIC_REFERENCE_RISK ({len(backends)})", all_dyn(backends), "013 §7 / 055 §13.4"),
        (f"prompt templates DYNAMIC_REFERENCE_RISK ({len(prompts)})", all_dyn(prompts), "053 §3"),
        (f"reviewer rubrics DYNAMIC_REFERENCE_RISK ({len(rubrics)})", all_dyn(rubrics), "053 §3"),
        ("ari.schemas.load() TEST_ONLY", bool(schemas_loader) and schemas_loader.classification == TEST_ONLY, "053 §5"),
        ("ari/__init__.py not dead", notdead(ari_init), "013 §7"),
        ("ari/public/__init__.py not dead", notdead(public_init), "013 §7"),
        (f"MCP handlers PUBLIC_CONTRACT ({len(mcp_tools)})", all_pub(mcp_tools), "013 §7"),
        (f"viz routes PUBLIC_CONTRACT ({len(routes)})", all_pub(routes), "013 §7"),
    ]


def to_report(graph: dict, cands: list[Candidate], config: dict) -> dict:
    summary = summarize(cands)
    # Findings = every non-LIVE node (the candidate/firewall surface); LIVE nodes
    # are counted only. 058 aggregator consumes this list.
    findings = [c for c in cands if c.classification != LIVE]
    checks = firewall_checks(cands)
    return {
        "checker": CHECKER_NAME,
        "version": SCHEMA_VERSION,
        "graph": config["graph"],
        "commit": graph.get("commit"),
        "generated_at": graph.get("generated_at"),  # copied -> deterministic
        "summary": summary,
        "firewall": [{"check": n, "ok": ok, "ref": ref} for n, ok, ref in checks],
        "collisions": graph.get("collisions", []),
        "findings": [c.as_dict() for c in findings],
    }


def render_json(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, sort_keys=False)


def render_markdown(report: dict, cands: list[Candidate], config: dict) -> str:
    s = report["summary"]
    cap = int(config["markdown_row_cap"])
    lines = [
        f"# {CHECKER_NAME} — dead-code candidates",
        "",
        "> Classifier over the 053/054 reference graph "
        "(`docs/refactoring/013_reference_graph_and_dead_code_plan.md` §7). "
        "Deletes nothing — quarantine is subtask 056, deletion is subtask 057.",
        "",
        f"- commit: `{report['commit']}`",
        f"- graph: `{report['graph']}`",
        f"- generated_at (from graph): `{report['generated_at']}`",
        "",
        "## Summary (nodes per classification)",
        "",
    ]
    order = [
        SAFE_DELETE_CANDIDATE, QUARANTINE_CANDIDATE, REVIEW_REQUIRED,
        DOCS_ONLY, TEST_ONLY, DYNAMIC_REFERENCE_RISK, PUBLIC_CONTRACT, LIVE,
    ]
    rows = [[cls, str(s.get(cls, 0))] for cls in order]
    lines.append(_common.render_markdown_table(["classification", "count"], rows))
    lines += [
        "",
        f"- SAFE_DELETE_CANDIDATE: known(allowlisted)={s['safe_delete_known']} · "
        f"**new={s['safe_delete_new']}**",
        f"- REVIEW_REQUIRED of which `under_traced_seam` (analyzer coverage gap, "
        f"treated live): {s['under_traced_seam_review']}",
        f"- total nodes classified: {s['total_nodes']}",
        "",
        "## Deletion firewall (013 §7 verified expectations)",
        "",
    ]
    fw_rows = [[("PASS" if c["ok"] else "**FAIL**"), c["check"], c["ref"]] for c in report["firewall"]]
    lines.append(_common.render_markdown_table(["status", "check", "ref"], fw_rows))
    lines.append("")

    collisions = report.get("collisions") or []
    if collisions:
        lines += ["## MCP flat-namespace collisions (054 §5.3)", ""]
        crows = [[c.get("tool_name", ""), ", ".join(c.get("skills", []))] for c in collisions]
        lines.append(_common.render_markdown_table(["tool", "skills"], crows))
        lines.append("")

    # Candidate groups, most-confident deletion first.
    def group(cls: str) -> list[Candidate]:
        return [c for c in cands if c.classification == cls]

    lines += ["## Candidates (most-confident deletion first)", ""]

    for cls in (SAFE_DELETE_CANDIDATE, QUARANTINE_CANDIDATE):
        items = group(cls)
        lines += [f"### {cls} ({len(items)})", ""]
        if not items:
            lines += ["_none_", ""]
            continue
        rows = [
            [c.file, c.symbol or "—", str(c.loc), c.status, "; ".join(c.evidence) or "—", c.rationale]
            for c in items[:cap]
        ]
        lines.append(_common.render_markdown_table(
            ["file", "symbol", "loc", "status", "evidence", "rationale"], rows))
        if len(items) > cap:
            lines.append(f"\n_… {len(items) - cap} more (see JSON report)._")
        lines.append("")

    # REVIEW_REQUIRED: aggregate under_traced_seam by file (analyzer artifacts),
    # list genuine unresolved per-node.
    review = group(REVIEW_REQUIRED)
    seam = [c for c in review if c.reason == "under_traced_seam"]
    genuine = [c for c in review if c.reason != "under_traced_seam"]
    lines += [f"### REVIEW_REQUIRED ({len(review)})", ""]
    if genuine:
        lines += ["Unresolved orphans (human triage; never auto-deleted):", ""]
        rows = [
            [c.file, c.symbol or "—", str(c.loc), c.reason or "—", c.rationale]
            for c in genuine[:cap]
        ]
        lines.append(_common.render_markdown_table(
            ["file", "symbol", "loc", "reason", "rationale"], rows))
        if len(genuine) > cap:
            lines.append(f"\n_… {len(genuine) - cap} more (see JSON report)._")
        lines.append("")
    if seam:
        by_file: dict[str, int] = {}
        for c in seam:
            by_file[c.file] = by_file.get(c.file, 0) + 1
        lines += [
            f"`under_traced_seam` (skill-internal/subprocess; live but untraced by "
            f"054) — {len(seam)} nodes across {len(by_file)} files, aggregated:",
            "",
        ]
        rows = [[f, str(n)] for f, n in sorted(by_file.items())]
        lines.append(_common.render_markdown_table(["file", "orphan nodes"], rows))
        lines.append("")

    for cls in (TEST_ONLY, DOCS_ONLY):
        items = group(cls)
        lines += [f"### {cls} ({len(items)})", ""]
        if not items:
            lines += ["_none_", ""]
            continue
        rows = [[c.file, c.symbol or "—", str(c.loc), c.rationale] for c in items[:cap]]
        lines.append(_common.render_markdown_table(["file", "symbol", "loc", "rationale"], rows))
        if len(items) > cap:
            lines.append(f"\n_… {len(items) - cap} more (see JSON report)._")
        lines.append("")

    # Kept-firewall surfaces: counts only (never candidates).
    lines += [
        "## Kept surfaces (firewall — never deletion candidates)",
        "",
        f"- DYNAMIC_REFERENCE_RISK: {s[DYNAMIC_REFERENCE_RISK]} nodes "
        "(publish backends, prompt templates, rubrics/profiles/config data, "
        "MCP/HTTP dynamic targets).",
        f"- PUBLIC_CONTRACT: {s[PUBLIC_CONTRACT]} nodes "
        "(MCP tools, dashboard routes, `ari.public.*`, file-format owners).",
        f"- LIVE (referenced internal): {s[LIVE]} nodes.",
        "",
    ]
    return "\n".join(lines) + "\n"


# ─────────────────────────── --update-baseline ─────────────────────────────


def write_baseline(path: Path, cands: list[Candidate]) -> None:
    """Freeze the current SAFE_DELETE_CANDIDATE ids into ``<name>.allow.yaml``."""
    sd = sorted(c for c in {c.id for c in cands if c.classification == SAFE_DELETE_CANDIDATE})
    known = [{"id": cid, "note": "frozen SAFE_DELETE baseline (055 --update-baseline)"} for cid in sd]
    header = [
        "# Frozen allowlist / baseline for scripts/check_dead_code.py (subtask 055).",
        "#",
        "# Each `known` entry is a SAFE_DELETE_CANDIDATE node id that predates this",
        "# gate; allowlisted candidates report as `known` and never fail --check.",
        "# The set only SHRINKS as subtask 057 deletes reviewed candidates; it never",
        "# grows silently. Regenerate deliberately with --update-baseline.",
        "#",
        "# 013 §7 firewall: PUBLIC_CONTRACT / DYNAMIC_REFERENCE_RISK / TEST_ONLY",
        "# nodes are never SAFE_DELETE, so they never appear here.",
    ]
    _common.dump_yaml_with_header(path, header, {"known": known})


# ─────────────────────────── cli ───────────────────────────────────────────


def load_config(path: Path) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG_VALUES))  # deep copy of defaults
    if path and path.exists():
        data = _common.load_yaml(path)
        for key, val in data.items():
            cfg[key] = val
    # Merge nested safe_delete/ruff dicts with defaults so partial config works.
    for nested in ("safe_delete", "ruff"):
        merged = dict(DEFAULT_CONFIG_VALUES[nested])
        merged.update(cfg.get(nested) or {})
        cfg[nested] = merged
    return cfg


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--graph", default=None,
                    help="reference_graph.json input (default: config graph key)")
    ap.add_argument("--target", action="append", default=None,
                    help="restrict the ruff-corroboration scan (repeatable)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="classification config YAML (default: scripts/quality/%(prog)s.yaml)")
    ap.add_argument("--allow", default=str(DEFAULT_ALLOW),
                    help="frozen SAFE_DELETE allowlist YAML")
    ap.add_argument("--output", default=None,
                    help="write the report to a file instead of stdout "
                         "(conventional target: docs/refactoring/reports/dead_code_candidates.md)")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown",
                    help="report format (default: markdown)")
    ap.add_argument("--json", action="store_true", help="alias for --format json")
    ap.add_argument("--warning-only", action="store_true",
                    help="force exit 0 regardless of findings (default posture)")
    ap.add_argument("--check", action="store_true",
                    help="ratchet: exit 1 on net-new SAFE_DELETE over budget")
    ap.add_argument("--base-ref", default="origin/main",
                    help="diff base for --check scoping (mirrors check_ref_coupling.py)")
    ap.add_argument("--no-ruff", action="store_true",
                    help="skip ruff corroboration (offline/tests); no SAFE_DELETE promotion")
    ap.add_argument("--update-baseline", action="store_true",
                    help="regenerate the SAFE_DELETE allowlist from the current graph")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(Path(args.config))

    graph_path = Path(args.graph) if args.graph else (REPO_ROOT / config["graph"])
    graph = load_graph(graph_path)

    if args.no_ruff:
        ruff_index: dict[str, set[str]] = {}
    else:
        targets = args.target or config["ruff"]["targets"]
        ruff_index = run_ruff(targets, config["ruff"]["codes"])

    cands = classify_all(graph, config, ruff_index)
    allow_ids, _notes = load_allow(Path(args.allow) if args.allow else None)
    apply_allowlist(cands, allow_ids)

    if args.update_baseline:
        write_baseline(Path(args.allow), cands)
        sys.stderr.write(
            f"check_dead_code: wrote SAFE_DELETE baseline to {args.allow} "
            f"({sum(1 for c in cands if c.classification == SAFE_DELETE_CANDIDATE)} entries).\n"
        )
        return 0

    report = to_report(graph, cands, {**config, "graph": graph_path.as_posix()})
    fmt = "json" if args.json else args.format
    text = render_json(report) if fmt == "json" else render_markdown(report, cands, config)

    # Default to stdout (sibling-checker convention); --output names the file.
    _common.write_output(text, args.output)

    new_safe = [
        c for c in cands
        if c.classification == SAFE_DELETE_CANDIDATE and not c.allowlisted
    ]
    if args.warning_only:
        return 0
    if args.check:
        return 1 if len(new_safe) > int(config["check_budget"]) else 0
    # Default posture is warning-mode-first (009 §6): report, exit 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
