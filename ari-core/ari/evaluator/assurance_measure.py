"""Score a BFTS node against a PINNED PROBLEM instead of a workspace harness.

WHAT THIS REPLACES. The deterministic evaluator resolved its measurement through
``ari.harness_registry``, which reads ``$ARI_WORKSPACE/harnesses/<task>/`` and
imports a python module found there. That made a scored run depend on an
untracked directory sitting next to the repository: a checkout without it could
not score anything, and the module it imported was free to define its own timing,
its own flags and its own oracle. This module reaches the governed mechanism
instead -- a pinned problem, a registered family, and one shared instrument.

WHAT IT DELIBERATELY DOES NOT DO. It does not score. ``DeterministicEvaluator._score``
still owns the whole scoring contract: the geomean over the case set, the
"invalid if any case fails" rule, and the ranking value. This module only turns a
``NativePerfReportV1`` into the measurement dict that contract already consumes,
so there is exactly one place where a number becomes a rank.

THE TWO ERROR CLASSES ARE THE POINT. ``PerfBuildError`` means the CANDIDATE was
bad -- it did not compile, or its object failed the symbol audit -- and that is a
result: it comes back as ``compile_ok: False`` and scores 0.0. Everything else --
a problem that will not resolve, a case set whose pin moved, a reference that
would not build, a missing work dir -- is the INSTRUMENT failing, and it is
raised, because ``evaluate_sync`` turns a raised exception into an unranked
``infrastructure_error`` rather than into a zero that looks like a bad kernel.
Collapsing the two is how a broken harness produced a full sheet of zeros that
read as "every agent failed".
"""

from __future__ import annotations

import os
import json
import platform
import shlex
import subprocess
from pathlib import Path
from typing import Any

from ari.assurance.native_perf_common import PerfBuildError, PerfInfrastructureError
from ari.assurance.native_perf_measure import verify_performance
from ari.assurance.problems import LoadedProblemV1, ProblemError, load_problem, materialize

#: Where the agent states the toolchain it wants. Owned by the AGENT CONTRACT,
#: not by any one problem: every problem asks the same way, so a candidate that
#: moves compilers does so through one screened path. Both are also listed in a
#: problem's ``score_inputs``, because the prototype left the compiler file out
#: of that list and a node that changed ONLY its compiler then read as a pure
#: re-measurement to the sterile gate -- while moving the score across a
#: toolchain boundary.
CANDIDATE_FLAGS_FILE = "candidate_flags.txt"
CANDIDATE_COMPILER_FILE = "candidate_cc.txt"

#: Which problem this run measures. No default: ``ARI_TASK`` unset used to fall
#: through to SpMM, i.e. a typo scored a DIFFERENT benchmark and reported it
#: under the requested name.
from ari.assurance.models import HarnessTargetDeclarationV1

from ari.public.execution import WorkspaceRefV1

from ari.assurance.target_abi import abi_identity, problem_target_kind

PROBLEM_ENV = "ARI_PROBLEM"

#: Repetitions per case. ``validate`` is three, which is the smallest number
#: that has a spread at all; a median quoted without one is how this study
#: previously mistook run-to-run variance for an effect.
DEFAULT_TIER = "validate"


def problem_revision() -> str:
    revision = (os.environ.get(PROBLEM_ENV) or "").strip()
    if not revision:
        raise PerfInfrastructureError(
            f"{PROBLEM_ENV} is unset, so there is no question to measure. Name a "
            f"pinned problem revision; a default here would score a benchmark "
            f"nobody asked for and report it under the requested name.")
    return revision


def resolve() -> LoadedProblemV1:
    """The pinned problem for this run. Raises rather than guessing."""
    try:
        return load_problem(problem_revision())
    except ProblemError as exc:
        raise PerfInfrastructureError(str(exc)) from exc


def seed_work_dir(work_dir: str | Path,
                  problem: LoadedProblemV1 | None = None) -> dict[str, Any]:
    """Write the starting scaffolding into a node's work dir, ONCE.

    IDEMPOTENT BY CONSTRUCTION, and that is the whole point. In BFTS a child's
    work dir is a copy of its parent's, and the parent's candidate IS the
    handoff -- the thing the study exists to measure. Seeding unconditionally
    would overwrite it with the naive seed on every node, so every node would
    start from scratch while the run still reported a tree. So: if the scored
    input is already there, this node inherited one, and nothing is written.

    Returns the provenance record, so "the node started from the pinned
    scaffolding" is checkable rather than assumed.
    """
    loaded = problem or resolve()
    target = Path(work_dir)
    target.mkdir(parents=True, exist_ok=True)
    candidate = target / loaded.definition.score_inputs[0]
    if candidate.is_file():
        return {
            "problem_id": loaded.definition.id,
            "problem_revision": loaded.definition.revision,
            "problem_digest": loaded.digest,
            "seeded": [],
            "already_seeded": True,
            "note": "the scored input was already present, so this node "
                    "inherited a candidate and was not re-seeded",
        }
    return {**materialize(loaded, target), "already_seeded": False}


def _declared_text(work_dir: Path, name: str) -> str | None:
    """One line the agent may write. Absent and blank both mean 'unspecified'.

    Deliberately tolerant about the file and strict about the content: the flag
    screen and the compiler allowlist in the instrument decide what is actually
    used, and neither is reachable from here.
    """
    path = work_dir / name
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="strict").strip()
    except (OSError, UnicodeDecodeError):
        # A candidate cannot make the measurement fail by writing junk here; it
        # simply does not get the toolchain it asked for, and the report records
        # that it asked.
        return None
    return text or None


def report_to_measurement(report, *, compile_ok: bool = True) -> dict[str, Any]:
    """Turn a performance report into the dict ``_score`` already consumes.

    One case becomes one "family". The name is the evaluator's, and it predates
    this: what it means there is "an independently valid sub-measurement the
    geomean runs over", which is exactly what a case is.
    """
    families: dict[str, dict[str, Any]] = {}
    for case in report.case_results:
        # VALID MEANS THE MEASUREMENT COUNTS, NOT THAT IT WON. This is the
        # evaluator's sense of the word and it is not the harness's verdict.
        # ``verdict == "fail"`` covers two different things: a WRONG answer,
        # which is not a measurement of anything, and a CORRECT answer that was
        # slower than the frozen reference, which is a perfectly good
        # measurement of a slow kernel.
        #
        # Mapping the verdict straight onto validity collapsed the search. The
        # denominator here is a COMPETENT reference, so the seeded naive kernel
        # measures about 0.008-0.02x of it; every case would read invalid, the
        # geomean would be 0.0, and every node in the tree would rank 0.0 until
        # one happened to beat a tuned kernel outright. BFTS would have no
        # gradient to climb while the run still produced a tree.
        #
        # So validity is CORRECTNESS plus a completed repetition. The regression
        # verdict is a separate statement and travels in the reason and in
        # ``regression_verdict`` below, where nothing ranks on it.
        # Complete AND correct. Counting only the repetitions that survived let
        # a case that timed out after one of three rank as a finished
        # measurement carrying that one repetition's speedup.
        complete = len(case.repetitions) >= case.repetitions_requested
        correct = complete and all(r.correct for r in case.repetitions)
        # WHAT GOES IN A FAMILY IS TREATMENT TEXT. Scalars here reach
        # ``evaluation_cases`` and are rendered verbatim into the CHILD's prompt
        # (orchestrator/node_summary_view.py). This study compares handoff
        # arms, so adding a field here changes the thing being measured and
        # quietly makes runs incomparable with earlier ones.
        #
        # So this stays at the prototype's shape: the ratio, whether the
        # measurement counts, and how close the answer came to the correctness
        # bound -- which is the one diagnostic an agent can act on. The absolute
        # seconds, the spread, the toolchain quotient and the regression verdict
        # are audit material and travel below, where nothing renders them.
        entry: dict[str, Any] = {
            "valid": correct,
            "speedup": float(case.speedup),
        }
        # ABSENT IS NOT ZERO, AND IT IS NOT SMALL EITHER. ``max_rel_error`` is
        # ``None`` when the oracle's answer was not a finite number -- ``inf``
        # for a candidate whose output contains an infinity, ``NaN`` for one that
        # leaves the frozen driver's poisoned buffer in place (see
        # ``finite_ratio``). That is the WORST a repetition can do, not the best,
        # so a maximum taken over the repetitions that did produce a number would
        # hand the agent the residual of its good repetitions and call it the
        # worst. The list was also non-empty whenever it held only ``None``, so
        # ``max`` raised TypeError on exactly the case the nullability was for.
        #
        # So the scalar is published only when EVERY repetition reported one, and
        # is otherwise absent -- the same thing it already did for a case with no
        # repetitions at all, and the same reading: not established. It cannot
        # instead be reported as a sentinel or beside a new companion field,
        # because every scalar in a family is rendered verbatim into the child's
        # prompt and is therefore treatment text (see above).
        errors = [r.max_rel_error for r in case.repetitions]
        observed = [error for error in errors if error is not None]
        if errors and len(observed) == len(errors):
            entry["max_relative_error"] = float(max(observed))
        # Not a scalar, so ``_evaluation_cases`` drops it and it never reaches a
        # prompt; ``_measurement_audit`` keeps it, so it stays checkable.
        credited = [r.credited_seconds for r in case.repetitions]
        entry["diagnostics"] = [{
            "regression_verdict": case.verdict,
            "detail": case.detail,
            "relative_spread": case.relative_spread,
            "toolchain_gain": case.toolchain_gain,
            "credited_seconds": min(credited) if credited else None,
            # WHY the scalar above is missing, when it is. Without this a reader
            # of a checkpoint cannot tell a case that reported no residual
            # because nothing ran from one whose oracle answered a non-finite
            # number, and both look like a case that simply carried no field.
            "repetitions_without_max_rel_error": len(errors) - len(observed),
        }]
        # THE AUDIT RECORD IS A CLOSED CONTRACT. node_report.schema.json declares
        # each repetition as {index, status, valid, measurements} with
        # additionalProperties: false, so the typed fields are named and
        # everything else goes in the generic bag. Emitting the pydantic model's
        # own field names instead would have failed validation -- which is what
        # the schema is for, and what it caught.
        entry["repetitions"] = [
            {
                "index": r.index,
                "status": "ok" if r.correct else "failed_correctness",
                "valid": bool(r.correct),
                "measurements": {
                    key: value for key, value in (
                        ("input_seed", r.input_seed),
                        ("credited_seconds", r.credited_seconds),
                        ("reference_seconds", r.reference_seconds),
                        ("speedup", r.speedup),
                        ("matched_seconds", r.matched_seconds),
                        ("speedup_matched", r.speedup_matched),
                        ("toolchain_gain", r.toolchain_gain),
                        ("max_rel_error", r.max_rel_error),
                    ) if value is not None
                },
            }
            for r in case.repetitions
        ]
        families[case.case_id] = entry

    # Status follows the MEASUREMENT, for the same reason validity does. A
    # correct-but-slow candidate produced a good measurement of a slow kernel;
    # calling that "candidate_invalid" would mean the search could not tell it
    # from one that computed the wrong answer. ``_score`` re-derives this anyway
    # from the families, so this only has to be honest about which of the two
    # happened when something did go wrong.
    if report.build_error:
        # The candidate did not build. One report says so now, whichever entry
        # point produced it, so the worker and the evaluator cannot disagree
        # about whose fault it was.
        return {
            "compile_ok": False,
            "families": {},
            "evaluation_status": "candidate_invalid",
            "candidate_cflags": list(report.accepted_flags),
            "rejected_cflags": list(report.rejected_flags),
            "reason": f"candidate did not build: {report.build_error}",
            "problem_revision": report.problem_revision,
            "problem_digest": report.problem_digest,
            "dataset_revision": report.dataset_revision,
            "report_digest": report.report_digest,
        }
    every_case_correct = bool(families) and all(
        entry["valid"] for entry in families.values())
    if every_case_correct:
        status = "valid"
    elif any(entry["valid"] for entry in families.values()):
        status = "measurement_invalid"     # some case did not resolve
    else:
        status = "candidate_invalid"       # nothing it produced was right
    details = "; ".join(f"{c.case_id}: {c.detail}" for c in report.case_results)
    return {
        "compile_ok": compile_ok,
        "families": families,
        "evaluation_status": status,
        "candidate_cflags": list(report.accepted_flags),
        "rejected_cflags": list(report.rejected_flags),
        "reason": f"{report.verdict} against {report.problem_revision} "
                  f"on {report.dataset_revision}"
                  + (f" -- {details}" if details else ""),
        # The registered property's own answer, kept next to the ranking data
        # rather than folded into it: "did not regress" and "is this the best
        # candidate so far" are different questions and only the second ranks.
        "regression_verdict": report.verdict,
        "regression_threshold": report.regression_threshold,
        # Provenance a reader needs to know WHICH question produced these
        # numbers. Not scored; carried so a checkpoint is self-describing.
        "problem_revision": report.problem_revision,
        "problem_digest": report.problem_digest,
        "dataset_revision": report.dataset_revision,
        "report_digest": report.report_digest,
    }


def measure(work_dir: str, *, seed: int = 0, tier: str | None = None,
            regression_threshold: float = 1.0,
            run_timeout: float = 900.0) -> dict[str, Any]:
    """Measure the candidate in ``work_dir`` against this run's pinned problem.

    Shaped for ``DeterministicEvaluator(measure_fn=...)``. Raises on instrument
    failure; returns ``compile_ok: False`` on candidate failure. See the module
    docstring for why that distinction is load-bearing.
    """
    loaded = resolve()
    definition = loaded.definition
    root = Path(work_dir or "")
    if not root.is_dir():
        raise PerfInfrastructureError(
            f"work dir does not exist, so there is nothing to score: {root!r}")
    candidate = root / definition.score_inputs[0]
    if not candidate.is_file():
        # The seed puts this file there, so its absence is the harness's fault
        # and not the candidate's -- an agent that deleted it would have had to
        # be handed a work dir that was never seeded.
        raise PerfInfrastructureError(
            f"the scored input {definition.score_inputs[0]!r} is not in the work "
            f"dir; it is seeded by materialize(), so this node was never seeded")

    try:
        report = verify_performance(
            loaded, candidate,
            tier=tier or os.environ.get("ARI_PERF_TIER") or DEFAULT_TIER,
            seed=seed,
            candidate_compiler=_declared_text(root, CANDIDATE_COMPILER_FILE),
            candidate_flags=_declared_text(root, CANDIDATE_FLAGS_FILE),
            regression_threshold=regression_threshold,
            run_timeout=run_timeout)
    except PerfBuildError as exc:
        # The candidate did not build, or its object failed the symbol audit.
        # That is a result about the candidate, so it is scored, not raised.
        return {
            "compile_ok": False,
            "families": {},
            "evaluation_status": "candidate_invalid",
            "candidate_cflags": [],
            "rejected_cflags": [],
            "reason": f"candidate did not build: {exc}",
            "problem_revision": definition.revision,
            "problem_digest": loaded.digest,
        }
    measurement = report_to_measurement(report)
    # The candidate built and was measured, so it is also the thing a governed
    # Harness should judge. Declaring it here is what joins the two halves: the
    # Harness reads assurance_target.json and, finding none, recorded every node
    # as `tampered`. Best-effort on purpose -- a run whose assurance is off must
    # not lose its score because a shared-library link failed.
    try:
        declaration = declare_target(root, loaded)
    except TargetABIMismatch as exc:
        # Not the candidate's failure to build and not the instrument's: the
        # artifact simply is not the kind of thing this Harness verifies.
        measurement["assurance_target_error"] = f"ABI mismatch: {exc}"
    except PerfBuildError as exc:
        measurement["assurance_target_error"] = f"candidate did not link: {exc}"
    except Exception as exc:  # instrument-side; the score is still valid
        measurement["assurance_target_error"] = f"{type(exc).__name__}: {exc}"
    else:
        if declaration is not None:
            measurement["assurance_target"] = declaration["logical_name"]
            measurement["assurance_target_digest"] = declaration["target_digest"]
    return measurement


__all__ = [
    "CANDIDATE_COMPILER_FILE",
    "CANDIDATE_FLAGS_FILE",
    "DEFAULT_TIER",
    "PROBLEM_ENV",
    "measure",
    "problem_revision",
    "report_to_measurement",
    "resolve",
    "seed_work_dir",
]


#: What the governed Harness reads to learn WHICH artifact it is judging.
#: Nothing in the repository wrote this file, so a governed run resolved its
#: Harness, locked it, and then recorded ``tampered`` on every node: the scoring
#: path measures the candidate through a driver EXECUTABLE, while the Harness
#: verifies a shared LIBRARY it is pointed at. The two halves were never joined.
TARGET_DECLARATION_FILE = "assurance_target.json"

#: The library the declaration points at. Named for the entry point rather than
#: the candidate file so a problem whose scored input is not C still reads.
_TARGET_LIBRARY = "assurance_target.so"


class TargetABIMismatch(RuntimeError):
    """The built artifact does not implement the contract it would declare."""


def _missing_abi_symbols(library: Path, required: tuple[str, ...]) -> list[str]:
    """Which required symbols the built library does not resolve.

    Resolved through ctypes, the same way the verifier resolves them, so this
    check and the check that matters cannot disagree about what "exported"
    means.
    """
    if not required:
        return []
    import ctypes

    try:
        handle = ctypes.CDLL(str(library))
    except OSError as exc:
        raise TargetABIMismatch(f"built library will not load: {exc}") from exc
    missing = []
    for name in required:
        try:
            getattr(handle, name)
        except AttributeError:
            missing.append(name)
    return missing


def declare_target(work_dir: str | Path,
                   problem: "LoadedProblemV1 | None" = None) -> dict[str, Any] | None:
    """Build the scored candidate as a shared library and declare it.

    Compiled with the candidate's OWN declared compiler and flags. Using the
    instrument's defaults instead would verify a different program than the one
    that was timed -- ``-ffast-math`` alone changes what the oracle sees.

    Returns the declaration document, or ``None`` when this problem's family
    declares no ABI identity (nothing to point a Harness at).
    """
    loaded = problem or resolve()
    definition = loaded.definition
    root = Path(work_dir)
    abi = abi_identity(definition.family)
    if abi is None:
        return None

    candidate = root / definition.score_inputs[0]
    if not candidate.is_file():
        raise PerfInfrastructureError(
            f"cannot declare a Harness target: {candidate.name} is not in the "
            f"work dir, so there is no candidate to build")
    header = root / definition.scaffolding.contract_header
    compiler = _declared_text(root, CANDIDATE_COMPILER_FILE) or os.environ.get(
        "ARI_PERF_CC") or "cc"
    flags = shlex.split(_declared_text(root, CANDIDATE_FLAGS_FILE) or "")
    library = root / _TARGET_LIBRARY
    argv = [compiler, "-shared", "-fPIC", *flags,
            f"-I{header.parent}", str(candidate), "-o", str(library)]
    completed = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    if completed.returncode != 0:
        # The candidate's, not the instrument's: it compiled for the timed
        # driver, so a failure here is about THIS link and is reported as the
        # candidate's rather than raised as an outage.
        raise PerfBuildError(
            f"candidate did not link as a shared library: "
            f"{completed.stderr.strip()[:2000]}")

    workspace = WorkspaceRefV1(root=str(root))
    # THE PROBLEM DECIDES WHICH CONTRACT, and the artifact only decides whether
    # it keeps it. Asking the built library first looks equivalent and is not: a
    # candidate that exports BOTH the problem's entry point and the family's ABI
    # symbols would be declared a shared library here, while the resolver -- which
    # runs before any candidate exists and can only read the pinned problem --
    # has already stamped this run's atoms ``benchmark-submission``. The
    # declaration and the resolution would then disagree, the resolved Harness
    # would be inapplicable to the declared target, and the node would get no
    # verification at all with nothing reporting an error. Both sides now read
    # ``problem_target_kind``, which is the sentence "these two cannot come to
    # disagree" made true rather than asserted.
    expected_kind = problem_target_kind(definition.entry_point, definition.family)
    native_contract = expected_kind == abi.target_kind
    missing = _missing_abi_symbols(library, abi.exported_symbols) if native_contract else []
    if native_contract and not missing:
        # Declaring `interface_contract` asserts this artifact keeps that
        # contract. Unchecked, the assertion was simply false: a candidate
        # exporting only the problem's own entry point was declared conformant
        # to gemm-c-abi/v1, and the verifier failed 33 of 33 cases with
        # "missing ari_gemm_f32 symbol" -- every error exactly 0.0, because the
        # kernel was never entered.
        logical_name, kind, contract = (
            _TARGET_LIBRARY, abi.target_kind, abi.interface_contract)
    elif not _missing_abi_symbols(library, (definition.entry_point,)):
        # THE CONTRACT THE CANDIDATE ACTUALLY KEEPS. It was written against this
        # problem's header, so the ARI-native ABI is the wrong thing to have
        # asked it for, and refusing outright left the node with no verifiable
        # target at all -- true, but only because the question had been put
        # wrongly. The problem's own correctness Harness verifies the SOURCE
        # against the SOURCE's contract, so that is what is declared, and the
        # claim is checked the same way the other one is: the object built from
        # this candidate exports the entry point the problem declares.
        #
        # Named after the pinned problem revision rather than the family, so it
        # cannot collide with gemm-c-abi/v1, and so a Harness pinning this
        # contract and pinning this problem cannot come to disagree.
        logical_name = definition.score_inputs[0]
        kind, contract = "benchmark-submission", f"problem:{definition.revision}"
    else:
        # Neither contract. Refusing is the honest outcome: the node then has no
        # verifiable target, which is true, instead of a conformance claim it
        # does not meet.
        wanted = (f"{abi.interface_contract} ({', '.join(abi.exported_symbols)})"
                  if native_contract
                  else f"problem:{definition.revision} ({definition.entry_point!r})")
        raise TargetABIMismatch(
            f"candidate does not implement the contract this problem is verified "
            f"under -- {wanted}: {library.name} exports neither those symbols nor "
            f"{definition.entry_point!r}"
        )

    declaration = HarnessTargetDeclarationV1.create(
        logical_name=logical_name,
        target_kind=kind,
        subject_type=abi.subject_type,
        language=abi.language,
        hardware="cpu",
        architecture=platform.machine(),
        # From the family's ABI record, which is a statement about the family's
        # numeric type and is true of both contracts. Inventing one here would
        # be a third place dtype is decided.
        dtype=abi.dtype,
        interface_contract=contract,
        target_digest=workspace.file_digest(logical_name),
    )
    document = declaration.model_dump(mode="json")
    workspace.atomic_write_bytes(
        TARGET_DECLARATION_FILE,
        (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2)
         + "\n").encode("utf-8"),
    )
    return document
