"""Task-harness registry: ARI ships no harnesses; the workspace supplies them.

A *harness* owns the task-specific half of scoring: it seeds a node's work_dir
with the frozen scaffolding, then compiles and measures the node's candidate,
returning ``{"compile_ok": bool, "families": {name: {"speedup": float,
"valid": bool}}}``. The task-INDEPENDENT half (the all-or-nothing validity gate,
the geomean, and the ``[0,1]`` normalisation) stays in
:mod:`ari.evaluator.deterministic_evaluator` and is never delegated.

Where harnesses live
--------------------
``$ARI_WORKSPACE/harnesses/<task>/`` — the frozen scaffolding plus a
``harness.toml`` declaring the task's TARGET, scoring scale, ``measure_node``
kwargs, and a sha256 for every file. ARI core contains NO task: adding, changing
or removing one never edits this repo. A benchmark is an experiment asset with
its own lifecycle, not a framework feature.

The consequence is deliberate and worth stating plainly: a checkout of ARI with
no workspace can run no task, and :func:`available_tasks` returns ``[]``. The
instrument travels with the experiment.

Why the manifest pins hashes
----------------------------
The agent runs ``run_bash`` as the SAME uid as the evaluator, so no filesystem
permission stops it from rewriting a harness file. The integrity property is
therefore NOT "the agent cannot touch it"; it is:

1. the evaluator resolves the driver/baseline from a path the agent's *output*
   never feeds (never from ``work_dir``), and
2. every file it compiles is **content-addressed**: the manifest pins a sha256
   and :func:`load` verifies all of them before binding the harness, so a
   modified file *refuses to score* rather than scoring differently.

The claim is falsifiable in the OUTPUT, not just here: every run writes
``<checkpoint>/provenance.json`` (``ari/cli/bfts_loop.py``) carrying
:meth:`Harness.provenance` — the verified digests, the workspace-relative origin,
the target/scale/axis, plus the ARI commit and the measurement environment. A
reader holding the published workspace and this repo can recompute each digest
and compare. That record is METADATA: it must never be copied into a node, or the
node is handed the scoring configuration it is judged by.

What IS enforced, and what is not. The node is deliberately *given* copies of the
scaffolding (driver, baseline, Makefile, selftest) so it can self-test the way the
evaluator measures — so "the harness is hidden from the node" is not the property
and never was. The property is that the node's copies CANNOT COUNT: every harness
resolves ``main_c``, the baseline and ``-I`` from ``kernels_dir()`` and takes only
``candidate_*.c`` from ``work_dir``, compiling into a fresh temp dir. Editing the
seeded copies changes the node's own selftest and nothing else.

That isolation is by RESOLUTION PATH, not by permission. ``run_bash`` runs as the
same uid as the evaluator and ``import ari`` reveals the originals' location in one
line, so a node that deliberately overwrote a file in ``kernels_dir()`` would
poison the baseline for the rest of the run. Nothing here prevents that; only the
container runtime could. Say "the agent's edits cannot reach the scorer", never
"the scaffolding cannot be edited".
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

MANIFEST_NAME = "harness.toml"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class HarnessIntegrityError(RuntimeError):
    """A pinned harness file is missing or its content does not match the manifest.

    Raised INSTEAD of returning a score: a measurement made with an unverified
    driver/baseline is not a measurement, it is a claim.
    """


@dataclass
class Harness:
    """A harness resolved from ``workspace/harnesses/<task>/``."""

    task: str
    target: float
    scale: str                      # "log" | "linear" — how a speedup is squashed to [0,1]
    axis: str                       # "speedup" | "score" — the NATIVE outcome axis
    origin: str                     # the harness dir it was loaded from
    seed_work_dir: Callable[[str], list[str]]
    # Where the frozen scaffolding lives. ARI reads it to copy the run's INPUT
    # files into the checkpoint's ``uploads/`` (provenance). It is NOT a path the
    # node is ever told: the node receives copies via ``seed_work_dir``.
    kernels_dir: Callable[[], str]
    _measure_node: Callable[..., dict]
    # Per-task call kwargs (seed / n,k / none) — resolved at call time from env.
    _kwargs: Callable[[], dict] = dict
    # path (relative to the harness dir) -> sha256, for every pinned file.
    pinned: dict[str, str] = field(default_factory=dict)
    # Formatting-independent digest of the scoring config (target/scale/axis/
    # measure_kwargs/files); recorded in provenance so a reader can re-check that
    # the manifest that scored a published number was not later edited.
    manifest_hash: str = ""

    def measure(self, work_dir: str) -> dict:
        """Measure the node's candidate. ARI calls this; the node never sees it.

        The node's work_dir holds only the agent's candidate (plus seeded copies
        of the scaffolding for its own self-test, which do NOT participate). The
        driver/baseline compiled here come from this harness's own directory.
        """
        return self._measure_node(work_dir, **self._kwargs())

    def digests(self) -> dict[str, str]:
        """Digests to record alongside the score, so a reader can later confirm
        WHICH scaffolding produced a published number."""
        return dict(self.pinned)

    def provenance(self) -> dict[str, Any]:
        """What must be recorded with a run for its numbers to be re-checkable.

        Pure — the caller decides where it lands. ``origin`` is workspace-relative
        so the record is portable: it names a directory inside the artifact being
        published, not a path on the machine that produced it.
        """
        origin = Path(self.origin)
        try:
            rel = str(origin.relative_to(workspace_harness_root().parent))
        except ValueError:
            rel = origin.name
        return {
            "task": self.task,
            "origin": rel,
            "target": self.target,
            "scale": self.scale,
            "axis": self.axis,
            # The problem SIZE the score was measured at (spmm n/k, seeds) — a
            # dropped kwarg silently measures a different problem, so it must
            # travel with the number, not just target/scale/axis.
            "measure_kwargs": self._kwargs(),
            # Self-digest of the scoring config; lets a reader detect a manifest
            # edited after the run (target/scale/axis/measure_kwargs/files).
            "manifest_sha256": self.manifest_hash,
            "files": dict(self.pinned),
        }


def workspace_harness_root() -> Path:
    """``<workspace>/harnesses`` — where task harnesses are registered.

    ``ARI_WORKSPACE`` wins; otherwise this defers to
    :meth:`ari.paths.RuntimePathResolver.resolve_workspace_root`, which owns "what
    is the workspace root" (ARI_CHECKPOINT_DIR / ARI_ROOT / the repo checkout) and
    anchors on ``__file__``, never the cwd.

    Resolving from the cwd would be a trap created by moving the harnesses out of
    the package: the scorer used to be reached by ``import``, which no cwd can
    change. Run from a cwd that is not the repo root — a normal scheduler default
    — and no harness is found; because both call sites swallow that (seeding logs
    a warning; ``evaluate_sync`` has a blanket except), the run would not crash. It
    would score EVERY node 0.0 and read as total agent failure rather than a
    misconfiguration.

    Deferring (rather than re-implementing the precedence here) is the point: a
    second source of truth for the workspace root is the exact class of defect
    this registry exists to remove.
    """
    ws = os.environ.get("ARI_WORKSPACE")
    if ws:
        return Path(ws) / "harnesses"
    from ari.paths import RuntimePathResolver
    return RuntimePathResolver.resolve_workspace_root() / "harnesses"


def _load_manifest(d: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:  # py<3.11
        import tomli as tomllib  # type: ignore
    with (d / MANIFEST_NAME).open("rb") as fh:
        return tomllib.load(fh)


def _verify(d: Path, pinned: dict[str, str]) -> None:
    """Every pinned file must exist and match its digest, or refuse to measure."""
    for name, want in pinned.items():
        p = d / name
        if not p.is_file():
            raise HarnessIntegrityError(
                f"harness {d.name}: pinned file missing: {name}")
        got = sha256_file(p)
        if got != want:
            raise HarnessIntegrityError(
                f"harness {d.name}: {name} does not match the manifest "
                f"(pinned {want[:12]}…, found {got[:12]}…). The measurement "
                f"scaffolding was modified; refusing to score.")


def manifest_integrity_hash(man: dict[str, Any]) -> str:
    """A formatting-independent digest of the manifest's SCORING CONFIGURATION.

    ``[files]`` sha256s pin the scaffolding, but the manifest cannot pin its own
    body, so ``[harness]`` (target / scale / axis / target_env / entry),
    ``[measure_kwargs]`` (the problem size n/k/seed), and the ``[files]`` map
    itself are otherwise editable without tripping any check — silently
    rescaling every score. This hashes the parsed values (comments/whitespace do
    not matter), excluding the ``[integrity]`` block that carries this digest, so
    it can be self-pinned in the manifest and recomputed at load + recorded in
    provenance for later re-check.
    """
    import hashlib
    import json
    payload = {
        "harness": {k: (man.get("harness") or {})[k]
                    for k in sorted(man.get("harness") or {})},
        "measure_kwargs": man.get("measure_kwargs") or {},
        "files": man.get("files") or {},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True, default=str).encode()
    ).hexdigest()


def _verify_manifest_self(task: str, d: Path, man: dict[str, Any]) -> str:
    """Enforce the manifest's own ``[integrity].self_sha256`` if present, and
    return the computed digest (recorded in provenance so a reader can re-check
    the scoring config that produced a published number)."""
    got = manifest_integrity_hash(man)
    want = (man.get("integrity") or {}).get("self_sha256")
    if want and str(want) != got:
        raise HarnessIntegrityError(
            f"harness {task}: {MANIFEST_NAME} self-hash mismatch "
            f"(pinned {str(want)[:12]}…, found {got[:12]}…). A scoring constant "
            f"(target/scale/axis/measure_kwargs/files) was modified without "
            f"re-pinning; refusing to score.")
    return got


def _kwargs_from_manifest(man: dict[str, Any]) -> Callable[[], dict]:
    """Build the per-task ``measure_node`` kwargs resolver from ``[measure_kwargs]``.

    The kwargs are NOT uniform across tasks and a plausible uniformity silently
    rescales the measurement, so each harness DECLARES its own call:

        [measure_kwargs]                  # gemm: absent -> {} (never seeded)
        seed = {env = "ARI_SEED", default = 0}          # stencil/erfc/meshpart
        n = {env = "ARI_SPMM_N", default = 20000}       # spmm sizes, not seeds
        k = {env = "ARI_SPMM_K", default = 64}

    A bare literal (``n = 20000``) pins a value with no env override. The env
    value is coerced to the default's type; an uncoercible value falls back to
    the default rather than raising mid-run.
    """
    spec = man.get("measure_kwargs") or {}
    if not spec:
        return dict

    def _resolve() -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, v in spec.items():
            if not isinstance(v, dict):
                out[name] = v
                continue
            dflt = v.get("default")
            raw = os.environ.get(str(v["env"])) if v.get("env") else None
            if raw is None:
                out[name] = dflt
                continue
            try:
                out[name] = type(dflt)(raw) if dflt is not None else raw
            except (TypeError, ValueError):
                out[name] = dflt
        return out

    return _resolve


def _load_external(task: str, d: Path) -> Harness:
    """Load ``workspace/harnesses/<task>/`` — verify digests, then bind it."""
    man = _load_manifest(d)
    h = man.get("harness") or {}
    pinned = {k: str(v) for k, v in (man.get("files") or {}).items()}
    if not pinned:
        raise HarnessIntegrityError(
            f"harness {task}: {MANIFEST_NAME} pins no files. An unpinned harness "
            f"cannot be verified, so its scores are not falsifiable.")
    _verify(d, pinned)
    manifest_hash = _verify_manifest_self(task, d, man)

    scale, target = _describe_manifest(task, man)

    # The python half: an external harness supplies `module` (importable) or
    # `entry` (a file next to the manifest) exposing seed_work_dir/measure_node.
    mod = _import_entry(h, d, task)
    for fn in ("seed_work_dir", "measure_node"):
        if not callable(getattr(mod, fn, None)):
            raise HarnessIntegrityError(
                f"harness {task}: its module does not implement {fn}()")
    # kernels_dir: a harness that resolves its own fixtures (``__file__``-relative,
    # e.g. ``<dir>/gemm_kernels/``) is authoritative — the registry must not
    # second-guess where it compiles from, or the provenance copy would record a
    # different directory than the one actually measured. Flat layouts that define
    # no kernels_dir() fall back to the harness dir itself.
    _kdir = getattr(mod, "kernels_dir", None)
    return Harness(
        task=task, target=target, scale=scale, axis=_axis_of(task, man), origin=str(d),
        seed_work_dir=mod.seed_work_dir,
        kernels_dir=_kdir if callable(_kdir) else (lambda _d=str(d): _d),
        _measure_node=mod.measure_node,
        _kwargs=_kwargs_from_manifest(man), pinned=pinned,
        manifest_hash=manifest_hash,
    )


def _describe_manifest(task: str, man: dict[str, Any]) -> tuple[str, float]:
    """``(scale, target)`` from a manifest — the env override is DECLARED by the
    harness (``target_env``) instead of being a name the core happens to know."""
    h = man.get("harness") or {}
    scale = str(h.get("scale", "linear")).lower()
    if scale not in ("log", "linear"):
        raise HarnessIntegrityError(f"harness {task}: bad scale {scale!r}")
    target = float(h.get("target", 16.0))
    env = h.get("target_env")
    if env:
        try:
            target = float(os.environ.get(str(env), target))
        except ValueError:
            pass
    return scale, target


def _axis_of(task: str, man: dict[str, Any]) -> str:
    a = str((man.get("harness") or {}).get("axis", "speedup")).lower()
    if a not in ("speedup", "score"):
        raise HarnessIntegrityError(
            f"harness {task}: bad axis {a!r} (expected 'speedup' or 'score')")
    return a


def axis(task: str) -> str:
    """``"speedup"`` or ``"score"`` — the task's NATIVE outcome axis.

    Distinct from ``scale`` (log/linear), which is only how a speedup is squashed
    into ``[0,1]`` for BFTS selection. The axis decides how results may be
    ANALYSED: a speedup is a ratio, compared multiplicatively in log domain with a
    ratio margin; a score is already a bounded ``[0,1]`` fraction, compared
    additively in linear domain with an absolute margin. Getting this wrong does
    not mislabel a chart — it runs the equivalence test in the wrong domain, e.g.
    taking ``log`` of a ``[0,1]`` score against a ``log(1.05)`` margin.

    The harness declares it because only the harness knows: the evaluator infers
    it at measure time from the SHAPE ``measure_node`` returns (a ``score`` key vs
    a ``families`` map), which an analyser reading archived results cannot see
    without re-measuring.
    """
    task = (task or "").lower()
    d = workspace_harness_root() / task
    if not (d / MANIFEST_NAME).is_file():
        raise HarnessIntegrityError(_unknown(task))
    return _axis_of(task, _load_manifest(d))


def _import_entry(h: dict, d: Path, task: str):
    import importlib
    import importlib.util
    if h.get("module"):
        return importlib.import_module(str(h["module"]))
    entry = str(h.get("entry") or f"{task}_harness.py")
    p = d / entry
    if not p.is_file():
        raise HarnessIntegrityError(f"harness {task}: entry not found: {entry}")
    spec = importlib.util.spec_from_file_location(f"ari_harness_{task}", p)
    if spec is None or spec.loader is None:
        raise HarnessIntegrityError(f"harness {task}: cannot import {entry}")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def describe(task: str) -> tuple[float, str]:
    """Return ``(target, scale)`` for *task* WITHOUT importing its python entry.

    The evaluator's constructor needs the normalisation constants but must stay
    cheap and dependency-free — the old hardcoded table imported nothing, and
    importing a harness (numpy/scipy) just to read two numbers would be a
    regression. External harnesses declare both in ``harness.toml``, so this
    reads metadata only; digests are verified later, when a measurement is
    actually taken.
    """
    task = (task or "spmm").lower()
    d = workspace_harness_root() / task
    if (d / MANIFEST_NAME).is_file():
        scale, target = _describe_manifest(task, _load_manifest(d))
        return target, scale
    raise HarnessIntegrityError(_unknown(task))


def _unknown(task: str) -> str:
    avail = available_tasks()
    return (f"unknown task {task!r}: no {workspace_harness_root()/task/MANIFEST_NAME}. "
            f"Harnesses are not shipped inside ARI — register one under "
            f"{workspace_harness_root()}/<task>/. "
            + (f"Available: {', '.join(avail)}" if avail else
               "No harnesses are registered (is ARI_WORKSPACE set?)."))


def available_tasks() -> list[str]:
    """Tasks registered under ``workspace/harnesses/``. ARI ships none."""
    root = workspace_harness_root()
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and (d / MANIFEST_NAME).is_file())


def load(task: str | None = None) -> Harness:
    """Resolve the harness for *task* (default: ``$ARI_TASK``, else ``spmm``).

    An external harness registered in the workspace WINS over a packaged one of
    the same name — that is what lets a study pin its own frozen scaffolding
    next to its results instead of depending on whatever the installed ARI ships.
    """
    task = (task or os.environ.get("ARI_TASK", "spmm")).lower()
    d = workspace_harness_root() / task
    if (d / MANIFEST_NAME).is_file():
        return _load_external(task, d)
    raise HarnessIntegrityError(_unknown(task))
