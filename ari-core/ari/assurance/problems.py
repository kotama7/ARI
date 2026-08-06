"""A research problem as a pinned asset, so problems can be free without the
instrument becoming free with them.

WHY THIS EXISTS. The scored task used to be a constant: three names in a
``Literal``, scaffolding at a path built from one of those names, a goal
statement in an untracked tree, and a size passed as a request parameter. Adding
a research theme therefore meant editing ARI core, and every one of the choices
that make a measurement mean something -- which files the agent starts from,
what it is asked to do, which file is scored, what it is compared against, at
what size -- was made once, invisibly, in a different place from the others.

WHAT IS FREE AND WHAT IS NOT. A problem definition may supply the kernel
contract, the frozen driver, the reference, the seed candidate, the case set,
the entry point, the goal text and the ranking axis. It may NOT supply compiler
flags, the timed window, the thread regime, the oracle protocol, or the rules by
which the reference is built. That boundary is not a convention to be reviewed:
``StrictModel`` forbids unknown keys and this schema has no field for any of
them, so a problem file that tried would fail to load. This is what lets a
problem be pinned WITHOUT being approved -- an unsigned problem supplies inputs,
it cannot weaken the instrument that measures them.

WHY PINNED AT ALL, THEN. Not for trust -- for comparability. Two runs of "the
same" problem are only comparable if they started from the same scaffolding and
were asked the same question, and the goal statement is as much an experimental
condition as the problem size is. An unpinned prompt silently makes runs
incomparable while every artifact still claims they measured one thing. So a
problem carries a digest over its declaration AND every file it names, and a run
records it.

WHAT IS DELIBERATELY NOT HANDED TO THE AGENT. ``materialize`` seeds the contract
header, the driver and a correct-but-unoptimised candidate. It does NOT seed the
reference: the reference is the denominator, and a work dir containing it turns
the task into a copy.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from ari.protocols.integrity import StrictModel, bytes_digest, canonical_digest


PROBLEM_MANIFEST_NAME = "problem.yaml"

#: The goal statement, written into the work dir under a fixed name so a reader
#: of a finished run can see the question that was actually asked rather than
#: the one the repository holds today.
PROBLEM_STATEMENT_NAME = "problem_statement.md"

#: A ranking axis is declared because a speedup and a bounded score are not the
#: same number and must not be averaged as though they were. The evaluator owns
#: the reduction; a problem only says which axis its measurements live on.
ProblemAxis = Literal["speedup", "bounded_score"]

#: Same vocabulary the prototype's harness manifests used, kept so a denominator
#: means one thing across both.
ProblemDenominator = Literal["naive", "competent_frozen", "anchor_matched",
                             "best_known"]

_C_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BARE_FILENAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")


class ProblemError(RuntimeError):
    """A problem definition is missing, malformed, or does not match its pin."""


def _bare(value: str, what: str) -> str:
    """Reject anything that is not a plain filename inside the problem dir.

    ``materialize`` writes these names into a work dir and ``load_problem``
    reads them from the problem dir; a ``..`` or a leading ``/`` in either
    direction would let a problem file reach outside its own bundle. A problem
    is unapproved by design, so this is the check that keeps that safe.
    """
    if not _BARE_FILENAME.fullmatch(value or ""):
        raise ValueError(
            f"{what}={value!r} must be a plain filename inside the problem "
            f"directory, with no path separator and no '..'")
    return value


class ProblemScaffoldingV1(StrictModel):
    """The files a problem is made of. All relative to the problem directory."""

    #: Declares the signature the candidate must implement. Reached through
    #: ``-I`` at compile time, never copied next to the candidate, because a
    #: quoted include searches the including file's directory first.
    contract_header: str
    #: The frozen main: reads the problem, first-touches, times ONE call.
    driver: str
    #: The denominator. Built by the instrument's rules, not the problem's.
    reference: str
    #: Correct, unoptimised, and what the agent starts from. Not the reference.
    seed_candidate: str
    #: The scored driver plus a counter gate, when the problem supports
    #: profiling. Absent means profiles are simply unavailable for it.
    profiled_driver: str | None = None
    #: The parity probe's two negative controls, which must keep this problem's
    #: contract and so cannot live in ARI. They must fail for DIFFERENT reasons
    #: -- one on the ratio, one on the oracle -- or the probe cannot tell a
    #: performance harness from a stopwatch. Optional here and REQUIRED by the
    #: probe: a problem without them is measurable but not registrable, which is
    #: the honest split, because supplying them is what makes the evidence a
    #: human signs mean anything.
    negative_control_slow: str | None = None
    negative_control_wrong: str | None = None

    @field_validator("contract_header", "driver", "reference", "seed_candidate")
    @classmethod
    def _files_are_bare(cls, value: str, info) -> str:
        return _bare(value, f"scaffolding.{info.field_name}")

    @field_validator("profiled_driver", "negative_control_slow",
                     "negative_control_wrong")
    @classmethod
    def _optional_file_is_bare(cls, value: str | None, info) -> str | None:
        return None if value is None else _bare(value, f"scaffolding.{info.field_name}")

    def declared_files(self) -> tuple[str, ...]:
        names = [self.contract_header, self.driver, self.reference,
                 self.seed_candidate]
        names += [name for name in (self.profiled_driver,
                                    self.negative_control_slow,
                                    self.negative_control_wrong) if name]
        return tuple(names)


class ProblemDefinitionV1(StrictModel):
    """One research problem: what is asked, what is scored, against what.

    Closed schema on purpose -- see the module docstring. There is no field here
    for a compiler flag, a repetition count, a timed window or an oracle
    tolerance, and ``extra="forbid"`` means a problem that tried to add one
    would not load rather than being quietly ignored.
    """

    schema_version: Literal["ari.harness-problem/v1"] = "ari.harness-problem/v1"
    #: Stable name of the QUESTION. Two revisions of a problem share an id.
    id: str
    #: What a manifest pins and a run records, e.g. ``gemm-dense-fp64/v1@2026q3``.
    revision: str
    #: Which oracle and problem generator measure it. This is the one thing a
    #: problem cannot express as data -- "the residual bound for a dense GEMM"
    #: is code -- so it names a registered plugin instead of ARI naming the
    #: problem. Adding a family is still an ARI change; adding a PROBLEM is not.
    family: str
    #: The symbol the candidate must define, audited at the object level.
    entry_point: str
    description: str
    scaffolding: ProblemScaffoldingV1
    #: The file(s) the agent edits and the evaluator compiles. First one is the
    #: candidate; the seed candidate is written to it by ``materialize``.
    score_inputs: tuple[str, ...] = Field(min_length=1)
    #: A pinned case set, by revision. The size stays data.
    case_set: str
    #: Where the parity probe certifies, if not the scored set. Separate so a
    #: probe can be cheap without changing what a scored run measures. Still a
    #: pinned set, still checked against the family, and the probe refuses one
    #: that declares ``resolves: false`` -- an instrument certified at a size
    #: where its own spread swamps the difference has not been certified.
    parity_case_set: str | None = None
    axis: ProblemAxis
    denominator: ProblemDenominator
    #: The 課題文. Pinned with everything else because a prompt is an
    #: experimental condition: change it and the runs stop being comparable.
    goal: str

    @field_validator("id", "revision", "family", "case_set", "description", "goal")
    @classmethod
    def _not_blank(cls, value: str, info) -> str:
        if not (value or "").strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("entry_point")
    @classmethod
    def _entry_point_is_a_symbol(cls, value: str) -> str:
        if not _C_IDENTIFIER.fullmatch(value or ""):
            raise ValueError(f"entry_point={value!r} is not a C identifier")
        return value

    @field_validator("score_inputs")
    @classmethod
    def _score_inputs_are_bare(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_bare(item, "score_inputs") for item in value)


class LoadedProblemV1(StrictModel):
    """A problem definition together with where it came from and its digest."""

    definition: ProblemDefinitionV1
    #: Absolute path of the problem directory. Also the include root a driver
    #: and a candidate are compiled against.
    directory: Path
    #: Covers the declaration AND every file it names. A scaffolding edit is a
    #: different problem, which is the point: it would otherwise be possible to
    #: change what the agent starts from without changing anything a run records.
    digest: str
    #: Per-file digests, so a reader can see WHICH file moved.
    file_digests: tuple[tuple[str, str], ...]

    model_config = StrictModel.model_config | {"arbitrary_types_allowed": True}

    def path(self, name: str) -> Path:
        return self.directory / name


def problems_root() -> Path:
    configured = os.environ.get("ARI_HARNESS_PROBLEMS")
    if configured:
        return Path(configured)
    return (Path(__file__).resolve().parents[2]
            / "config" / "harnesses" / "problems")


def _read_manifest(path: Path) -> dict:
    import yaml as _yaml

    return _yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def registered_problems() -> tuple[str, ...]:
    """Every problem revision on disk. Empty is legal: ARI ships no problems."""
    root = problems_root()
    if not root.is_dir():
        return ()
    found = []
    for manifest in sorted(root.glob(f"*/{PROBLEM_MANIFEST_NAME}")):
        try:
            found.append(str(_read_manifest(manifest).get("revision") or ""))
        except Exception:                      # a broken file is reported by load
            continue
    return tuple(item for item in found if item)


def load_problem(revision: str) -> LoadedProblemV1:
    """Resolve a problem revision to its declaration, files and digest.

    Raises rather than falling back. A problem that cannot be resolved is not a
    problem measured at defaults -- the prototype's unknown-task fallthrough
    scored a DIFFERENT benchmark and reported it under the requested name.
    """
    root = problems_root()
    if not root.is_dir():
        raise ProblemError(f"no problem directory at {root}")
    for manifest in sorted(root.glob(f"*/{PROBLEM_MANIFEST_NAME}")):
        try:
            raw = _read_manifest(manifest)
        except Exception as exc:
            raise ProblemError(
                f"problem manifest {manifest} could not be read: {exc}") from exc
        if str(raw.get("revision", "")) != revision:
            continue
        try:
            definition = ProblemDefinitionV1.model_validate(raw)
        except Exception as exc:
            raise ProblemError(f"problem {revision!r} is malformed: {exc}") from exc
        directory = manifest.parent
        digests: list[tuple[str, str]] = [
            (PROBLEM_MANIFEST_NAME, bytes_digest(manifest.read_bytes()))
        ]
        for name in definition.scaffolding.declared_files():
            path = directory / name
            if not path.is_file():
                raise ProblemError(
                    f"problem {revision!r} names {name!r}, which is not a file "
                    f"in {directory}")
            digests.append((name, bytes_digest(path.read_bytes())))
        return LoadedProblemV1(
            definition=definition,
            directory=directory,
            digest=canonical_digest(tuple(digests)),
            file_digests=tuple(digests),
        )
    raise ProblemError(
        f"no registered problem {revision!r}; a problem is chosen by naming a "
        f"pinned revision. Known: {list(registered_problems())}")


def materialize(problem: LoadedProblemV1, work_dir: str | Path) -> dict[str, Any]:
    """Seed a work dir from a problem, and record exactly what was written.

    This is the ``seed_work_dir`` equivalent. It writes the contract header, the
    frozen driver, the goal statement, and the seed candidate under the first
    scored input name -- and nothing else. The reference is withheld on purpose:
    it is the denominator, so seeding it would make the task a copy.

    Returns a provenance record rather than nothing, because "the agent started
    from the pinned scaffolding" is otherwise an unfalsifiable claim.
    """
    target = Path(work_dir)
    if not target.is_dir():
        raise ProblemError(f"work dir does not exist: {target}")
    definition = problem.definition
    written: list[tuple[str, str]] = []

    for name in (definition.scaffolding.contract_header,
                 definition.scaffolding.driver):
        shutil.copy2(problem.path(name), target / name)
        written.append((name, bytes_digest((target / name).read_bytes())))

    candidate_name = definition.score_inputs[0]
    shutil.copy2(problem.path(definition.scaffolding.seed_candidate),
                 target / candidate_name)
    written.append((candidate_name,
                    bytes_digest((target / candidate_name).read_bytes())))

    statement = target / PROBLEM_STATEMENT_NAME
    statement.write_text(definition.goal, encoding="utf-8")
    written.append((PROBLEM_STATEMENT_NAME, bytes_digest(statement.read_bytes())))

    return {
        "problem_id": definition.id,
        "problem_revision": definition.revision,
        "problem_digest": problem.digest,
        "entry_point": definition.entry_point,
        "score_inputs": list(definition.score_inputs),
        "case_set": definition.case_set,
        "axis": definition.axis,
        "denominator": definition.denominator,
        "seeded": [{"name": name, "sha256": digest} for name, digest in written],
        # Named so a reader does not have to infer it from an absence.
        "withheld": [definition.scaffolding.reference],
    }


__all__ = [
    "PROBLEM_MANIFEST_NAME",
    "PROBLEM_STATEMENT_NAME",
    "LoadedProblemV1",
    "ProblemAxis",
    "ProblemDefinitionV1",
    "ProblemDenominator",
    "ProblemError",
    "ProblemScaffoldingV1",
    "load_problem",
    "materialize",
    "problems_root",
    "registered_problems",
]
