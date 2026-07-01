#!/usr/bin/env python3
"""Snapshot & diff gate for the ``ari.public.*`` API surface (contract freeze).

``ari.public`` is the single stable contract between the 14 ``ari-skill-*``
servers and ``ari-core`` internals — its own ``ari/public/__init__.py`` docstring
states "Skills must only import from ``ari.public.*``". This checker freezes the
exact public surface (the 8 re-export submodules plus the docstring-only package)
into a committed JSON snapshot so that a later refactor cannot silently remove,
rename, or hollow out a symbol a skill depends on.

Design: docs/refactoring/009_quality_scripts_plan.md §5.5 (this checker's spec).
Policy: docs/refactoring/010_contract_preservation_policy.md §2 (Public Python API).
Sequencing: docs/refactoring/subtasks/029_add_public_api_contract_checker_script.md.

What it records (deterministic, sorted JSON — byte-stable for ``git diff``):
  * the 8 public submodules ``ari.public.{claim_gate, config_schema, container,
    cost_tracker, llm, paths, run_env, verified_context}`` and the docstring-only
    ``ari.public`` package itself;
  * each module's exported name set (its ``__all__``);
  * ``backing`` — the ``ari.*`` internals each submodule re-exports from;
  * ``thin`` — whether the module body is a pure re-export (no ``def``/``class``);
  * ``all_is_dynamic`` — whether ``__all__`` is computed at import time
    (``container``/``cost_tracker``/``run_env`` do
    ``getattr(_impl, "__all__", [...])`` over their backing module).

Surface reading strategy (per subtask §7.2): the literal ``__all__`` of the
static modules is read straight from the AST (so an arbitrary ``--target`` scratch
copy still works for a removal smoke-test), while the three dynamically-computed
``__all__`` modules are resolved by importing their backing ``_impl`` module in a
hermetic subprocess and reproducing the module's own
``getattr(_impl, "__all__", [dir(_impl) …])`` computation. The docstring-only
``ari.public`` package has no ``__all__`` and is recorded faithfully as
``exports: []`` (it re-exports nothing at the package level — a recorded fact,
not a bug this checker fixes).

Determinism (design principle P2): stdlib only, no network, no LLM calls; two runs
on the same tree yield byte-identical output.

Exit codes (staged warning→error rollout, matching scripts/docs/*):
  0  clean, or advisory mode (default) even when a break is present;
  1  a contract break (removed module/symbol, thin regression, backing change)
     was found AND ``--strict`` was passed; also usage/verify-without-snapshot;
  2  environment error (cannot introspect ``ari``).
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = REPO_ROOT / "ari-core" / "ari" / "public"
DEFAULT_SNAPSHOT = (
    REPO_ROOT / "docs" / "refactoring" / "reports" / "public_api_snapshot.json"
)
# TODO(034): coordinate the snapshot fixture location with subtask 034
# (add_contract_snapshot_fixtures); until it lands the baseline lives beside the
# other refactoring measurement artifacts under docs/refactoring/reports/.

PACKAGE_NAME = "ari.public"
SCHEMA_VERSION = 1

# Subprocess snippet: import a set of backing modules and print their resolved
# public name set, reproducing the ``getattr(_impl, "__all__", [dir(_impl) …])``
# computation the dynamic public re-exports perform themselves.
_RESOLVE_SNIPPET = r"""
import importlib, json, sys

mods = json.loads(sys.argv[1])
out = {}
for name in mods:
    try:
        mod = importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - surface any import failure verbatim
        out[name] = {"error": "%s: %s" % (type(exc).__name__, exc)}
        continue
    declared = getattr(mod, "__all__", None)
    if declared is None:
        names = [n for n in dir(mod) if not n.startswith("_")]
    else:
        names = list(declared)
    out[name] = {"names": sorted(str(n) for n in names)}
print(json.dumps(out))
"""


class CheckerError(Exception):
    """Raised for environment/usage failures (exit 2)."""


# --------------------------------------------------------------------------- #
# AST analysis of a single public re-export module.
# --------------------------------------------------------------------------- #

def _targets_all(node: ast.Assign) -> bool:
    return any(
        isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
    )


def _string_elements(value: ast.expr) -> list[str]:
    out: list[str] = []
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        for elt in value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
    return out


def _analyze_module(path: Path) -> dict:
    """Return the AST-derived facts for one ``ari/public/*.py`` file.

    Keys: ``static_names`` (literal ``__all__`` or None), ``all_kind``
    (``static``/``dynamic``/``absent``), ``impl_module`` (module aliased as
    ``_impl`` for dynamic resolution, or None), ``backing`` (sorted ``ari.*``
    provenance), ``thin`` (pure re-export?).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    backing: set[str] = set()
    impl_module: str | None = None
    static_names: list[str] | None = None
    all_kind = "absent"
    thin = True

    for node in tree.body:
        # module docstring / bare string expression
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "ari" or alias.name.startswith("ari."):
                    backing.add(alias.name)
            continue
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "ari" or mod.startswith("ari."):
                # A ``... as _impl`` alias points at the backing *submodule*
                # (e.g. ``from ari.agent import run_env as _impl`` -> the
                # backing module is ``ari.agent.run_env``, not ``ari.agent``);
                # a wildcard / named import re-exports from ``mod`` itself.
                impl_alias = next(
                    (a for a in node.names if a.asname == "_impl"), None
                )
                if impl_alias is not None:
                    target = f"{mod}.{impl_alias.name}"
                    impl_module = target
                    backing.add(target)
                else:
                    backing.add(mod)
            continue
        if isinstance(node, ast.Assign) and _targets_all(node):
            if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                all_kind = "static"
                static_names = _string_elements(node.value)
            else:
                all_kind = "dynamic"
            continue
        # Anything else at module top level (def/class/other executable stmt)
        # means the module is no longer a pure re-export.
        thin = False

    return {
        "static_names": static_names,
        "all_kind": all_kind,
        "impl_module": impl_module,
        "backing": sorted(backing),
        "thin": thin,
    }


# --------------------------------------------------------------------------- #
# Live surface construction.
# --------------------------------------------------------------------------- #

def _public_module_files(target: Path) -> list[Path]:
    if not target.is_dir():
        raise CheckerError(f"--target is not a directory: {target}")
    return sorted(p for p in target.glob("*.py") if p.name != "__init__.py")


def _resolve_backings(module_names: list[str]) -> dict[str, list[str]]:
    """Import each backing module in a subprocess; return resolved name sets."""
    if not module_names:
        return {}
    proc = subprocess.run(
        [sys.executable, "-c", _RESOLVE_SNIPPET, json.dumps(sorted(module_names))],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        raise CheckerError(
            "failed to introspect ari backing modules "
            f"(is ari-core importable?):\n{proc.stderr.strip()}"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CheckerError(f"malformed introspection output: {exc}") from exc
    resolved: dict[str, list[str]] = {}
    errors: list[str] = []
    for name, info in data.items():
        if "error" in info:
            errors.append(f"{name}: {info['error']}")
        else:
            resolved[name] = info["names"]
    if errors:
        raise CheckerError(
            "could not import backing module(s):\n  " + "\n  ".join(errors)
        )
    return resolved


def build_live_surface(target: Path) -> dict:
    """Build the normalized public-API surface dict for *target*."""
    files = _public_module_files(target)
    facts: dict[str, dict] = {}
    dynamic_backings: set[str] = set()

    # Package row: docstring-only, no __all__ -> exports [].
    pkg_init = target / "__init__.py"
    if pkg_init.exists():
        facts[PACKAGE_NAME] = _analyze_module(pkg_init)

    for f in files:
        mod_name = f"{PACKAGE_NAME}.{f.stem}"
        info = _analyze_module(f)
        facts[mod_name] = info
        if info["all_kind"] == "dynamic":
            if info["impl_module"] is None:
                raise CheckerError(
                    f"{mod_name}: dynamic __all__ but no ``_impl`` alias found"
                )
            dynamic_backings.add(info["impl_module"])

    resolved = _resolve_backings(list(dynamic_backings))

    modules: dict[str, dict] = {}
    for mod_name, info in facts.items():
        all_kind = info["all_kind"]
        if all_kind == "static":
            exports = sorted(info["static_names"] or [])
        elif all_kind == "dynamic":
            exports = sorted(resolved[info["impl_module"]])
        else:  # absent (the docstring-only package)
            exports = []
        modules[mod_name] = {
            "exports": exports,
            "backing": info["backing"],
            "thin": info["thin"],
            "has_all": all_kind != "absent",
            "all_is_dynamic": all_kind == "dynamic",
        }

    return {
        "schema": SCHEMA_VERSION,
        "generated_by": "scripts/check_public_api_contracts.py",
        "ari_core_version": _read_core_version(),
        "modules": dict(sorted(modules.items())),
    }


def _read_core_version() -> str:
    pyproject = REPO_ROOT / "ari-core" / "pyproject.toml"
    try:
        import tomllib

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return str(data.get("project", {}).get("version", "unknown"))
    except Exception:  # noqa: BLE001 - version stamp is best-effort metadata
        return "unknown"


def _serialize(surface: dict) -> str:
    return json.dumps(surface, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- #
# Diff.
# --------------------------------------------------------------------------- #

# Finding kinds -> severity bucket.
_BREAK = {"module_removed", "export_removed"}
_REGRESSION = {"thin_regressed", "backing_changed"}
_INFO = {"module_added", "export_added", "dynamic_changed", "version_changed"}


def diff_surfaces(old: dict, new: dict) -> list[dict]:
    findings: list[dict] = []
    old_mods = old.get("modules", {})
    new_mods = new.get("modules", {})

    ov = old.get("ari_core_version")
    nv = new.get("ari_core_version")
    if ov is not None and ov != nv:
        findings.append(
            {
                "kind": "version_changed",
                "module": None,
                "message": f"ari_core_version {ov} -> {nv} (informational)",
            }
        )

    for name in sorted(set(old_mods) | set(new_mods)):
        if name not in new_mods:
            findings.append(
                {
                    "kind": "module_removed",
                    "module": name,
                    "message": f"public module removed: {name}",
                }
            )
            continue
        if name not in old_mods:
            findings.append(
                {
                    "kind": "module_added",
                    "module": name,
                    "message": f"public module added: {name}",
                }
            )
            continue
        o, n = old_mods[name], new_mods[name]
        o_exports, n_exports = set(o.get("exports", [])), set(n.get("exports", []))
        for sym in sorted(o_exports - n_exports):
            findings.append(
                {
                    "kind": "export_removed",
                    "module": name,
                    "message": f"symbol removed: {name}.{sym}",
                }
            )
        for sym in sorted(n_exports - o_exports):
            findings.append(
                {
                    "kind": "export_added",
                    "module": name,
                    "message": f"symbol added: {name}.{sym}",
                }
            )
        if o.get("thin") and not n.get("thin"):
            findings.append(
                {
                    "kind": "thin_regressed",
                    "module": name,
                    "message": (
                        f"public re-export {name} grew real logic "
                        "(no longer a thin contract layer)"
                    ),
                }
            )
        if o.get("backing", []) != n.get("backing", []):
            findings.append(
                {
                    "kind": "backing_changed",
                    "module": name,
                    "message": (
                        f"backing changed for {name}: "
                        f"{o.get('backing')} -> {n.get('backing')}"
                    ),
                }
            )
        if o.get("all_is_dynamic") != n.get("all_is_dynamic"):
            findings.append(
                {
                    "kind": "dynamic_changed",
                    "module": name,
                    "message": (
                        f"__all__ dynamic flag changed for {name}: "
                        f"{o.get('all_is_dynamic')} -> {n.get('all_is_dynamic')}"
                    ),
                }
            )
    return findings


def _severity(kind: str) -> str:
    if kind in _BREAK:
        return "break"
    if kind in _REGRESSION:
        return "regression"
    return "info"


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #

def _load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _emit_text(findings: list[dict], snapshot: Path, strict: bool) -> None:
    breaks = [f for f in findings if _severity(f["kind"]) == "break"]
    regressions = [f for f in findings if _severity(f["kind"]) == "regression"]
    infos = [f for f in findings if _severity(f["kind"]) == "info"]

    if not findings:
        print(f"OK: ari.public.* surface matches {snapshot.relative_to(REPO_ROOT)}")
        return

    if breaks:
        print("!! CONTRACT BREAK(S) — ari.public.* lost a symbol/module:")
        for f in breaks:
            print(f"   - {f['message']}")
    for label, group in (("REGRESSION", regressions), ("info", infos)):
        for f in group:
            print(f"   [{label}] {f['message']}")

    total = len(breaks)
    print(
        f"\n{total} break(s), {len(regressions)} regression(s), "
        f"{len(infos)} informational."
    )
    if (breaks or regressions) and not strict:
        print(
            "advisory mode (exit 0): re-run with --strict to fail on breaks, "
            "or --update to deliberately re-baseline the snapshot."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--target",
        type=Path,
        default=PUBLIC_DIR,
        help="public-surface directory to scan (default: ari-core/ari/public).",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=DEFAULT_SNAPSHOT,
        help="committed baseline snapshot JSON (default under docs/refactoring/reports).",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="regenerate the snapshot in place (deliberate re-baseline); prints "
        "what changed vs the previous snapshot; exit 0.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable output (for the subtask-031 aggregator).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="promote breaks/regressions to exit 1 (staged-rollout toggle; "
        "default advisory).",
    )
    args = parser.parse_args(argv)

    try:
        live = build_live_surface(args.target.resolve())
    except CheckerError as exc:
        sys.stderr.write(f"check_public_api_contracts: {exc}\n")
        return 2

    if args.update:
        previous: dict = {}
        if args.snapshot.exists():
            previous = _load_snapshot(args.snapshot)
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        args.snapshot.write_text(_serialize(live), encoding="utf-8")
        findings = diff_surfaces(previous, live)
        if args.json:
            print(json.dumps(
                {
                    "checker": "check_public_api_contracts",
                    "mode": "update",
                    "snapshot": str(args.snapshot.relative_to(REPO_ROOT)),
                    "modules": sorted(live["modules"]),
                    "changes": findings,
                },
                ensure_ascii=False,
                indent=2,
            ))
        else:
            rel = args.snapshot.relative_to(REPO_ROOT)
            print(f"wrote snapshot: {rel} ({len(live['modules'])} modules)")
            for f in findings:
                print(f"   [{_severity(f['kind'])}] {f['message']}")
        return 0

    if not args.snapshot.exists():
        sys.stderr.write(
            f"check_public_api_contracts: snapshot not found: {args.snapshot}\n"
            "run with --update to create the baseline first.\n"
        )
        return 1

    committed = _load_snapshot(args.snapshot)
    findings = diff_surfaces(committed, live)

    if args.json:
        print(json.dumps(
            {
                "checker": "check_public_api_contracts",
                "mode": "verify",
                "snapshot": str(args.snapshot.relative_to(REPO_ROOT)),
                "ari_core_version": live.get("ari_core_version"),
                "summary": {
                    "breaks": sum(
                        1 for f in findings if _severity(f["kind"]) == "break"
                    ),
                    "regressions": sum(
                        1 for f in findings if _severity(f["kind"]) == "regression"
                    ),
                    "info": sum(
                        1 for f in findings if _severity(f["kind"]) == "info"
                    ),
                },
                "findings": [
                    {**f, "severity": _severity(f["kind"])} for f in findings
                ],
            },
            ensure_ascii=False,
            indent=2,
        ))
    else:
        _emit_text(findings, args.snapshot, args.strict)

    has_fail = any(
        _severity(f["kind"]) in ("break", "regression") for f in findings
    )
    return 1 if (args.strict and has_fail) else 0


if __name__ == "__main__":
    raise SystemExit(main())
