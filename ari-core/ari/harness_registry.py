"""Task-harness registry: ARI ships no harnesses; the workspace supplies them.

A *harness* owns the task-specific half of scoring: it seeds a node's work_dir
with the frozen scaffolding, then compiles and measures the node's candidate,
returning ``{"compile_ok": bool, "families": {name: {"speedup": float,
"valid": bool}}}``. The task-INDEPENDENT half (the all-or-nothing validity gate,
the geomean, and the BFTS ranking value) stays in
:mod:`ari.evaluator.deterministic_evaluator` and is never delegated. For
speedup-shaped tasks the ranking value is the native valid geomean speedup, not
a target-normalized score.

Where harnesses live
--------------------
``$ARI_WORKSPACE/harnesses/<task>/`` — the frozen scaffolding plus a
``harness.toml`` declaring the task's native axis, compatibility target/scale,
``measure_node`` kwargs, and a sha256 for every file. ARI core contains NO task:
adding, changing or removing one never edits this repo. A benchmark is an
experiment asset with its own lifecycle, not a framework feature.

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
    scale: str                      # compatibility metadata; speedup ranking ignores it
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
    # work_dir-relative files that determine the score (candidate source + flags).
    # Empty when the harness declares none, which keeps the legacy whole-directory
    # sterility check.
    score_inputs: tuple[str, ...] = ()
    # Formatting-independent digest of the scoring config (target/scale/axis/
    # measure_kwargs/files); recorded in provenance so a reader can re-check that
    # the manifest that scored a published number was not later edited.
    manifest_hash: str = ""
    # What this harness says it is FOR. Empty when it has not been characterised;
    # a selector must read that as "unknown", not as "suitable".
    declares: "Declaration" = field(default_factory=lambda: Declaration())

    def measure(self, work_dir: str, **overrides: Any) -> dict:
        """Measure the node's candidate. ARI calls this; the node never sees it.

        The node's work_dir holds only the agent's candidate (plus seeded copies
        of the scaffolding for its own self-test, which do NOT participate). The
        driver/baseline compiled here come from this harness's own directory.
        """
        kwargs = self._kwargs()
        unknown = set(overrides) - set(kwargs) - {"reps", "seed"}
        if unknown:
            raise TypeError(
                f"harness {self.task}: unsupported measurement override(s): "
                f"{sorted(unknown)}")
        kwargs.update(overrides)
        return self._measure_node(work_dir, **kwargs)

    # What `profile` accepts BEYOND the manifest's own kwargs. The manifest keys
    # themselves (spmm's n/k) stay overridable exactly as they are for `measure`
    # -- choosing the size is the point of a profile. What this fixes is the
    # DEFAULT: it comes from [measure_kwargs], so a profile taken without saying
    # otherwise is taken at the size the score is taken at, instead of the
    # harness's own default, which for spmm is ~39x smaller.
    # `seed` is here for the same reason `measure` whitelists it: gemm declares
    # no [measure_kwargs] at all, so without it a caller could not choose one.
    _PROFILE_OVERRIDES = frozenset({"reps", "seed", "cases", "shapes", "families",
                                    "line_bytes"})

    def profile(self, work_dir: str, **overrides: Any) -> dict:
        """Hardware counters for the region this harness scores. NEVER a score.

        Applies the manifest's ``[measure_kwargs]`` exactly as :meth:`measure`
        does, so a profile is taken at the SCORED problem size. Calling
        ``profile_node`` directly bypasses that and lands on the harness's own
        default, which for spmm is ~39x smaller than the study size.
        """
        fn = getattr(self._measure_node, "__globals__", {}).get("profile_node")
        if not callable(fn):
            raise HarnessIntegrityError(
                f"harness {self.task}: does not implement profile_node(). Counters "
                f"are a property of a timed region; a score-shaped harness has none.")
        kwargs = self._kwargs()
        unknown = set(overrides) - set(kwargs) - self._PROFILE_OVERRIDES
        if unknown:
            raise TypeError(
                f"harness {self.task}: unsupported profile override(s): "
                f"{sorted(unknown)}")
        kwargs.update(overrides)
        return fn(work_dir, **kwargs)

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
            # Which harness answered this task, and what else could have. With a
            # pool the score is a property of the harness as much as the code,
            # so "we used the best one" is unfalsifiable unless the alternatives
            # are on the record next to the choice.
            "harness": origin.name,
            "alternatives": [n for n in harnesses_for(self.task)
                             if n != origin.name],
            "declares": {
                "question": self.declares.question,
                "denominator": self.declares.denominator,
                "resolves": self.declares.resolves,
                "resolves_measured_on": self.declares.resolves_measured_on,
                "blind_to": list(self.declares.blind_to),
            },
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


# What is NOT scored scaffolding, and so need not be pinned. The manifest cannot
# pin itself (its digest would have to contain itself); tests are the harness's
# own checks, not the thing being measured; build artefacts are derived.
_UNPINNED_OK = frozenset({MANIFEST_NAME})
_UNPINNED_SKIP_DIRS = frozenset({"tests", "__pycache__"})
_UNPINNED_SKIP_SUFFIXES = frozenset({".pyc", ".so"})


def unpinned_files(d: Path, pinned) -> list[str]:
    """Files present in harness dir *d* that ``[files]`` does not pin.

    The pin is a set of digests, so verifying it answers "did these files
    change" and NOT "is this every file that matters". Anything added to the
    directory afterwards is outside the manifest and freely editable, which is
    the whole guarantee inverted for exactly the file most likely to be added
    late — a new reference source is the score's denominator.
    """
    out = []
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(d)
        if rel.parts[0] in _UNPINNED_SKIP_DIRS or str(rel) in _UNPINNED_OK:
            continue
        if p.suffix in _UNPINNED_SKIP_SUFFIXES:
            continue
        if str(rel) not in pinned:
            out.append(str(rel))
    return out


def _verify_complete(d: Path, pinned: dict[str, str]) -> None:
    """Refuse a harness whose directory holds scaffolding the manifest ignores.

    ``_verify`` walks the KEYS of ``[files]``; a file the manifest never names is
    never hashed, so it passes every check by not being looked at. This was the
    rule ``workspace/regen_manifest.py`` already refused to regenerate under —
    but only at re-pin time, so a file added by hand afterwards stayed invisible
    to the scorer. It belongs at load, where the refusal reaches scoring.
    """
    missing = unpinned_files(d, set(pinned))
    if missing:
        raise HarnessIntegrityError(
            f"harness {d.name}: present but NOT pinned in [files]: "
            f"{', '.join(missing)}. An unpinned file in the harness directory is "
            f"scored scaffolding nobody is checking; refusing to score. Add it "
            f"to {MANIFEST_NAME} and re-pin with workspace/regen_manifest.py.")


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

    ``[declares]`` is included for the same reason, one level up. It is what a
    pool SELECTS on, so editing it changes which harness measures a study without
    changing a single scored byte: lowering a declared band from 0.251% to 0.01%
    makes the selector accept this harness for an effect it cannot resolve, and
    the result is a well-formed null that means nothing. A declaration outside
    the digest would be an unpinned scoring decision.
    """
    import hashlib
    import json
    # EVERYTHING except [integrity]. Naming four tables meant a fifth added
    # later sat outside the digest and could be edited without tripping the
    # self-hash — a scoring key nobody pinned, which is the exact hole [files]
    # exists to close one level down. Excluding [integrity] is structural: it
    # carries this digest and cannot contain itself.
    payload = {k: man[k] for k in sorted(man) if k != "integrity"}
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
    if not want:
        # Optional-when-absent meant a manifest could opt OUT of the check by
        # deleting one line, and the deletion looked like a manifest that simply
        # predated the field. A scoring config nobody pinned is not a weaker
        # guarantee, it is none.
        raise HarnessIntegrityError(
            f"harness {task}: {MANIFEST_NAME} has no [integrity].self_sha256. "
            f"The scoring config (target/scale/axis/measure_kwargs/files/"
            f"declares) would then be editable without tripping any check; "
            f"refusing to score. Re-pin with workspace/regen_manifest.py "
            f"(computed digest: {got}).")
    if str(want) != got:
        raise HarnessIntegrityError(
            f"harness {task}: {MANIFEST_NAME} self-hash mismatch "
            f"(pinned {str(want)[:12]}…, found {got[:12]}…). A scoring constant "
            f"(target/scale/axis/measure_kwargs/files/declares) was modified "
            f"without re-pinning; refusing to score.")
    return got


def _load_checked_manifest_metadata(task: str, d: Path) -> dict[str, Any]:
    """Load manifest metadata and fail closed on scoring-config edits.

    This intentionally does NOT import the harness or hash every pinned source
    file; ``load()`` owns that full verification. Metadata-only consumers such as
    ``describe()`` still read target/scale/axis, so they must at least enforce
    the manifest self-digest when it is present.
    """
    man = _load_manifest(d)
    _verify_manifest_self(task, d, man)
    return man


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
    _verify_complete(d, pinned)
    manifest_hash = _verify_manifest_self(task, d, man)

    scale, target = _describe_manifest(task, man)

    # The python half: an external harness supplies `module` (importable) or
    # `entry` (a file next to the manifest) exposing seed_work_dir/measure_node.
    mod = _import_entry({**h, "_pinned": tuple(pinned)}, d, task)
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
    # score_inputs: the work_dir-relative files that actually determine the score.
    # Only the harness knows this. Search control needs it to tell a real edit from
    # a re-measurement: judging "did the child change anything?" by diffing the whole
    # work_dir is useless, because every node rewrites bookkeeping files. A harness
    # that declares nothing keeps the old whole-directory behaviour.
    _si = getattr(mod, "SCORE_INPUTS", ())
    return Harness(
        task=task, target=target, scale=scale, axis=_axis_of(task, man), origin=str(d),
        seed_work_dir=mod.seed_work_dir,
        kernels_dir=_kdir if callable(_kdir) else (lambda _d=str(d): _d),
        _measure_node=mod.measure_node,
        _kwargs=_kwargs_from_manifest(man), pinned=pinned,
        manifest_hash=manifest_hash,
        score_inputs=tuple(str(x) for x in _si),
        declares=_declaration_of(task, man),
    )


@dataclass(frozen=True)
class Declaration:
    """What a harness says it is FOR, so a pool can be chosen between.

    A manifest already declares how to RUN a harness. It declares nothing about
    what the harness answers, what it costs, or what it cannot see -- which is
    exactly what selection needs. Everything here is optional: a harness that
    declares nothing is still loadable and still scores. It is simply not
    selectable on the axis it stayed silent about, and a selector must treat
    silence as "unknown", never as "fine".

    ``resolves`` is the measured band -- the smallest difference the harness can
    separate. It is the one field a selector must refuse to guess: choosing a
    harness with a 0.25% band for a study expecting a 0.1% effect produces a
    well-formed null result that means nothing. It therefore carries the
    conditions it was measured under, and a band with no measurement date is
    treated as undeclared.

    ``blind_to`` is not a disclaimer, it is data. It was MEASURED that the
    large-page policy moves one harness 5.9x and leaves two others inside the
    noise, because only the first has the candidate allocating and first-touching
    its own memory inside the timed window. That is a permanent property of those
    harnesses and belongs in the manifest rather than in someone's notes.
    """

    question: str = ""
    denominator: str = ""          # naive | competent_frozen | anchor_matched | best_known
    resolves: float | None = None  # measured band, as a fraction (0.00149 = 0.149%)
    resolves_measured_on: str = ""  # date; a band with no date is not a measurement
    resolves_reps: int | None = None
    cost_s: float | None = None
    requires: tuple[str, ...] = ()
    sees: tuple[str, ...] = ()
    blind_to: tuple[str, ...] = ()
    # Environment variables whose value the band was measured UNDER, and which
    # therefore must not differ at run time. `ARI_STENCIL_SHAPES` can replace the
    # scored problem outright without touching a single pinned byte: the manifest
    # hash does not move, `measure_kwargs` does not move, and the harness goes on
    # advertising a band it measured on a different problem. Naming the variable
    # here turns that from an unfalsifiable claim into a check.
    band_conditions: tuple[tuple[str, str], ...] = ()

    @property
    def band_is_measured(self) -> bool:
        """A number without a measurement behind it is worse than no number."""
        return self.resolves is not None and bool(self.resolves_measured_on)

    def band_condition_drift(self) -> list[str]:
        """Where the running environment differs from what the band assumed.

        An empty list is not proof of agreement: it also means the harness named
        no conditions. The distinction is the caller's to make, so this reports
        differences and ``band_conditions`` reports whether any were claimed.
        """
        import os as _os
        out = []
        for name, want in self.band_conditions:
            got = _os.environ.get(name)
            if (got or "") != (want or ""):
                out.append(f"{name}: band measured with {want!r}, now {got!r}")
        return out


_DENOMINATORS = ("naive", "competent_frozen", "anchor_matched", "best_known")


def _conditions(task: str, raw: dict) -> tuple[tuple[str, str], ...]:
    """``band_conditions`` as ordered (name, value) pairs."""
    v = raw.get("band_conditions")
    if v is None:
        return ()
    if not isinstance(v, dict):
        raise HarnessIntegrityError(
            f"harness {task}: [declares].band_conditions must be a table of "
            f"VARIABLE = \"value it was measured under\"")
    return tuple(sorted((str(k), "" if x is None else str(x)) for k, x in v.items()))


def _declaration_of(task: str, man: dict[str, Any]) -> Declaration:
    """Parse ``[declares]``. Absent is legal; malformed is not.

    Silence is a harness that has not been characterised yet. A wrong type or an
    unknown denominator is a harness whose author believed they had declared
    something -- that must fail loudly, or the selector reads a typo as silence
    and quietly considers the harness for work it cannot do.
    """
    raw = man.get("declares")
    if raw is None:
        return Declaration()
    if not isinstance(raw, dict):
        raise HarnessIntegrityError(
            f"harness {task}: [declares] must be a table, got {type(raw).__name__}")

    def _tuple(key: str) -> tuple[str, ...]:
        v = raw.get(key, ())
        if isinstance(v, str) or not isinstance(v, (list, tuple)):
            raise HarnessIntegrityError(
                f"harness {task}: [declares].{key} must be a list of strings")
        return tuple(str(x) for x in v)

    den = str(raw.get("denominator", ""))
    if den and den not in _DENOMINATORS:
        raise HarnessIntegrityError(
            f"harness {task}: [declares].denominator={den!r} is not one of "
            f"{_DENOMINATORS}. An unrecognised value would be read as 'no "
            f"denominator declared', which is how a naive denominator gets "
            f"selected for a study that needed a competent one.")

    band = raw.get("resolves")
    if band is not None:
        try:
            band = float(band)
        except (TypeError, ValueError):
            raise HarnessIntegrityError(
                f"harness {task}: [declares].resolves must be a number")
        if not 0 < band < 1:
            raise HarnessIntegrityError(
                f"harness {task}: [declares].resolves={band} is a FRACTION of "
                f"the measured value (0.00149 means 0.149%). A band of 1 or "
                f"more would let the selector accept this harness for any "
                f"effect size.")
    return Declaration(
        question=str(raw.get("question", "")),
        denominator=den,
        resolves=band,
        resolves_measured_on=str(raw.get("resolves_measured_on", "")),
        resolves_reps=(int(raw["resolves_reps"])
                       if raw.get("resolves_reps") is not None else None),
        cost_s=(float(raw["cost_s"]) if raw.get("cost_s") is not None else None),
        requires=_tuple("requires"), sees=_tuple("sees"),
        blind_to=_tuple("blind_to"),
        band_conditions=_conditions(task, raw),
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
    return _axis_of(task, _load_checked_manifest_metadata(task, d))


def _import_entry(h: dict, d: Path, task: str):
    import importlib
    import importlib.util
    if h.get("module"):
        # An importable module is resolved by sys.path, so its FILE need not be
        # in the harness directory and therefore need not be pinned — the one
        # route by which the scoring code could differ from what _verify just
        # checked. The capability is kept (a harness may ship as a package), but
        # only when the file it resolves to is inside this directory and pinned.
        mod = importlib.import_module(str(h["module"]))
        src = getattr(mod, "__file__", None)
        pinned = {str(k) for k in (h.get("_pinned") or ())}
        try:
            rel = str(Path(src).resolve().relative_to(d.resolve())) if src else None
        except ValueError:
            rel = None
        if rel is None or rel not in pinned:
            raise HarnessIntegrityError(
                f"harness {task}: [harness].module={h['module']!r} resolves to "
                f"{src or '<no file>'}, which is not a pinned file inside "
                f"{d}. The pins would then cover something other than the code "
                f"that measures; refusing to score. Use [harness].entry, or pin "
                f"the module's file in [files].")
        return mod
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

    Kept for compatibility with older evaluator configs and checkpoint
    provenance. Importing a harness (numpy/scipy) just to read two metadata
    values would be a regression, so this reads metadata only. The manifest
    self-digest is still checked here because these declarations travel with the
    scoring instrument; full file digests are verified later, when a measurement
    is actually taken.
    """
    task = (task or "spmm").lower()
    d = workspace_harness_root() / task
    if (d / MANIFEST_NAME).is_file():
        scale, target = _describe_manifest(task, _load_checked_manifest_metadata(task, d))
        return target, scale
    raise HarnessIntegrityError(_unknown(task))


def _unknown(task: str) -> str:
    avail = available_tasks()
    return (f"unknown task {task!r}: no {workspace_harness_root()/task/MANIFEST_NAME}. "
            f"Harnesses are not shipped inside ARI — register one under "
            f"{workspace_harness_root()}/<task>/. "
            + (f"Available: {', '.join(avail)}" if avail else
               "No harnesses are registered (is ARI_WORKSPACE set?)."))


def registered_harnesses() -> list[str]:
    """Every harness directory under ``workspace/harnesses/``. ARI ships none.

    A HARNESS is a directory; the TASK it serves is declared. The two used to be
    the same string, which made "one way of measuring" and "the scientific
    question" indistinguishable and left no room for a second harness to answer
    the same question differently.
    """
    root = workspace_harness_root()
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and (d / MANIFEST_NAME).is_file())


def _task_of(name: str) -> str:
    """The task a harness directory serves — declared, defaulting to its name.

    Reads only the manifest; it does not import the harness or verify digests,
    because enumerating the pool must not be as expensive as binding one.

    A manifest that does not parse RAISES rather than falling back to the
    directory name. Swallowing it looks harmless and is not: the harness would
    silently leave the pool it declared membership in, ``load(task)`` would stop
    seeing an ambiguity it should refuse, and the remaining harness would be
    bound without anyone choosing it. Failing to read a registration is not the
    same as a registration that says nothing.
    """
    d = workspace_harness_root() / name
    try:
        man = _load_manifest(d)
    except Exception as exc:
        raise HarnessIntegrityError(
            f"harness {name}: {MANIFEST_NAME} could not be read ({exc}). It "
            f"cannot be treated as serving its directory name -- that would "
            f"quietly remove it from the pool it may have declared.") from exc
    return str((man.get("harness") or {}).get("task", name)).lower()


def available_tasks() -> list[str]:
    """The distinct questions the pool can answer, not the harness count."""
    return sorted({_task_of(n) for n in registered_harnesses()})


def harnesses_for(task: str) -> list[str]:
    """Every harness directory serving *task*. More than one is the point."""
    task = task.lower()
    return [n for n in registered_harnesses() if _task_of(n) == task]


def load(task: str | None = None, *, harness: str | None = None) -> Harness:
    """Resolve a harness for *task* (default: ``$ARI_TASK``, else ``spmm``).

    An external harness registered in the workspace WINS over a packaged one of
    the same name — that is what lets a study pin its own frozen scaffolding
    next to its results instead of depending on whatever the installed ARI ships.

    When several harnesses serve one task this REFUSES to choose. Silently
    binding whichever sorted first would make the measurement depend on a
    directory name, and the resulting score would be attributed to the task
    rather than to the harness that produced it — which is precisely the
    conflation the pool exists to end. Name the harness, or ask
    ``ari.harness_select`` for a ranking on declared properties.
    """
    task = (task or os.environ.get("ARI_TASK", "spmm")).lower()
    # The choice travels the same way the task does, so every caller inherits it
    # without a new argument. It is RECORDED in provenance below: a study that
    # picked one of several harnesses and did not say which is not reproducible
    # on the axis that decides its numbers.
    harness = harness or os.environ.get("ARI_HARNESS") or None
    if harness:
        d = workspace_harness_root() / harness
        if not (d / MANIFEST_NAME).is_file():
            raise HarnessIntegrityError(_unknown(harness))
        served = _task_of(harness)
        if served != task:
            raise HarnessIntegrityError(
                f"harness {harness!r} serves task {served!r}, not {task!r}. "
                f"Binding it anyway would score one question with another "
                f"question's measurement.")
        return _load_external(served, d)

    candidates = harnesses_for(task)
    if len(candidates) > 1:
        raise HarnessIntegrityError(
            f"task {task!r} is served by {len(candidates)} harnesses "
            f"({', '.join(candidates)}) and no choice was made. Refusing to "
            f"pick one: the result would be a property of whichever name "
            f"sorted first, reported as a property of the task. Pass "
            f"harness=... (or ARI_HARNESS), or rank them with "
            f"`ari harness select`.")
    if candidates:
        return _load_external(task, workspace_harness_root() / candidates[0])

    # No harness DECLARES this task; fall back to the directory of that name so
    # a manifest without an explicit [harness].task keeps working.
    d = workspace_harness_root() / task
    if (d / MANIFEST_NAME).is_file():
        return _load_external(task, d)
    raise HarnessIntegrityError(_unknown(task))
