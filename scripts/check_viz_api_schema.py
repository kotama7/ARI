#!/usr/bin/env python3
"""Reconcile the dashboard HTTP surface with its sole consumer, ``services/api.ts``.

The ARI dashboard backend (``ari-core/ari/viz/routes.py`` + the ``api_*.py``
family + ``websocket.py``) is a bespoke stdlib ``http.server`` app whose routing
is two hand-rolled ``if/elif`` chains over ``self.path`` (no route table). Its
only consumer is the React client ``ari-core/ari/viz/frontend/src/services/
api.ts`` (four transport regimes: ``get``/``post`` throw on non-2xx,
``pbGet``/``pbPost`` never throw). Nothing today keeps the two in sync, so a
renamed/dropped endpoint on either side can silently diverge.

This checker extracts BOTH sides statically, normalizes to a canonical endpoint
identity, and simulates dispatch (a client call routes to the first matching
server branch, exactly like the runtime ``if/elif``). It reports:

  * **client-only** — a path the frontend calls that no route serves (a broken
    call; the hard-error class, promoted first once the baseline is clean);
  * **server-only** — a route served that ``services/api.ts`` never calls
    (candidate dead endpoint; most are legitimately server-only — reverse proxy,
    container ops, health probes, static assets, SSE/EventSource, direct-URL
    ``<img>``/``<a>`` deps — and belong on the allowlist);
  * **matched** — present on both sides.

It **guards** the dashboard API contract (a preserved external contract per
``docs/refactoring/010_contract_preservation_policy.md`` §4/§5); it never
renames, adds, or removes any endpoint. Drift it surfaces is resolved by the
owning viz subtask (015/021/023) or by an allowlist entry — never by "fixing" an
endpoint here. The term "deprecated" is reserved for external contracts; a
server-only route is a "candidate unused endpoint", not "deprecated".

Registry-agnostic by design: the server extractor parses the current ``if/elif``
tests via ``ast`` (equality / ``in`` / ``startswith`` / ``endswith`` /
substring / ``re.match``), and can also read a declarative ``ROUTES`` map if a
future refactor (015/021, the abandoned ``WIZARD_ROUTES`` at ``api_wizard.py:30``
is its seed) introduces one — so it survives the very refactor it guards.

Ships **warning-mode-first** (009 plan §6): default and ``--warning-only`` exit 0;
a frozen allowlist keeps the known baseline out of a future ``--fail-on-regression``
ratchet. Stdlib + PyYAML only — no LLM, no network, no ``node``/``pnpm`` (design
principle P2 determinism). NOT wired into any workflow here (CI integration is the
workflow-integration track's job); intended future job: a warning-first step in an
additive source-hygiene workflow.

Design: docs/refactoring/009_quality_scripts_plan.md §5.6 (this checker's spec) +
§3 (common CLI/allowlist/exit contract) + §8 (placement, ``scripts/quality/``,
``_common.py``); docs/refactoring/subtasks/030_add_viz_api_schema_checker_script.md
(§7 design, §13 acceptance); consumes the frozen endpoint baseline in
docs/refactoring/reports/viz_api_contract_inventory.md (020) and its FE twin
dashboard_fe_api_contract_inventory.md (060).

Exit convention (matches ``scripts/docs/check_doc_sources.py``): ``0`` = clean,
default/``--warning-only`` posture, or ``--fail-on-regression`` with no net-new
drift; ``1`` = net-new drift under ``--fail-on-regression``; ``2`` =
usage/environment error (missing PyYAML, missing target file).
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# scripts/check_viz_api_schema.py -> parents[1] == repo root (top-level scripts/
# checker level, per 009 §8 / readme_sync.py:31); NOT parents[2] (scripts/docs/).
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = REPO_ROOT / "ari-core" / "ari" / "viz"
DEFAULT_ROUTES = DEFAULT_TARGET / "routes.py"
DEFAULT_CLIENT = DEFAULT_TARGET / "frontend" / "src" / "services" / "api.ts"
DEFAULT_CONFIG = REPO_ROOT / "scripts" / "quality" / "check_viz_api_schema.yaml"
DEFAULT_ALLOW = REPO_ROOT / "scripts" / "quality" / "check_viz_api_schema.allow.yaml"

CHECKER_NAME = "check_viz_api_schema"
SCHEMA_VERSION = 1

# The four ``services/api.ts`` transport helpers -> HTTP method (009 §5.6,
# 060 §1). Overridable via config so a rename does not require a code edit.
DEFAULT_CLIENT_HELPERS: dict[str, str] = {
    "get": "GET",
    "pbGet": "GET",
    "post": "POST",
    "pbPost": "POST",
}
# A slash-free placeholder substituted for every ``${...}`` path parameter so a
# reconstructed probe stays a single path segment (matches server ``<id>`` /
# ``[^/]+`` capture groups and ``${encodeURIComponent(...)}`` interpolation).
PARAM_TOKEN = "SEG"
PARAM_DISPLAY = "{id}"


def _import_common():
    """Load ``scripts/quality/_common.py`` without a package (avoids E402).

    Mirrors ``scripts/check_complexity.py``. The import also triggers ``_common``'s
    own ``SystemExit(2)`` PyYAML guard, satisfying the house-style requirement
    that a missing PyYAML exits 2 (like ``check_doc_sources.py:29-35``).
    """
    common_path = REPO_ROOT / "scripts" / "quality" / "_common.py"
    spec = importlib.util.spec_from_file_location("quality_common", common_path)
    if spec is None or spec.loader is None:  # pragma: no cover - env guard
        sys.stderr.write(
            "check_viz_api_schema: cannot locate scripts/quality/_common.py\n"
        )
        raise SystemExit(2)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so the ``Finding`` dataclass (with ``from __future__
    # import annotations``) can resolve its own module for KW_ONLY detection.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_common = _import_common()
Finding = _common.Finding


# ── server-side extraction (routes.py if/elif dispatch) ─────────────────────


@dataclass
class ServerRoute:
    """One dispatch branch: a method + a predicate over the request path."""

    method: str
    label: str  # canonical, line-independent identity (path-shaped)
    line: int
    test: ast.AST  # the branch's ``if/elif`` test expression
    hits: int = 0  # client probes that route here (first-match)

    @property
    def id(self) -> str:
        return f"{self.method} {self.label}"

    def matches(self, path: str) -> bool | None:
        return _eval_test(self.test, path)


def _is_self_path(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "path"
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _is_urlparse_call(node: ast.AST) -> bool:
    """True for ``urllib.parse.urlparse(self.path)`` / ``urlparse(self.path)``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else (
        func.id if isinstance(func, ast.Name) else "")
    if name != "urlparse":
        return False
    return any(_is_self_path(a) for a in node.args)


def _subject(node: ast.AST) -> str | None:
    """Classify a call/compare subject as the full path or the query-stripped path."""
    if _is_self_path(node):
        return "full"
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "path"
        and _is_urlparse_call(node.value)
    ):
        return "urlpath"
    return None


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _str_or_tuple(node: ast.AST) -> tuple[str, ...] | None:
    """A string arg, or a tuple/list of string args (as ``str.startswith`` accepts)."""
    s = _const_str(node)
    if s is not None:
        return (s,)
    if isinstance(node, (ast.Tuple, ast.List)):
        parts = [_const_str(e) for e in node.elts]
        if all(p is not None for p in parts):
            return tuple(p for p in parts if p is not None)
    return None


def _subject_str(kind: str, path: str) -> str:
    if kind == "urlpath":
        return path.split("?", 1)[0].split("#", 1)[0]
    return path


def _references_self_path(node: ast.AST) -> bool:
    return any(_is_self_path(n) for n in ast.walk(node))


def _eval_test(node: ast.AST, path: str) -> bool | None:
    """Evaluate a dispatch test against a concrete ``path``.

    Returns ``True``/``False`` for recognized idioms, or ``None`` when the shape
    is unknown (conservative — an unrecognized branch never claims a match).
    """
    if isinstance(node, ast.BoolOp):
        vals = [_eval_test(v, path) for v in node.values]
        if isinstance(node.op, ast.And):
            if any(v is False for v in vals):
                return False
            return None if any(v is None for v in vals) else True
        if isinstance(node.op, ast.Or):
            if any(v is True for v in vals):
                return True
            return None if any(v is None for v in vals) else False
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = _eval_test(node.operand, path)
        return None if inner is None else (not inner)
    if isinstance(node, ast.Compare):
        return _eval_compare(node, path)
    if isinstance(node, ast.Call):
        return _eval_call(node, path)
    return None


def _eval_compare(node: ast.Compare, path: str) -> bool | None:
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    op, right = node.ops[0], node.comparators[0]
    left = node.left
    # self.path == "x"
    if _is_self_path(left) and isinstance(op, ast.Eq):
        s = _const_str(right)
        return None if s is None else (path == s)
    # self.path in ("x", "y")  /  self.path not in (...)
    if _is_self_path(left) and isinstance(op, (ast.In, ast.NotIn)):
        vals = _str_or_tuple(right)
        if vals is None:
            return None
        hit = path in set(vals)
        return hit if isinstance(op, ast.In) else (not hit)
    # "x" in self.path  /  "x" in urlparse(self.path).path
    if isinstance(op, (ast.In, ast.NotIn)):
        needle = _const_str(left)
        subj = _subject(right)
        if needle is not None and subj is not None:
            hit = needle in _subject_str(subj, path)
            return hit if isinstance(op, ast.In) else (not hit)
    return None


def _eval_call(node: ast.Call, path: str) -> bool | None:
    func = node.func
    # re.match(pattern, self.path)
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "match"
        and isinstance(func.value, ast.Name)
        and func.value.id == "re"
        and len(node.args) >= 2
    ):
        pat = _const_str(node.args[0])
        if pat is not None and _is_self_path(node.args[1]):
            try:
                return re.match(pat, path) is not None
            except re.error:  # pragma: no cover - malformed pattern
                return None
    # <subject>.startswith(...) / <subject>.endswith(...)
    if isinstance(func, ast.Attribute) and func.attr in ("startswith", "endswith"):
        subj = _subject(func.value)
        if subj is not None and node.args:
            args = _str_or_tuple(node.args[0])
            if args is not None:
                target = _subject_str(subj, path)
                if func.attr == "startswith":
                    return target.startswith(args)
                return target.endswith(args)
    return None


def _route_label(test: ast.AST) -> str:
    """A deterministic, line-independent, path-shaped identity for a branch.

    Stable across the 015/021 route-registry refactor (path-keyed, never
    line-keyed), so the allowlist survives the reorganization this checker
    guards. Built from the string literals + match kind in the test.
    """
    exacts: list[str] = []
    prefixes: list[str] = []
    suffixes: list[str] = []
    contains: list[str] = []
    regexes: list[str] = []

    for n in ast.walk(test):
        if isinstance(n, ast.Compare) and len(n.ops) == 1:
            op = n.ops[0]
            if _is_self_path(n.left) and isinstance(op, ast.Eq):
                s = _const_str(n.comparators[0])
                if s is not None:
                    exacts.append(s)
            elif _is_self_path(n.left) and isinstance(op, (ast.In, ast.NotIn)):
                vals = _str_or_tuple(n.comparators[0])
                if vals is not None:
                    exacts.extend(vals)
            elif isinstance(op, (ast.In, ast.NotIn)):
                needle = _const_str(n.left)
                if needle is not None and _subject(n.comparators[0]) is not None \
                        and isinstance(op, ast.In):
                    contains.append(needle)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in ("startswith", "endswith") and n.args:
                args = _str_or_tuple(n.args[0])
                if args is not None and _subject(n.func.value) is not None:
                    (prefixes if n.func.attr == "startswith" else suffixes).extend(args)
            elif n.func.attr == "match" and isinstance(n.func.value, ast.Name) \
                    and n.func.value.id == "re" and len(n.args) >= 2:
                pat = _const_str(n.args[0])
                if pat is not None:
                    regexes.append(pat)

    if exacts and not (prefixes or suffixes or contains or regexes):
        return "|".join(sorted(set(exacts)))
    if regexes:
        return "re:" + regexes[0]
    prefix = prefixes[0] if prefixes else ""
    tail = ""
    if suffixes:
        tail = suffixes[0] if suffixes[0].startswith("/") else "/" + suffixes[0]
    elif contains:
        tail = contains[0] if contains[0].startswith("/") else "/" + contains[0]
    if prefix:
        return prefix.rstrip("/") + "/" + PARAM_DISPLAY + tail
    if tail:
        return PARAM_DISPLAY + tail
    # Fallback: join whatever literals were found (keeps a stable, if terse, id).
    lit = exacts + prefixes + suffixes + contains
    return "|".join(sorted(set(lit))) or "<unparsed>"


def _iter_dispatch_tests(func: ast.FunctionDef):
    """Yield each ``if/elif`` test that references ``self.path``, in dispatch order.

    Handles the two independent top-level ``if`` chains in ``do_GET`` (the logo
    guard then the main chain) and skips the ``do_POST`` 413/body-length guard
    (its test does not reference ``self.path``).
    """
    for stmt in func.body:
        if not isinstance(stmt, ast.If):
            continue
        node: ast.If | None = stmt
        while node is not None:
            if _references_self_path(node.test):
                yield node.test
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                node = node.orelse[0]
            else:
                node = None


def extract_server_routes(routes_path: Path, methods: dict[str, str]) -> list[ServerRoute]:
    """Static-extract dispatch branches from ``routes.py``'s ``do_<METHOD>`` handlers."""
    src = routes_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    handler = _find_class(tree, "_Handler")
    routes: list[ServerRoute] = []
    wanted = {"do_GET": "GET", "do_POST": "POST"}
    scope = handler.body if handler is not None else tree.body
    for node in scope:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            method = wanted[node.name]
            for test in _iter_dispatch_tests(node):
                routes.append(
                    ServerRoute(method, _route_label(test), test.lineno, test)
                )
    return routes


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def parse_declarative_routes(target: Path) -> list[tuple[str, str]]:
    """Recognize a module-level ``ROUTES``/``WIZARD_ROUTES`` map, if any (015/021).

    Registry-agnostic hook: returns ``(method, path)`` pairs so the checker keeps
    working after the ``if/elif`` chain is replaced by a declarative table. Today
    the only such dict (``api_wizard.WIZARD_ROUTES``) is unused and stale, so this
    is off by default (config ``use_declarative_routes``) and returns ``[]``.
    """
    pairs: list[tuple[str, str]] = []
    for py in sorted(target.glob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if not any(n in ("ROUTES", "WIZARD_ROUTES") for n in names):
                continue
            if isinstance(node.value, ast.Dict):
                for k, v in zip(node.value.keys, node.value.values):
                    path = _const_str(k) if k is not None else None
                    method = _declared_method(v)
                    if path:
                        pairs.append((method, path))
    return pairs


def _declared_method(value: ast.AST) -> str:
    """Best-effort HTTP method for a declarative route value (defaults to GET)."""
    for n in ast.walk(value):
        s = _const_str(n)
        if s and s.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
            return s.upper()
    return "GET"


# ── client-side extraction (services/api.ts) ────────────────────────────────


@dataclass
class ClientCall:
    method: str
    canonical: str  # /api/x/{id} form, query stripped
    probe: str  # a concrete routable URL for dispatch simulation
    line: int
    raw: str

    @property
    def id(self) -> str:
        return f"{self.method} {self.canonical}"


def _read_delimited(text: str, start: int) -> tuple[str, int] | None:
    """Read a quoted or template string beginning at ``text[start]``.

    Returns ``(content, end_index)`` or ``None`` if ``text[start]`` is not a
    string delimiter. Handles ``'`` / ``"`` / backtick and backslash escapes;
    template literals may span newlines.
    """
    delim = text[start]
    if delim not in ("'", '"', "`"):
        return None
    i = start + 1
    buf: list[str] = []
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            buf.append(text[i:i + 2])
            i += 2
            continue
        if c == delim:
            return "".join(buf), i + 1
        buf.append(c)
        i += 1
    return None  # pragma: no cover - unterminated string


_CALL_RE = re.compile(r"(?<![A-Za-z0-9_$])(get|post|pbGet|pbPost)\s*(?:<[^>]*>)?\s*\(")
_FETCH_RE = re.compile(r"(?<![A-Za-z0-9_$])fetch\s*\(")
_METHOD_RE = re.compile(r"method\s*:\s*['\"]([A-Za-z]+)['\"]")
_INTERP_RE = re.compile(r"\$\{.*?\}", re.DOTALL)


def _to_probe(raw: str) -> str:
    """Reconstruct a concrete, routable URL from a client path template.

    ``${API_BASE}`` -> ``''``; ``${encodeURIComponent(x)}`` / ``${param}`` ->
    ``SEG`` (a slash-free segment); a query-value interpolation (``${q.toString()}``)
    -> ``k=v``; a conditional query fragment (``${qs}``/``${nq}``) -> ``''``.
    """
    s = raw.replace("${API_BASE}", "")

    def repl(m: re.Match) -> str:
        inner = m.group(0)[2:-1].strip()
        if "encodeURIComponent" in inner:
            return PARAM_TOKEN
        if inner in ("qs", "nq"):
            return ""
        if inner.endswith(".toString()") or "(" in inner:
            return "k=v"
        return PARAM_TOKEN

    return _INTERP_RE.sub(repl, s).strip()


def _canonical(probe: str) -> str:
    path = probe.split("?", 1)[0].split("#", 1)[0]
    return path.replace(PARAM_TOKEN, PARAM_DISPLAY)


def _line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def extract_client_calls(client_path: Path, helpers: dict[str, str]) -> list[ClientCall]:
    # ``services/api.ts`` was split (subtask 063) into a re-export barrel + a
    # ``services/api/`` subpackage (client.ts transport + per-domain modules).
    # Read the barrel AND every module so the wrapper call sites are visible;
    # falls back to the single file for a pre-split tree.
    text = client_path.read_text(encoding="utf-8")
    api_dir = client_path.parent / "api"
    if api_dir.is_dir():
        for mod in sorted(api_dir.rglob("*.ts")):
            if "__tests__" not in mod.parts:
                text += "\n" + mod.read_text(encoding="utf-8")
    calls: list[ClientCall] = []
    seen: set[tuple[str, str, int]] = set()

    def _add(method: str, raw: str, idx: int) -> None:
        probe = _to_probe(raw)
        if not probe or probe == PARAM_TOKEN:
            return  # generic helper-internal fetch (``${API_BASE}${path}``)
        canonical = _canonical(probe)
        key = (method, canonical, _line_of(text, idx))
        if key in seen:
            return
        seen.add(key)
        calls.append(ClientCall(method, canonical, probe, _line_of(text, idx), raw))

    # get / post / pbGet / pbPost helper call sites.
    for m in _CALL_RE.finditer(text):
        method = helpers.get(m.group(1))
        if method is None:
            continue
        j = m.end()
        while j < len(text) and text[j] in " \t\r\n":
            j += 1
        got = _read_delimited(text, j) if j < len(text) else None
        if got is None:
            continue  # first arg is not a literal (e.g. the helper definition)
        _add(method, got[0], m.start())

    # Bespoke bare ``fetch(...)`` wrappers (uploadFile, uploadCheckpointFile,
    # deletePaperbenchPaper). Method read from the options object; default GET.
    for m in _FETCH_RE.finditer(text):
        j = m.end()
        while j < len(text) and text[j] in " \t\r\n":
            j += 1
        got = _read_delimited(text, j) if j < len(text) else None
        if got is None:
            continue
        raw = got[0]
        if "${path}" in raw:
            continue  # the get/post/pbGet/pbPost helper bodies themselves
        window = text[m.end():m.end() + 400]
        mm = _METHOD_RE.search(window)
        method = mm.group(1).upper() if mm else "GET"
        _add(method, raw, m.start())

    return calls


# ── reconciliation ──────────────────────────────────────────────────────────


def reconcile(
    routes: list[ServerRoute], calls: list[ClientCall]
) -> tuple[list[ClientCall], list[ServerRoute], list[tuple[ClientCall, ServerRoute]], list[ServerRoute]]:
    """Simulate dispatch: first matching route (in order) wins, like the runtime.

    Returns ``(client_only, server_only, matched_pairs, unparsed_routes)``.
    """
    by_method: dict[str, list[ServerRoute]] = {}
    for r in routes:
        by_method.setdefault(r.method, []).append(r)

    client_only: list[ClientCall] = []
    matched: list[tuple[ClientCall, ServerRoute]] = []
    for call in calls:
        hit: ServerRoute | None = None
        for r in by_method.get(call.method, []):
            if r.matches(call.probe) is True:
                hit = r
                break
        if hit is None:
            client_only.append(call)
        else:
            hit.hits += 1
            matched.append((call, hit))

    server_only = [r for r in routes if r.hits == 0]
    unparsed = [r for r in routes if r.label.startswith("re:") is False
                and _all_none(r)]
    return client_only, server_only, matched, unparsed


def _all_none(route: ServerRoute) -> bool:
    """A route whose test never evaluates to True/False for a probe (unknown idiom)."""
    return route.matches("/__probe__/x") is None and route.matches("/") is None


# ── config / allowlist ──────────────────────────────────────────────────────


def load_config(path: Path) -> dict:
    rules: dict = {
        "routes_file": str(DEFAULT_ROUTES),
        "client_file": str(DEFAULT_CLIENT),
        "client_helpers": dict(DEFAULT_CLIENT_HELPERS),
        "use_declarative_routes": False,
    }
    if path and path.exists():
        data = _common.load_yaml(path)
        for key in rules:
            if key in data:
                rules[key] = data[key]
    return rules


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


# ── findings / reporting ────────────────────────────────────────────────────


def build_findings(
    client_only: list[ClientCall],
    server_only: list[ServerRoute],
    allow_ids: set[str],
    routes_rel: str,
    client_rel: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for call in client_only:
        findings.append(Finding(
            id=call.id, severity="error", file=client_rel, line=call.line,
            kind="client-only",
            message=(f"client calls {call.method} {call.canonical} but no route "
                     f"serves it (broken call)"),
            allowlisted=call.id in allow_ids,
        ))
    for r in server_only:
        findings.append(Finding(
            id=r.id, severity="warning", file=routes_rel, line=r.line,
            kind="server-only",
            message=(f"route {r.method} {r.label} is served but services/api.ts "
                     f"never calls it (candidate unused endpoint)"),
            allowlisted=r.id in allow_ids,
        ))
    findings.sort(key=lambda f: (f.kind, f.severity, f.id))
    return findings


def build_report(
    target_rel: str,
    findings: list[Finding],
    matched: list[tuple[ClientCall, ServerRoute]],
    unparsed: list[ServerRoute],
) -> dict:
    client_only = sum(1 for f in findings if f.kind == "client-only")
    server_only = sum(1 for f in findings if f.kind == "server-only")
    known = sum(1 for f in findings if f.allowlisted)
    new = sum(1 for f in findings if not f.allowlisted)
    summary = {
        "client_only": client_only,
        "server_only": server_only,
        "matched": len(matched),
        "known": known,
        "new": new,
        "total": len(findings),
        "unparsed_routes": len(unparsed),
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
        f"- matched (both sides): **{s['matched']}**",
        f"- client-only (broken call): **{s['client_only']}**",
        f"- server-only (candidate unused): **{s['server_only']}**",
        f"- known (allowlisted): {s['known']}  ·  new: **{s['new']}**",
    ]
    if s.get("unparsed_routes"):
        lines.append(f"- unparsed routes (unknown dispatch idiom): {s['unparsed_routes']}")
    lines.append("")
    if not report["findings"]:
        lines.append("Backend routes and `services/api.ts` are in sync.")
        return "\n".join(lines) + "\n"
    headers = ["Kind", "Severity", "Endpoint", "Location", "Status"]
    rows = []
    for f in report["findings"]:
        status = "known" if f["allowlisted"] else "**new**"
        rows.append([
            f["kind"], f["severity"], f"`{f['id']}`",
            f"`{f['file']}:{f['line']}`", status,
        ])
    lines.append(_common.render_markdown_table(headers, rows))
    return "\n".join(lines) + "\n"


# ── cli ─────────────────────────────────────────────────────────────────────


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--target", default=str(DEFAULT_TARGET),
                    help="viz backend package dir (default: ari-core/ari/viz)")
    ap.add_argument("--client", default=None,
                    help="services/api.ts path (default: <target>/frontend/src/services/api.ts)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="checker config YAML (default: scripts/quality/%(prog)s.yaml)")
    ap.add_argument("--allow", default=str(DEFAULT_ALLOW),
                    help="frozen allowlist YAML (default: scripts/quality/...allow.yaml)")
    ap.add_argument("--inventory", default=None,
                    help="optional 020 endpoint manifest (JSON) as the server source of truth")
    ap.add_argument("--output", default=None,
                    help="write the report to a file instead of stdout")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown",
                    help="report format (default: markdown)")
    ap.add_argument("--json", action="store_true", help="alias for --format json")
    ap.add_argument("--warning-only", action="store_true",
                    help="force exit 0 regardless of findings (rollout default posture)")
    ap.add_argument("--fail-on-regression", action="store_true",
                    help="exit 1 only on findings not in the allowlist (ratchet)")
    ap.add_argument("--base-ref", default="origin/main",
                    help="git base ref for --fail-on-regression diffing (advisory)")
    return ap


def _load_inventory_routes(path: Path, methods) -> list[ServerRoute] | None:
    """Best-effort load of a machine-readable 020 manifest as exact-path routes.

    Recognizes a JSON list of ``{method, path}`` (or ``{method, path_pattern}``)
    or a dict with a ``routes``/``endpoints`` key. Returns ``None`` (fall back to
    static extraction) when the shape is not recognized — never fails the run.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    items = data
    if isinstance(data, dict):
        for key in ("routes", "endpoints"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    if not isinstance(items, list):
        return None
    routes: list[ServerRoute] = []
    for it in items:
        if not isinstance(it, dict):
            return None
        method = str(it.get("method", "")).upper()
        p = it.get("path") or it.get("path_pattern")
        if method not in ("GET", "POST", "PUT", "DELETE", "PATCH") or not p:
            return None
        label = str(p).replace(PARAM_TOKEN, PARAM_DISPLAY)
        # Exact-match test synthesized so ``matches`` works uniformly.
        test = ast.parse(f'self.path == {json.dumps(str(p))}', mode="eval").body
        routes.append(ServerRoute(method, label, 0, test))
    return routes or None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    rules = load_config(Path(args.config))
    methods = rules["client_helpers"]

    routes_file = Path(args.target).resolve() / "routes.py" \
        if Path(args.target).is_dir() else Path(rules["routes_file"])
    if not routes_file.exists():
        routes_file = Path(rules["routes_file"])
    client_file = Path(args.client) if args.client else Path(rules["client_file"])

    if not routes_file.exists():
        sys.stderr.write(f"check_viz_api_schema: routes file not found: {routes_file}\n")
        raise SystemExit(2)
    if not client_file.exists():
        sys.stderr.write(f"check_viz_api_schema: client file not found: {client_file}\n")
        raise SystemExit(2)

    routes: list[ServerRoute] | None = None
    if args.inventory:
        routes = _load_inventory_routes(Path(args.inventory), methods)
    if routes is None:
        routes = extract_server_routes(routes_file, methods)
        if rules.get("use_declarative_routes"):
            target_dir = Path(args.target).resolve()
            for method, path in parse_declarative_routes(target_dir):
                test = ast.parse(f'self.path == {json.dumps(path)}', mode="eval").body
                routes.append(ServerRoute(method, path.replace(PARAM_TOKEN, PARAM_DISPLAY),
                                          0, test))

    calls = extract_client_calls(client_file, methods)
    allow_ids, _notes = load_allow(Path(args.allow) if args.allow else None)

    client_only, server_only, matched, unparsed = reconcile(routes, calls)
    findings = build_findings(
        client_only, server_only, allow_ids, _rel(routes_file), _rel(client_file),
    )
    report = build_report(_rel(Path(args.target)), findings, matched, unparsed)

    fmt = "json" if args.json else args.format
    text = json.dumps(report, indent=2, ensure_ascii=False) if fmt == "json" \
        else render_markdown(report)
    _common.write_output(text.rstrip("\n"), args.output)

    if args.warning_only:
        return 0
    if args.fail_on_regression:
        return 1 if any(not f.allowlisted for f in findings) else 0
    # Warning-mode-first (030 §7.7 / 009 §6): report, exit 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
