#!/usr/bin/env python3
"""Check that the English and Japanese papers match derived study results.

The check follows the reporting chain:

1. Recompute descriptive outcomes from ``run_level_summary.csv``.
2. Compare those values with ``reviewer_response_analysis.json``.
3. Compare both papers' descriptive, contrast, resource, absolute-performance,
   and lineage tables with machine-readable results and frozen analyses.
4. Check high-salience audit and cost values reported in prose.

This script is read-only. It exits nonzero on any mismatch.
"""

from __future__ import annotations

import csv
import json
import os as _os
import math
import re
import statistics
import sys
from pathlib import Path


# TOOLS is where these programs live (workspace/tools). The manuscripts and the
# derived CSV/JSON they cite live under report_temp/, NOT next to the code, so
# neither can be reached by walking up from __file__ any more.
TOOLS = Path(__file__).resolve().parent
REPORT = TOOLS.parents[1] / "report_temp"
# The replacement-analysis directory is named by the run that produced it,
# which embeds machine detail this repository must not carry. Take it from
# the environment; the default is the name with that detail removed.
_REPLACEMENT_DIR = _os.environ.get(
    "ARI_REPLACEMENT_ANALYSIS_DIR",
    "20260731_003500_handoff_ratelimit_replaced_analysis")

ROOT = TOOLS.parents[1]
DERIVED_DIR = Path(_os.environ.get("ARI_TOOL_OUT", REPORT / "tools"))
DERIVED = DERIVED_DIR / "reviewer_response_analysis.json"
RUNS = DERIVED_DIR / "run_level_summary.csv"
CROSS_TASK = (
    ROOT
    / "workspace/checkpoints"
    / _REPLACEMENT_DIR
    / "cross_task_analysis.json"
)
ANALYSIS_ROOT = CROSS_TASK.parent
TASK_ANALYSES = {
    task: ANALYSIS_ROOT / task / "analysis.json"
    for task in ("gemm", "spmm", "stencil")
}
PAPERS = {
    "en": REPORT / "paper_en.tex",
    "ja": REPORT / "paper_ja.tex",
}
TASKS = ("gemm", "spmm", "stencil")
ARMS = ("code_only", "evidence_only", "evidence_plus_reflection")
ARM_SHORT = {
    "code_only": "W",
    "evidence_only": "E",
    "evidence_plus_reflection": "S",
}
CONTRASTS = {
    "E-C": ("evidence_only_minus_code_only", "E--W"),
    "R-E": ("evidence_plus_reflection_minus_evidence_only", "S--E"),
}
FLOAT_TOKEN = re.compile(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)")


class CheckFailure(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def close(actual: float, expected: float, label: str, tol: float = 1e-9) -> None:
    if not math.isclose(actual, expected, rel_tol=tol, abs_tol=tol):
        raise CheckFailure(f"{label}: {actual!r} != {expected!r}")


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(value) for value in values) / len(values))


class TableAbsent(Exception):
    """The manuscript does not contain this table (yet)."""


def strip_comments(tex: str) -> str:
    r"""Drop LaTeX comments before any parsing.

    The v1 results section is retained in the manuscript as commented-out text
    (each line prefixed ``% [v1-DISCARDED]``) because the conditions do not match
    this paper's design. Without this, the parsers read those tables as if they
    were live -- and the number extractor even picked the ``1`` out of ``v1`` as a
    column, which is how a discarded table came to be verified against current
    data. Escaped ``\%`` is not a comment."""
    out = []
    for line in tex.splitlines():
        cut, i = None, 0
        while i < len(line):
            if line[i] == "%" and (i == 0 or line[i - 1] != "\\"):
                cut = i
                break
            i += 1
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def table_block(tex: str, label: str) -> str:
    marker = rf"\label{{{label}}}"
    position = tex.find(marker)
    if position < 0:
        raise TableAbsent(label)
    start = tex.rfind(r"\begin{table", 0, position)
    end = tex.find(r"\end{table", position)
    require(start >= 0 and end >= 0, f"cannot delimit table {label}")
    return tex[start : end + len(r"\end{table}")]


def strip_tex(value: str) -> str:
    previous = None
    while previous != value:
        previous = value
        value = re.sub(
            r"\\(?:texttt|textbf|mathbf|emph|armW|armE|armS)\s*\{([^{}]*)\}",
            r"\1",
            value,
        )
    value = value.replace(r"\armW", "W")
    value = value.replace(r"\armE", "E")
    value = value.replace(r"\armS", "S")
    value = value.replace("$", "")
    value = value.replace(r"\ ", "")
    return re.sub(r"\s+", "", value)


def data_rows(block: str, minimum_float_tokens: int) -> list[tuple[str, list[str]]]:
    if r"\midrule" in block:
        block = block.split(r"\midrule", 1)[1]
    if r"\bottomrule" in block:
        block = block.split(r"\bottomrule", 1)[0]
    rows: list[tuple[str, list[str]]] = []
    for raw in block.split(r"\\"):
        clean = strip_tex(raw)
        # TeX's ``--`` range separator is not a numeric minus sign.
        numbers = FLOAT_TOKEN.findall(clean.replace("--", "|"))
        if len(numbers) >= minimum_float_tokens:
            rows.append((clean, numbers))
    return rows


def fmt_p(value: float) -> str:
    digits = 5 if value < 0.01 else 3
    return f"{value:.{digits}f}".lstrip("0")


def fmt_ratio_bound(value: float) -> str:
    rounded = f"{value:.3f}"
    if rounded == "1.000" and value < 1.0:
        return f"{value:.4f}"
    return rounded


def load_runs() -> list[dict[str, str]]:
    with RUNS.open(newline="") as handle:
        return list(csv.DictReader(handle))


def numeric_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "mean": statistics.mean(values),
        "sd": statistics.stdev(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "geomean": geomean(values) if all(value > 0 for value in values) else None,
    }


def verify_run_summary(
    runs: list[dict[str, str]], derived: dict[str, object]
) -> int:
    require(len(runs) == int(derived["dataset"]["runs"]), "run count mismatch")
    require(len(runs) == 270, f"expected 270 runs, found {len(runs)}")
    require(all(row["valid"] == "True" for row in runs), "not all final runs valid")
    require(
        all(
            int(row["prompt_tokens"]) + int(row["completion_tokens"])
            == int(row["total_tokens"])
            for row in runs
        ),
        "prompt plus completion tokens do not equal total tokens",
    )

    checked = 4
    for task in TASKS:
        for arm in ARMS:
            group = [
                row for row in runs if row["task"] == task and row["arm"] == arm
            ]
            require(len(group) == 30, f"{task}/{arm}: expected 30 runs")
            require(
                {int(row["seed"]) for row in group} == set(range(30)),
                f"{task}/{arm}: seed set is not 0..29",
            )
            values = [float(row["score"]) for row in group]
            expected = derived["outcomes"][task][arm]
            for key, actual in numeric_summary(values).items():
                close(actual, float(expected[key]), f"{task}/{arm}/{key}")
                checked += 1

            for column in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "llm_calls",
                "fallback_summary_calls",
                "failed_llm_calls",
                "elapsed_seconds",
            ):
                values = [float(row[column]) for row in group]
                expected = derived["costs"][task][arm][column]
                for key, actual in numeric_summary(values).items():
                    expected_value = expected[key]
                    if actual is None or expected_value is None:
                        require(
                            actual is None and expected_value is None,
                            f"{task}/{arm}/{column}/{key}: null mismatch",
                        )
                    else:
                        close(
                            actual,
                            float(expected_value),
                            f"{task}/{arm}/{column}/{key}",
                        )
                    checked += 1

            absolute_columns = [
                ("absolute_candidate_ms_geomean_cases", "candidate_ms")
            ]
            if task != "spmm":
                absolute_columns.append(("absolute_rate_geomean_cases", "rate"))
            for column, key_name in absolute_columns:
                values = [float(row[column]) for row in group]
                expected = derived["absolute_performance"][task][arm][key_name]
                for key, actual in numeric_summary(values).items():
                    close(
                        actual,
                        float(expected[key]),
                        f"{task}/{arm}/{key_name}/{key}",
                    )
                    checked += 1
    return checked


def verify_descriptive_table(
    tex: str, label: str, derived: dict[str, object], language: str
) -> int:
    rows = data_rows(table_block(tex, label), 6)
    require(len(rows) == 9, f"{language}: {label} has {len(rows)} data rows")
    checked = 0
    for (row, numbers), (task, arm) in zip(
        rows, ((task, arm) for task in TASKS for arm in ARMS), strict=True
    ):
        stats = derived["outcomes"][task][arm]
        expected = [
            f"{stats['mean']:.2f}",
            f"{stats['median']:.2f}",
            f"{stats['sd']:.2f}",
            f"{stats['min']:.2f}",
            f"{stats['max']:.2f}",
            f"{stats['geomean']:.2f}",
        ]
        require(
            numbers == expected,
            f"{language}: descriptive row {task}/{arm} mismatch: "
            f"{numbers} != {expected}",
        )
        require(
            ARM_SHORT[arm] in row or arm == "evidence_only" and "Evidence" in row,
            f"{language}: policy label missing in {task}/{arm} row",
        )
        checked += len(expected)
    return checked


def verify_contrast_table(
    tex: str,
    label: str,
    derived: dict[str, object],
    cross_task: dict[str, object],
    language: str,
) -> int:
    block = table_block(tex, label)
    rows = data_rows(block, 7)
    require(len(rows) == 6, f"{language}: {label} has {len(rows)} contrast rows")
    holm = {
        (entry["task"], entry["contrast"]): float(
            entry["holm_p_across_tasks_and_primary_contrasts"]
        )
        for entry in cross_task["tests"]
    }
    expected_order = [
        (task, old_label) for task in TASKS for old_label in ("E-C", "R-E")
    ]
    checked = 0
    for (row, numbers), (task, old_label) in zip(
        rows, expected_order, strict=True
    ):
        source_label, paper_label = CONTRASTS[old_label]
        randomization = derived["aligned_randomization_ci"][task][old_label]
        log_result = derived["paired_log_analysis"][task][old_label]
        ci_low, ci_high = randomization["randomization_95_ci"]
        ratio_low, ratio_high = log_result["bootstrap_95_ci_ratio"]
        expected = [
            f"{float(randomization['mean_difference']):+.2f}",
            f"{float(ci_low):.2f}",
            f"{float(ci_high):.2f}",
            fmt_p(holm[(task, source_label)]),
            f"{float(log_result['geometric_mean_ratio']):.3f}",
            fmt_ratio_bound(float(ratio_low)),
            fmt_ratio_bound(float(ratio_high)),
        ]
        require(
            numbers == expected,
            f"{language}: contrast {task}/{paper_label} mismatch: "
            f"{numbers} != {expected}",
        )
        require(
            paper_label in row,
            f"{language}: expected contrast label {paper_label} in row",
        )
        checked += len(expected)
    return checked


def verify_absolute_table(
    tex: str, label: str, derived: dict[str, object], language: str
) -> int:
    block = strip_tex(table_block(tex, label))
    checked = 0
    for task in TASKS:
        for arm in ARMS:
            values = derived["absolute_performance"][task][arm]
            expected = [f"{values['candidate_ms']['median']:.3f}"]
            if "rate" in values:
                expected.append(f"{values['rate']['median']:.2f}")
            for token in expected:
                require(
                    token in block,
                    f"{language}: absolute value {task}/{arm}={token} missing",
                )
                checked += 1
    return checked


def verify_resource_table(
    tex: str, label: str, derived: dict[str, object], language: str
) -> int:
    rows = data_rows(table_block(tex, label), 5)
    require(len(rows) == 9, f"{language}: {label} has {len(rows)} resource rows")
    checked = 0
    for (row, numbers), (task, arm) in zip(
        rows, ((task, arm) for task in TASKS for arm in ARMS), strict=True
    ):
        costs = derived["costs"][task][arm]
        expected = [
            f"{float(costs['prompt_tokens']['median']) / 1e6:.3f}",
            f"{float(costs['completion_tokens']['median']) / 1e3:.0f}",
            f"{float(costs['llm_calls']['median']):.0f}",
            f"{float(costs['fallback_summary_calls']['mean']):.2f}",
            f"{float(costs['elapsed_seconds']['median']) / 60:.1f}",
        ]
        require(
            numbers == expected,
            f"{language}: resource row {task}/{arm} mismatch: "
            f"{numbers} != {expected}",
        )
        require(
            ARM_SHORT[arm] in row,
            f"{language}: policy label missing in {task}/{arm} resource row",
        )
        checked += len(expected)
    return checked


def verify_lineage_table(
    tex: str,
    label: str,
    task_analyses: dict[str, object],
    language: str,
) -> int:
    rows = data_rows(table_block(tex, label), 9)
    require(len(rows) == 3, f"{language}: {label} has {len(rows)} lineage rows")
    checked = 0
    for (row, numbers), task in zip(rows, TASKS, strict=True):
        expected = []
        for arm in ARMS:
            arm_result = task_analyses[task]["arms"][arm]
            expected.extend(
                [
                    f"{100 * float(arm_result['node_success_rate']):.1f}",
                    f"{100 * float(arm_result['child_improve_rate']):.1f}",
                    f"{100 * float(arm_result['child_break_rate']):.1f}",
                ]
            )
        require(
            numbers == expected,
            f"{language}: lineage row {task} mismatch: {numbers} != {expected}",
        )
        checked += len(expected)
    return checked


def verify_v2_measurement_facts(tex: str, language: str) -> int:
    """Check the numbers THIS study measured, not just the ones inherited from v1.

    The v1 pipeline produced reviewer_response_analysis.json and every value the
    manuscript quoted from it was checked against that file. The v2 measurement
    work -- the resolution band, the stencil page-cache mechanism -- produced
    numbers that were only ever checked by eye, and eye-checking missed two of
    them: the band RATIOS had been recomputed from the rounded values printed in
    the table (spmm 1.01 instead of 1.005, stencil 1.39 instead of 1.40), so the
    manuscript said a task was 1% over target when it was 0.5%, and rounding
    displayed it as exactly on target. Derived values need checking too, not just
    the values they derive from.
    """
    facts_path = DERIVED_DIR / "v2_measurement_facts.json"
    if not facts_path.is_file():
        raise TableAbsent("v2-measurement-facts")
    facts = json.loads(facts_path.read_text())
    compact = re.sub(r"\s+", " ", tex)
    checked = 0

    # A manuscript that carries NONE of the v2 band values is a pre-v2 manuscript,
    # not a manuscript with wrong numbers. Report it as absent so a stale
    # translation does not read as a numerical disagreement -- paper_en.tex is
    # exactly that today, and conflating the two would hide real mismatches
    # behind a failure everyone has learned to ignore.
    bands = [f"{f['band_p95_pct']:.3f}".rstrip("0").rstrip(".")
             for f in (facts.get("band") or {}).values()]
    if bands and not any(b in compact for b in bands):
        raise TableAbsent("v2-measurement-facts")

    for task, f in (facts.get("band") or {}).items():
        band = f"{f['band_p95_pct']:.3f}".rstrip("0").rstrip(".")
        require(band in compact,
                f"{language}: band {band}% for {task} not in the manuscript")
        ratio = f["band_p95_pct"] / f["target_pct"]
        # the ratio must follow from the UNROUNDED band and target
        shown = f"{ratio:.3f}".rstrip("0").rstrip(".")
        alt = f"{ratio:.2f}"
        require(shown in compact or alt in compact,
                f"{language}: band/target ratio for {task} is {ratio:.4f}; "
                f"neither {shown} nor {alt} appears (a ratio recomputed from the "
                f"rounded table values would differ)")
        checked += 2

    cold = facts.get("stencil_cold") or {}
    warm = facts.get("stencil_warm") or {}
    for label, d in (("cold", cold), ("warm", warm)):
        if d.get("max_ms"):
            require(f"{d['max_ms']:.1f}" in compact,
                    f"{language}: stencil {label} max {d['max_ms']:.1f} ms missing")
            checked += 1
    for name, spread in (warm.get("shapes") or {}).items():
        require(f"{spread:.2f}" in compact,
                f"{language}: warm spread {spread:.2f}% for {name} missing")
        checked += 1
    return checked


def verify_audit_claims(
    tex: str, derived: dict[str, object], language: str
) -> int:
    compact = re.sub(r"\s+", " ", tex)
    normalized = compact.replace("{,}", ",")
    handoff = derived["handoff"]
    reflection = derived["reflection"]
    leakage = derived["code_only_leakage"]
    expected_fragments = [
        str(derived["dataset"]["runs"]),
        str(handoff["evidence_only"]["messages"]),
        str(int(handoff["evidence_plus_reflection"]["reflection_tokens"]["median"])),
        str(reflection["architecture_incompatible_handoffs"]),
        str(leakage["edges_with_agent_added_comments"]),
        str(leakage["edges_with_optimization_comments"]),
        str(leakage["edges_with_evaluation_comments"]),
        str(leakage["runs_with_evaluation_comments"]),
        str(leakage["edges_with_extra_text_files"]),
        str(leakage["runs_with_extra_text_files"]),
        "594",
        "49,298",
    ]
    for fragment in expected_fragments:
        require(fragment in compact, f"{language}: audit value {fragment} missing")
    require(
        "43" in compact and "15" in compact and "18 run" in compact,
        f"{language}: task/run ISA breakdown missing",
    )
    for task in TASKS:
        costs = derived["costs"][task]
        difference = (
            float(costs["evidence_plus_reflection"]["total_tokens"]["mean"])
            - float(costs["evidence_only"]["total_tokens"]["mean"])
        )
        rendered = f"{difference:+,.0f}"
        require(
            rendered in normalized,
            f"{language}: S-E mean token difference {task}={rendered} missing",
        )
    return len(expected_fragments) + 6


def main() -> int:
    required = [
        DERIVED,
        RUNS,
        CROSS_TASK,
        *TASK_ANALYSES.values(),
        DERIVED_DIR / "handoff_message_audit.csv",
        DERIVED_DIR / "reflection_quality_audit.csv",
        DERIVED_DIR / "code_only_leakage_audit.csv",
        DERIVED_DIR / "selected_optimization_classification.csv",
        DERIVED_DIR / "paired_difference_dotplot.pdf",
    ]
    for path in required:
        require(path.is_file(), f"required file missing: {path}")

    derived = json.loads(DERIVED.read_text())
    cross_task = json.loads(CROSS_TASK.read_text())
    task_analyses = {
        task: json.loads(path.read_text()) for task, path in TASK_ANALYSES.items()
    }
    runs = load_runs()
    checks = verify_run_summary(runs, derived)
    skipped: list[str] = []

    for language, path in PAPERS.items():
        require(path.is_file(), f"paper missing: {path}")
        tex = strip_comments(path.read_text())
        descriptive_label = (
            "tab:descriptive" if language == "en" else "tab:final-outcome"
        )
        contrast_label = (
            "tab:contrasts" if language == "en" else "tab:primary-results"
        )
        absolute_label = (
            "tab:absolute" if language == "en" else "tab:absolute-performance"
        )
        resource_label = "tab:cost" if language == "en" else "tab:resource-audit"
        # A table the manuscript does not carry is not a disagreement: the v1
        # results are commented out pending the v2 campaign. Skip it and SAY SO,
        # so a run that checks almost nothing cannot be mistaken for a clean one.
        def _check(fn, *fn_args):
            nonlocal skipped
            try:
                return fn(*fn_args)
            except TableAbsent as exc:
                skipped.append(f"{language}:{exc.args[0]}")
                return 0

        before = len(skipped)
        checks += _check(
            verify_descriptive_table, tex, descriptive_label, derived, language
        )
        v1_absent = len(skipped) > before
        checks += _check(
            verify_contrast_table, tex, contrast_label, derived, cross_task, language
        )
        checks += _check(verify_v2_measurement_facts, tex, language)
        checks += _check(verify_absolute_table, tex, absolute_label, derived, language)
        checks += _check(verify_resource_table, tex, resource_label, derived, language)
        if language == "ja":
            checks += _check(
                verify_lineage_table, tex, "tab:lineage-results", task_analyses, language
            )
        # The audit narrative and the paired-difference figure sit in the same
        # v1 results section as the descriptive table, so they stand or fall with
        # it rather than being separately absent.
        if v1_absent:
            skipped.append(f"{language}:v1-audit-narrative")
            skipped.append(f"{language}:paired-difference-figure")
        else:
            checks += verify_audit_claims(tex, derived, language)
            require(
                r"{tools/paired_difference_dotplot.pdf}" in tex,
                f"{language}: paired-difference figure does not use tools/ path",
            )

    if skipped:
        print(f"SKIPPED {len(skipped)} table(s) absent from the manuscript: "
              + ", ".join(skipped))
    print(
        "PASS: 270-run source, derived JSON, and both papers agree "
        f"across {checks} reported-value checks."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CheckFailure as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
