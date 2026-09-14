"""``resources.cpu_cores`` is what a run is BILLED for, and nothing bound it.

WHAT THE FIELD ACTUALLY DOES. It reaches two places and neither is a limit:
``assurance_bridge`` hands it to the cost tracker, which records
``cpu_core_seconds = duration * cpu_cores``. The executor bounds memory through
prlimit and processes through the runtime's own flag; nothing bounds CPU. Both
publication points are honest about this -- the registration bundle's semantics
say "declared cores multiplied by measured wall seconds" and the runtime record
carries ``resource_measurement_basis="declared-allocation-x-executor-wall-time"``.

SO THE DEFECT IS NOT A MISLABELLED NUMBER. It is that the declaration and the
width a run actually uses were free to disagree, and did. While
``hpc/gemm-performance`` pinned ``thread_budget: 8`` beside ``cpu_cores: 2``,
every governed run of it recorded a quarter of the machine time it consumed.
They agree now because the placement moved to 2 for an unrelated reason -- the
only budget its clean control resolves at -- which is agreement by coincidence.

AND ENFORCING IT WOULD BE WORSE. Pinning CPU affinity from ``cpu_cores`` would
put a second mechanism next to the placement, which is the thing that decides
how wide a timed run is; the two would fight and the harness would measure
whichever won. The declaration should not be enforced. It should be unable to
disagree, which is what this holds.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

BUILTIN = (Path(__file__).resolve().parents[1] / "config" / "harnesses" / "builtin")


def _manifests():
    rows = []
    for path in sorted(BUILTIN.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        rows.append((document["id"], document))
    return rows


MANIFESTS = _manifests()


def test_there_are_manifests_to_check() -> None:
    assert MANIFESTS, "no shipped manifest; this file is inert"


@pytest.mark.parametrize("harness,document", MANIFESTS,
                         ids=[row[0] for row in MANIFESTS])
def test_a_pinned_placement_and_the_billed_allocation_agree(harness, document) -> None:
    """Where a manifest pins the width its runs are given, that is the width its
    runs are billed for.

    Skipped, not passed, for a manifest that pins no placement: those run at
    whatever the ambient regime gives and there is nothing here to compare
    against. Saying so is the finding -- their cost figure is a declaration with
    no counterpart at all.
    """
    placement = document.get("registered_placement") or {}
    budget = placement.get("thread_budget")
    if budget is None:
        pytest.skip(f"{harness} pins no placement, so nothing states the width "
                    f"its runs actually use")
    declared = document["resources"]["cpu_cores"]
    assert str(declared) == str(budget), (
        f"{harness} is billed for {declared} core(s) and pins a thread budget of "
        f"{budget}: every run records cpu_core_seconds off by a factor of "
        f"{float(budget) / max(float(declared), 1e-9):.2g}. The declaration is "
        f"not enforced anywhere -- the budget is what runs -- so the two must "
        f"not be free to disagree")


def test_the_cost_record_says_which_kind_of_number_it_is() -> None:
    """The figure is a declaration, and both places that publish it say so.

    Holding the LABEL matters as much as holding the value: an unlabelled
    "cpu_core_seconds" reads as a measurement, and a reader who takes a declared
    allocation for a measured one has been told something false by a number that
    is individually correct.
    """
    import inspect

    from ari import cost_tracker

    source = inspect.getsource(cost_tracker)
    assert 'resource_measurement_basis="declared-allocation-x-executor-wall-time"' \
        in source, (
        "the runtime cost record no longer says its cpu figure is a declared "
        "allocation rather than a measurement")
