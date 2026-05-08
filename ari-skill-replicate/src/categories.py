"""PaperBench category allow-lists + deterministic normalizer.

Mirrors ``vendor/paperbench/.../rubric/tasks.py`` (``VALID_TASK_CATEGORIES`` /
``VALID_FINEGRAINED_TASK_CATEGORIES``). PaperBench's ``TaskNode.__post_init__``
raises ``ValueError("Invalid finegrained task category: ...")`` for any value
outside its closed vocabulary, which crashes ``grade_with_simplejudge`` at the
first non-conforming leaf. This module gives the generator a normalizer that
maps observed LLM variants to allow-list entries before the rubric is frozen.
"""

from __future__ import annotations

VALID_TASK_CATEGORIES: tuple[str, ...] = (
    "Code Development",
    "Code Execution",
    "Result Analysis",
)

VALID_FINEGRAINED_TASK_CATEGORIES: tuple[str, ...] = (
    "Environment & Infrastructure Setup",
    "Dataset and Model Acquisition",
    "Data Processing & Preparation",
    "Method Implementation",
    "Experimental Setup",
    "Evaluation, Metrics & Benchmarking",
    "Logging, Analysis & Presentation",
)

# Synonyms observed (or reasonably anticipated) from LLM rubric generators.
# Keys are lower-case, stripped. Values must be members of
# ``VALID_FINEGRAINED_TASK_CATEGORIES``.
_FINEGRAINED_SYNONYMS: dict[str, str] = {
    # "visualization-of-results" family → Logging, Analysis & Presentation
    "result visualization": "Logging, Analysis & Presentation",
    "results visualization": "Logging, Analysis & Presentation",
    "result analysis": "Logging, Analysis & Presentation",
    "results analysis": "Logging, Analysis & Presentation",
    "visualization": "Logging, Analysis & Presentation",
    "plotting": "Logging, Analysis & Presentation",
    "plots": "Logging, Analysis & Presentation",
    "figures": "Logging, Analysis & Presentation",
    "logging": "Logging, Analysis & Presentation",
    "presentation": "Logging, Analysis & Presentation",
    "reporting": "Logging, Analysis & Presentation",
    # implementation-of-result-analysis → Method Implementation
    "result analysis implementation": "Method Implementation",
    "results analysis implementation": "Method Implementation",
    "analysis implementation": "Method Implementation",
    "method implementation": "Method Implementation",
    "implementation": "Method Implementation",
    "method": "Method Implementation",
    "model implementation": "Method Implementation",
    "algorithm implementation": "Method Implementation",
    # evaluation / benchmarking
    "evaluation": "Evaluation, Metrics & Benchmarking",
    "metrics": "Evaluation, Metrics & Benchmarking",
    "benchmarking": "Evaluation, Metrics & Benchmarking",
    "benchmark": "Evaluation, Metrics & Benchmarking",
    "evaluation metrics": "Evaluation, Metrics & Benchmarking",
    # experimental setup
    "experiment setup": "Experimental Setup",
    "experiments setup": "Experimental Setup",
    "experiment": "Experimental Setup",
    "experiments": "Experimental Setup",
    "training setup": "Experimental Setup",
    "hyperparameters": "Experimental Setup",
    "hyperparameter setup": "Experimental Setup",
    # data processing
    "data processing": "Data Processing & Preparation",
    "data preparation": "Data Processing & Preparation",
    "data preprocessing": "Data Processing & Preparation",
    "preprocessing": "Data Processing & Preparation",
    "data pipeline": "Data Processing & Preparation",
    "data": "Data Processing & Preparation",
    # dataset / model acquisition
    "dataset acquisition": "Dataset and Model Acquisition",
    "model acquisition": "Dataset and Model Acquisition",
    "dataset": "Dataset and Model Acquisition",
    "datasets": "Dataset and Model Acquisition",
    "model loading": "Dataset and Model Acquisition",
    "data loading": "Dataset and Model Acquisition",
    # environment / infra
    "environment setup": "Environment & Infrastructure Setup",
    "infrastructure setup": "Environment & Infrastructure Setup",
    "environment": "Environment & Infrastructure Setup",
    "infrastructure": "Environment & Infrastructure Setup",
    "dependencies": "Environment & Infrastructure Setup",
    "installation": "Environment & Infrastructure Setup",
    "setup": "Environment & Infrastructure Setup",
}

# Category-conditioned default (top PaperBench co-occurrence).
_DEFAULT_FINEGRAINED_BY_TC: dict[str, str] = {
    "Code Development": "Method Implementation",
    "Code Execution": "Experimental Setup",
    "Result Analysis": "Evaluation, Metrics & Benchmarking",
}

_DEFAULT_FINEGRAINED = "Method Implementation"


def _norm_key(s: str) -> str:
    return " ".join(s.lower().split())


def normalize_task_category(value: str | None) -> tuple[str | None, str | None]:
    """Return ``(clean, reason)``. ``reason`` is ``None`` if unchanged."""
    if value is None:
        return None, None
    if value in VALID_TASK_CATEGORIES:
        return value, None
    for ok in VALID_TASK_CATEGORIES:
        if value.lower() == ok.lower():
            return ok, f"task_category {value!r} -> {ok!r} (case-fix)"
    return (
        "Code Development",
        f"task_category {value!r} not in allow-list -> 'Code Development'",
    )


def normalize_finegrained(
    value: str | None, task_category: str | None
) -> tuple[str | None, str | None]:
    """Return ``(clean, reason)``. ``reason`` is ``None`` if unchanged."""
    if value is None:
        return None, None
    if value in VALID_FINEGRAINED_TASK_CATEGORIES:
        return value, None
    for ok in VALID_FINEGRAINED_TASK_CATEGORIES:
        if value.lower() == ok.lower():
            return ok, f"finegrained_task_category {value!r} -> {ok!r} (case-fix)"
    key = _norm_key(value)
    if key in _FINEGRAINED_SYNONYMS:
        target = _FINEGRAINED_SYNONYMS[key]
        return target, f"finegrained_task_category {value!r} -> {target!r} (synonym)"
    # Fuzzy: longest synonym key contained in normalized value wins.
    candidates = sorted(
        ((k, t) for k, t in _FINEGRAINED_SYNONYMS.items() if k in key),
        key=lambda kt: -len(kt[0]),
    )
    if candidates:
        k, target = candidates[0]
        return (
            target,
            f"finegrained_task_category {value!r} ~ {k!r} -> {target!r} (fuzzy)",
        )
    default = _DEFAULT_FINEGRAINED_BY_TC.get(task_category or "", _DEFAULT_FINEGRAINED)
    return (
        default,
        f"finegrained_task_category {value!r} unrecognized -> {default!r} "
        f"(default for task_category={task_category!r})",
    )


def normalize_rubric_node(node: dict) -> list[str]:
    """Recursively normalize categories in a rubric tree. Mutates in place.

    Returns a list of human-readable change descriptions (empty if no changes).
    """
    warnings: list[str] = []

    def _walk(n: dict) -> None:
        if not isinstance(n, dict):
            return
        tc_in = n.get("task_category")
        tc_out, why_tc = normalize_task_category(tc_in)
        if why_tc:
            warnings.append(why_tc)
        if tc_in is not None:
            n["task_category"] = tc_out
        fg_in = n.get("finegrained_task_category")
        fg_out, why_fg = normalize_finegrained(fg_in, tc_out if tc_in is not None else tc_in)
        if why_fg:
            warnings.append(why_fg)
        if fg_in is not None:
            n["finegrained_task_category"] = fg_out
        for child in n.get("sub_tasks") or []:
            _walk(child)

    _walk(node)
    return warnings
