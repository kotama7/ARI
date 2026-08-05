"""Choose a harness from the pool, on what it declares and never on results.

WHY THIS IS A SEPARATE MODULE. A selector that ranks harnesses by the score they
produce is a machine for score hacking, and it would be an easy accident --
"choose the harness under which the candidate does best" is a natural sentence
and a fatal criterion. The defence here is structural rather than a convention:
this module imports nothing that can score, takes no work_dir, and is given no
path to a result. It sees ``Declaration`` objects and the requirement, and
nothing else. If a future edit needs a score in here, that is the signal that
something has gone wrong, not that an import is missing.

WHAT IT DOES. Given a requirement -- the effect size the study must resolve, the
time budget per scoring, the capabilities the machine actually has, the axes the
question depends on -- it partitions the pool into eligible and rejected, and
says why for each. It ranks, it does not decide: the operator chooses from a
table that shows its work. Automatic mode applies a policy to the same ranking
and records the identical evidence.

SILENCE IS NOT SUITABILITY. A harness that declares no band is not a harness with
a good band. Asked to guarantee a resolution, the selector rejects it. This is
the whole reason `erfc` and `meshpart` declare no band rather than a plausible
one: nobody measured it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class Requirement:
    """What the study needs, stated before anything is measured."""

    # The smallest effect the study must be able to see, as a fraction. A
    # harness whose band is wider than this cannot answer the question: it will
    # return a well-formed null that means nothing.
    resolve: float | None = None
    budget_s: float | None = None          # seconds per scoring
    # Capabilities the machine actually has. Probed by executing, not by reading
    # a list of names -- a compiler that is installed but rejects the flags this
    # harness passes is not a capability.
    have: tuple[str, ...] = ()
    # Axes the question depends on. A harness blind to any of them cannot answer
    # it, however good its band.
    must_see: tuple[str, ...] = ()
    denominator: str = ""                  # required denominator, if the study fixes one


@dataclass
class Verdict:
    task: str
    eligible: bool
    reasons: list[str] = field(default_factory=list)   # why not, or what qualified it
    margin: float | None = None                        # band headroom, higher is better


def _band_verdict(d, req: Requirement, v: Verdict) -> None:
    if req.resolve is None:
        return
    if not d.band_is_measured:
        v.eligible = False
        v.reasons.append(
            "no measured band: this harness has never been characterised, so "
            "it cannot be promised to resolve anything. Silence is not a good "
            "band -- measure it (tools/measure_resolution_band.py) or choose "
            "another harness.")
        return
    if d.resolves >= req.resolve:
        v.eligible = False
        v.reasons.append(
            f"band {d.resolves*100:.3f}% is wider than the {req.resolve*100:.3f}% "
            f"effect this study must see. Running it would produce a clean null "
            f"result that says nothing about the hypothesis.")
        return
    drift = d.band_condition_drift() if hasattr(d, "band_condition_drift") else []
    if drift:
        v.eligible = False
        v.reasons.append(
            "the band was measured under conditions this run does not match, "
            "so it describes a different measurement: " + "; ".join(drift))
        return

    v.margin = req.resolve / d.resolves
    v.reasons.append(
        f"band {d.resolves*100:.3f}% resolves the {req.resolve*100:.3f}% target "
        f"with {v.margin:.1f}x headroom (measured {d.resolves_measured_on}"
        + (f", {d.resolves_reps} reps" if d.resolves_reps else "") + ")")


def evaluate(task: str, declares, req: Requirement) -> Verdict:
    """One harness against one requirement. Declarations only."""
    v = Verdict(task=task, eligible=True)
    _band_verdict(declares, req, v)

    if req.denominator and declares.denominator != req.denominator:
        v.eligible = False
        v.reasons.append(
            f"denominator is {declares.denominator or 'undeclared'}, the study "
            f"requires {req.denominator}")

    missing = [c for c in declares.requires if req.have and c not in req.have]
    if missing:
        v.eligible = False
        v.reasons.append(
            f"needs {missing} which this machine was not probed to have")

    blind = [a for a in req.must_see if a in declares.blind_to]
    if blind:
        v.eligible = False
        v.reasons.append(
            f"structurally blind to {blind}: the question depends on an axis "
            f"this harness cannot observe, so a good band does not help")

    unclaimed = [a for a in req.must_see
                 if a not in declares.sees and a not in declares.blind_to]
    if unclaimed:
        v.eligible = False
        v.reasons.append(
            f"says nothing about {unclaimed} -- neither seen nor declared "
            f"blind. Undeclared is unknown, and an unknown axis cannot be "
            f"assumed observable.")

    if req.budget_s is not None:
        if declares.cost_s is None:
            v.reasons.append("cost not declared; budget not checked")
        elif declares.cost_s > req.budget_s:
            v.eligible = False
            v.reasons.append(
                f"{declares.cost_s:.1f}s per scoring exceeds the "
                f"{req.budget_s:.1f}s budget")
    return v


def rank(pool: Sequence[tuple[str, object]], req: Requirement) -> list[Verdict]:
    """Every harness judged, eligible ones first, widest headroom first.

    Rejected harnesses stay in the result. A selector that returned only the
    winners would hide the fact that the pool had two candidates and one was
    dropped for a reason the operator might disagree with.
    """
    verdicts = [evaluate(task, d, req) for task, d in pool]
    verdicts.sort(key=lambda v: (not v.eligible, -(v.margin or 0), v.task))
    return verdicts


def format_table(verdicts: Sequence[Verdict]) -> str:
    out = []
    for v in verdicts:
        head = "ELIGIBLE" if v.eligible else "rejected"
        margin = f"  headroom {v.margin:.1f}x" if v.margin else ""
        out.append(f"{head:9s} {v.task}{margin}")
        for r in v.reasons:
            out.append(f"            - {r}")
    if not any(v.eligible for v in verdicts):
        out.append("")
        out.append("NO HARNESS IN THE POOL CAN ANSWER THIS QUESTION.")
        out.append("That is a result: either the requirement is wrong, or the")
        out.append("pool needs a harness that does not exist yet. Running the")
        out.append("closest one anyway produces a number, not an answer.")
    return "\n".join(out)
