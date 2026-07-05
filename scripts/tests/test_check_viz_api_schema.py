#!/usr/bin/env python3
"""Unit + smoke tests for scripts/check_viz_api_schema.py.

Covers (subtask 030 §8 item 8 / §13):
  * normalization: ``${encodeURIComponent(id)}`` -> ``SEG`` / ``{id}``; query
    stripped for the canonical id but retained in the dispatch probe; ``${qs}``/
    ``${nq}`` conditional fragments dropped; ``${API_BASE}`` removed (§13.6);
  * client extraction covers ALL FOUR regimes (get/post/pbGet/pbPost) + bespoke
    ``fetch``, literal + template paths, and recognizes a PaperBench pbPost call
    (§13.5); the generic helper-internal fetch is not mistaken for an endpoint;
  * server extraction of the ``if/elif`` dispatch (equality / ``in`` / prefix /
    suffix / ``re.match``), with the do_POST body-length guard skipped;
  * reconciliation: a synthetic client-only call -> error; an allowlisted
    server-only route -> known;
  * repo smoke (§13.4): against the real tree the checker is clean-or-warning —
    with the seeded allowlist ZERO net-new findings (exit 0 under
    ``--fail-on-regression``); with an empty allowlist exactly one client-only
    finding, the known F6a POST /report drift.

Unit tests import the checker module by file path (it has no package); the repo
smoke runs it as a subprocess (matching the §12 manual acceptance runs and the
sibling test_check_import_boundaries.py convention).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parent
CHECKER = SCRIPTS_DIR / "check_viz_api_schema.py"
ALLOW = REPO_ROOT / "scripts" / "quality" / "check_viz_api_schema.allow.yaml"


def _load_module():
    spec = importlib.util.spec_from_file_location("_viz_schema_checker", CHECKER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()
HELPERS = {"get": "GET", "pbGet": "GET", "post": "POST", "pbPost": "POST"}


# ── normalization ──────────────────────────────────────────────────────────


def test_probe_strips_api_base_and_substitutes_params() -> None:
    assert mod._to_probe("${API_BASE}/state") == "/state"
    assert (mod._to_probe("/api/checkpoint/${encodeURIComponent(id)}/summary")
            == "/api/checkpoint/SEG/summary")


def test_probe_keeps_query_but_canonical_strips_it() -> None:
    probe = mod._to_probe(
        "/api/checkpoint/${encodeURIComponent(id)}/file?name=${encodeURIComponent(f)}")
    assert probe == "/api/checkpoint/SEG/file?name=SEG"
    # canonical drops the query and shows the param placeholder.
    assert mod._canonical(probe) == "/api/checkpoint/{id}/file"


def test_probe_drops_conditional_query_fragments() -> None:
    # ${qs}/${nq} expand to '' (conditional query fragments); ${q.toString()}->k=v.
    assert (mod._to_probe("/api/checkpoint/${encodeURIComponent(id)}/filetree${qs}")
            == "/api/checkpoint/SEG/filetree")
    assert (mod._to_probe("/api/checkpoint/${encodeURIComponent(id)}/memory_access?${q.toString()}")
            == "/api/checkpoint/SEG/memory_access?k=v")


# ── client extraction (all four regimes + bespoke fetch) ───────────────────


CLIENT_FIXTURE = """
const API_BASE = '';
async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  return res.json();
}
async function pbGet<T = any>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  return res.json();
}
export async function fetchState() { return get<AppState>('/state'); }
export async function fetchSummary(id: string) {
  return get<X>(`/api/checkpoint/${encodeURIComponent(id)}/summary`);
}
export async function saveSettings(d: any) { return post('/api/settings', d); }
export async function runPaperbench(b: unknown) { return pbPost('/api/paperbench/run', b); }
export async function fetchPapers() { return pbGet('/api/paperbench/papers'); }
export async function uploadFile(file: File) {
  const res = await fetch(`/api/upload`, { method: 'POST', headers: {} });
  return res.json();
}
export async function deletePaper(id: string) {
  const res = await fetch(`/api/paperbench/papers/${encodeURIComponent(id)}/delete`, {
    method: 'POST',
  });
  return res.json();
}
"""


def test_client_extraction_all_regimes(tmp_path: Path) -> None:
    f = tmp_path / "api.ts"
    f.write_text(CLIENT_FIXTURE, encoding="utf-8")
    calls = mod.extract_client_calls(f, HELPERS)
    got = {(c.method, c.canonical) for c in calls}
    assert ("GET", "/state") in got                       # get
    assert ("GET", "/api/checkpoint/{id}/summary") in got  # get + template param
    assert ("POST", "/api/settings") in got                # post
    assert ("GET", "/api/paperbench/papers") in got        # pbGet -> GET
    assert ("POST", "/api/paperbench/run") in got          # pbPost -> POST (AC#5)
    assert ("POST", "/api/upload") in got                  # bespoke fetch, POST
    assert ("POST", "/api/paperbench/papers/{id}/delete") in got  # bespoke fetch
    # The generic helper-internal fetch(`${API_BASE}${path}`) is NOT an endpoint.
    assert all(c.canonical not in ("", "/SEG", "{id}") for c in calls)
    assert len(got) == 7


# ── server extraction + dispatch simulation ────────────────────────────────


SERVER_FIXTURE = '''
import re
class _Handler:
    def do_GET(self):
        if self.path in ("/logo.png", "/logo"):
            return
        if self.path == "/state":
            return
        elif self.path.startswith("/api/checkpoint/") and self.path.endswith("/summary"):
            return
        elif re.match(r"^/api/checkpoint/[^/]+/paper\\.(pdf|tex)$", self.path):
            return
        elif self.path == "/api/only-server":
            return
    def do_POST(self):
        body = self.rfile.read()
        if len(body) > 10:
            return
        if self.path == "/api/settings":
            return
        elif self.path == "/api/paperbench/run":
            return
'''


def test_server_extraction_and_matching(tmp_path: Path) -> None:
    f = tmp_path / "routes.py"
    f.write_text(SERVER_FIXTURE, encoding="utf-8")
    routes = mod.extract_server_routes(f, HELPERS)
    ids = {r.id for r in routes}
    # The do_POST body-length guard must NOT become a route.
    assert "GET /state" in ids
    assert "GET /api/only-server" in ids
    assert "POST /api/settings" in ids
    assert "POST /api/paperbench/run" in ids
    assert not any("body" in i.lower() for i in ids)

    def route_for(method: str, label_sub: str):
        return next(r for r in routes if r.method == method and label_sub in r.label)

    # prefix+suffix, exact, and regex predicates all evaluate a concrete probe.
    assert route_for("GET", "/summary").matches("/api/checkpoint/SEG/summary") is True
    assert route_for("GET", "/state").matches("/state") is True
    assert route_for("GET", "re:").matches("/api/checkpoint/SEG/paper.pdf") is True
    assert route_for("GET", "re:").matches("/api/checkpoint/SEG/summary") is not True


# ── reconciliation ─────────────────────────────────────────────────────────


def test_reconcile_client_only_and_allowlisted_server_only(tmp_path: Path) -> None:
    routes_f = tmp_path / "routes.py"
    routes_f.write_text(SERVER_FIXTURE, encoding="utf-8")
    routes = mod.extract_server_routes(routes_f, HELPERS)

    client_f = tmp_path / "api.ts"
    client_f.write_text(
        "export async function a() { return get<X>('/state'); }\n"
        "export async function b() { return get<X>('/api/does-not-exist'); }\n",
        encoding="utf-8",
    )
    calls = mod.extract_client_calls(client_f, HELPERS)

    client_only, server_only, matched, unparsed = mod.reconcile(routes, calls)
    assert {c.id for c in client_only} == {"GET /api/does-not-exist"}
    assert "GET /api/only-server" in {r.id for r in server_only}
    assert unparsed == []

    # An allowlisted server-only route reports as known; the broken call as new.
    allow = {"GET /api/only-server", "GET /logo|/logo.png",
             "GET re:^/api/checkpoint/[^/]+/paper\\.(pdf|tex)$"}
    findings = mod.build_findings(
        client_only, server_only, allow, "routes.py", "api.ts")
    by_id = {f.id: f for f in findings}
    assert by_id["GET /api/does-not-exist"].severity == "error"
    assert by_id["GET /api/does-not-exist"].allowlisted is False
    assert by_id["GET /api/only-server"].allowlisted is True


# ── repo smoke (real tree) ─────────────────────────────────────────────────


def _run(*args: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--json", *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def test_repo_smoke_seeded_allowlist_is_clean() -> None:
    code, report = _run("--allow", str(ALLOW))
    s = report["summary"]
    assert s["new"] == 0, [f for f in report["findings"] if not f["allowlisted"]]
    assert s["matched"] >= 78
    assert s["unparsed_routes"] == 0
    assert code == 0


def test_repo_smoke_fail_on_regression_passes_with_seed() -> None:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--fail-on-regression", "--allow", str(ALLOW)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_repo_smoke_empty_allowlist_flags_only_f6a_client_only() -> None:
    code, report = _run("--allow", "/dev/null")
    client_only = [f for f in report["findings"] if f["kind"] == "client-only"]
    assert len(client_only) == 1
    assert client_only[0]["id"] == "POST /api/paperbench/run/{id}/report"
    assert client_only[0]["severity"] == "error"
    assert code == 0  # default posture is warning-mode-first


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
