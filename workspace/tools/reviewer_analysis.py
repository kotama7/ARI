#!/usr/bin/env python3
"""Post-hoc audits requested during review.

This script reads the frozen confirmatory dataset and writes only derived
tables and figures in ``report_temp/tools``. It does not alter experiment data.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os as _os
import re
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tiktoken


# The replacement-analysis directory is named by the run that produced it,
# which embeds machine detail this repository must not carry. Take it from
# the environment; the default is the name with that detail removed.
_REPLACEMENT_DIR = _os.environ.get(
    "ARI_REPLACEMENT_ANALYSIS_DIR",
    "20260731_003500_handoff_ratelimit_replaced_analysis")


def _anonymise_host(name: str) -> str:
    """Stable pseudonym for a compute node.

    Node identity MATTERS to this analysis — the same code measured 1.13x on one
    node and 2.26x on another, so an effect could be a node effect and the data
    must be able to show that. But a real hostname is machine identity and does
    not belong in a tracked repository or in a published artefact. A salted hash
    keeps every property the analysis needs (same node -> same label, different
    nodes -> different labels) and carries none of the identity.

    The salt defaults to a constant so labels are reproducible across runs of
    this script; set ARI_HOST_SALT to make them non-linkable across releases.
    """
    import hashlib as _h
    import os as _o
    salt = _o.environ.get("ARI_HOST_SALT", "ari-node")
    digest = _h.sha256(f"{salt}:{name}".encode()).hexdigest()
    return f"node_{digest[:8]}"


ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = (
    ROOT
    / "workspace/checkpoints"
    / _REPLACEMENT_DIR
)
# The programs live in workspace/tools/; their derived outputs live beside the
# manuscript that cites them. Before the move these coincided and OUT was just
# the script's own directory, which now points at the code directory instead.
OUT = Path(_os.environ.get("ARI_TOOL_OUT", ROOT / "report_temp/tools"))
OUT.mkdir(parents=True, exist_ok=True)
TASKS = ["gemm", "spmm", "stencil"]
TASK_LABEL = {"gemm": "GEMM", "spmm": "SpMM", "stencil": "Stencil"}
ARMS = ["code_only", "evidence_only", "evidence_plus_reflection"]
ARM_LABEL = {
    "code_only": "Workspace only",
    "evidence_only": "Evidence only",
    "evidence_plus_reflection": "Evidence+Self-Report",
}
CANDIDATE = {
    "gemm": "candidate_gemm.c",
    "spmm": "candidate_spmm.c",
    "stencil": "candidate_stencil.c",
}

ENCODING = tiktoken.get_encoding("o200k_harmony")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+.-]*")
STOPWORDS = set(
    """
    the a an and or but if then else to of in on for with by from as at is are
    was were be been being this that these those it its they their we our you
    your can could should would may might will into over under than also only
    all any each per not no do does did done has have had using use used based
    via about after before during when while where which who what how more less
    further next new same such both some out up down parent node candidate
    implementation code file files run test tests result results step steps
    """.split()
)


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    pieces = []
    for item in content:
        if isinstance(item, str):
            pieces.append(item)
        elif isinstance(item, dict):
            value = item.get("text") or item.get("content")
            if isinstance(value, str):
                pieces.append(value)
    return "\n".join(pieces)


def content_words(value: str) -> list[str]:
    words = []
    for raw in WORD_RE.findall(value):
        word = raw.lower().strip(".-")
        if len(word) >= 3 and word not in STOPWORDS:
            words.append(word)
    return words


def geometric_mean(values: object) -> float:
    array = np.asarray(values, dtype=float)
    return float(np.exp(np.mean(np.log(array))))


def quantile_stats(values: object) -> dict[str, float | int | None]:
    array = np.asarray(values, dtype=float)
    return {
        "n": int(len(array)),
        "mean": float(np.mean(array)),
        "sd": float(np.std(array, ddof=1)),
        "median": float(np.median(array)),
        "q1": float(np.quantile(array, 0.25)),
        "q3": float(np.quantile(array, 0.75)),
        "min": float(np.min(array)),
        "max": float(np.max(array)),
        "geomean": geometric_mean(array) if np.all(array > 0) else None,
    }


def normalize_comment(value: str) -> str:
    value = re.sub(r"^\s*(?://+|/\*+|\*+)", "", value)
    value = re.sub(r"(?:\*/)?\s*$", "", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def extract_comments(source: str) -> list[str]:
    raw = re.findall(r"/\*.*?\*/|//[^\n]*", source, flags=re.S)
    return [comment for item in raw if (comment := normalize_comment(item))]


def remove_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)


def parse_stencil_case(case: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)x(\d+)t(\d+)", case)
    if not match:
        raise ValueError(f"Unexpected stencil case: {case}")
    return tuple(map(int, match.groups()))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifests() -> list[dict]:
    manifests = []
    for task in TASKS:
        path = ANALYSIS / task / "manifest.jsonl"
        manifests.extend(json.loads(line) for line in path.read_text().splitlines() if line)
    counts = collections.Counter((item["task"], item["arm"]) for item in manifests)
    expected = collections.Counter({(task, arm): 30 for task in TASKS for arm in ARMS})
    assert len(manifests) == 270 and counts == expected
    return manifests


def main() -> None:
    baseline_comments = {}
    for task in TASKS:
        path = (
            ROOT
            / f"workspace/harnesses/{task}/{task}_kernels/{CANDIDATE[task]}"
        )
        baseline_comments[task] = collections.Counter(
            extract_comments(path.read_text(errors="replace"))
        )

    rows = []
    handoff_rows = []
    reflection_rows = []
    comment_rows = []
    selected_rows = []
    mismatch_examples = []
    invalid_positive_examples = []

    for manifest in load_manifests():
        task = manifest["task"]
        arm = manifest["arm"]
        seed = int(manifest["seed"])
        recorded_run_dir = Path(manifest["run_dir"])
        run_dir = ROOT / "workspace/experiments" / recorded_run_dir.name
        if not run_dir.is_dir():
            run_dir = recorded_run_dir
        checkpoint = ROOT / "workspace/checkpoints" / run_dir.name
        final = json.loads((run_dir / "final_measurement.json").read_text())

        reports = {}
        starts = []
        for node_dir in sorted(run_dir.glob("node_*")):
            report_path = node_dir / "node_report.json"
            if not report_path.exists():
                continue
            report = json.loads(report_path.read_text())
            reports[report["node_id"]] = (node_dir, report)
            if report.get("started_at"):
                starts.append(parse_datetime(report["started_at"]))
        assert len(reports) == 10, (run_dir, len(reports))

        cost_records = []
        cost_path = checkpoint / "cost_trace.jsonl"
        if cost_path.exists():
            cost_records = [
                json.loads(line) for line in cost_path.read_text().splitlines() if line
            ]
        fallback = [
            record
            for record in cost_records
            if record.get("phase") == "fallback_summary"
        ]

        case_times = []
        case_rates = []
        for case, audits in final["measurement_audit"]["cases"].items():
            accepted = [
                float(item["measurements"]["candidate_credited_seconds"])
                for item in audits
                if item.get("valid") and item.get("status") == "accepted"
            ]
            assert accepted
            median_time = float(np.median(accepted))
            case_times.append(median_time)
            if task == "gemm":
                n, p, m = map(int, case.split("x"))
                case_rates.append((2 * n * p * m) / median_time / 1e9)
            elif task == "stencil":
                nx, ny, nz, steps = parse_stencil_case(case)
                case_rates.append((nx * ny * nz * steps) / median_time / 1e9)

        rows.append(
            {
                "task": task,
                "arm": arm,
                "seed": seed,
                "score": float(final["scientific_score"]),
                "valid": bool(final["measurement_valid"]),
                "run_dir": str(run_dir),
                "checkpoint_dir": str(checkpoint),
                # anonymised: node identity is needed for the analysis, the name is not
                "hostname": _anonymise_host(
                    manifest["allocation"]["hostname"]),
                "slurm_job_id": manifest["allocation"]["slurm_job_id"],
                "slurm_array_task_id": manifest["allocation"]["slurm_array_task_id"],
                "started_at": min(starts).isoformat(),
                "completed_at": final["completed_at"],
                "elapsed_seconds": (
                    parse_datetime(final["completed_at"]) - min(starts)
                ).total_seconds(),
                "llm_calls": len(cost_records),
                "failed_llm_calls": sum(
                    record.get("status") != "ok" for record in cost_records
                ),
                "fallback_summary_calls": len(fallback),
                "fallback_summary_nodes": len(
                    {record.get("node_id") for record in fallback}
                ),
                "prompt_tokens": sum(
                    int(record.get("prompt_tokens") or 0) for record in cost_records
                ),
                "completion_tokens": sum(
                    int(record.get("completion_tokens") or 0)
                    for record in cost_records
                ),
                "total_tokens": sum(
                    int(record.get("total_tokens") or 0) for record in cost_records
                ),
                "absolute_candidate_ms_geomean_cases": geometric_mean(case_times)
                * 1000,
                "absolute_rate_geomean_cases": geometric_mean(case_rates)
                if case_rates
                else None,
                "selected_node_id": final["selected_node_id"],
            }
        )

        handoff_count = 0
        for node_id, (node_dir, report) in reports.items():
            if report.get("parent_id") is None:
                continue
            full_log = json.loads((node_dir / "full_log.json").read_text())
            handoffs = []
            for message in full_log.get("messages", []):
                text = content_text(message.get("content"))
                if "[Parent handoff]" in text:
                    handoffs.append(text)
            handoff_count += len(handoffs)

            if arm == "code_only":
                for handoff in handoffs:
                    handoff_rows.append(
                        {
                            "task": task,
                            "arm": arm,
                            "seed": seed,
                            "child_node": node_id,
                            "chars": len(handoff),
                            "tokens": len(ENCODING.encode(handoff)),
                        }
                    )
                continue

            assert len(handoffs) == 1, (run_dir, node_id, len(handoffs))
            handoff = handoffs[0]
            split = "\n  reflection_summary:"
            if split in handoff:
                evidence, remainder = handoff.split(split, 1)
                reflection = "reflection_summary:" + remainder
            else:
                evidence, reflection = handoff, ""
            handoff_rows.append(
                {
                    "task": task,
                    "arm": arm,
                    "seed": seed,
                    "child_node": node_id,
                    "chars": len(handoff),
                    "tokens": len(ENCODING.encode(handoff)),
                    "evidence_chars": len(evidence),
                    "evidence_tokens": len(ENCODING.encode(evidence)),
                    "reflection_chars": len(reflection),
                    "reflection_tokens": len(ENCODING.encode(reflection))
                    if reflection
                    else 0,
                }
            )
            if arm != "evidence_plus_reflection":
                continue

            parent_id = report["parent_id"]
            _, parent = reports[parent_id]
            summary = str(parent.get("what_was_done") or "")
            concerns = parent.get("self_assessment", {}).get("concerns") or []
            next_steps = parent.get("next_steps_hints") or []
            reflection_text = "\n".join(
                [summary, *map(str, concerns), *map(str, next_steps)]
            )
            evidence_words = set(content_words(evidence))
            reflection_words = set(content_words(reflection_text))
            lexical_reuse = (
                len(evidence_words & reflection_words) / len(reflection_words)
                if reflection_words
                else 0.0
            )
            novel_steps = 0
            for step in next_steps:
                step_words = set(content_words(str(step)))
                if step_words and len(step_words - evidence_words) / len(step_words) >= 0.5:
                    novel_steps += 1

            incompatible = []
            # The CPU is A64FX. Count only next-step recommendations that name
            # an incompatible x86/GPU ISA, not cautions that merely mention one.
            for index, value in enumerate(next_steps):
                if re.search(
                    r"\b(?:AVX(?:2|[- ]?512)?|CUDA|GPU|x86|"
                    r"Intel intrinsic|AMD intrinsic)\b",
                    str(value),
                    re.I,
                ):
                    incompatible.append(
                        {
                            "field": "next_steps",
                            "index": index,
                            "text": str(value),
                        }
                    )

            valid = bool(parent.get("measurement_valid"))
            unaware = []
            unaware_patterns = [
                r"(?:candidate|compilation status).{0,80}(?:still )?"
                r"(?:needs? to be|is|remains) "
                r"(?:built|compiled|evaluated|unclear)",
                r"(?:correctness|compilation).{0,80}"
                r"(?:not (?:confirmed|verified)|unclear)",
                r"no (?:final )?(?:evaluation|performance measurements?) "
                r"(?:was|were) (?:performed|produced|obtained)",
            ]
            flattened_fields = [
                ("summary", summary),
                ("concerns", "\n".join(map(str, concerns))),
                ("next_steps", "\n".join(map(str, next_steps))),
            ]
            for field, value in flattened_fields:
                if any(
                    re.search(pattern, value, re.I | re.S)
                    for pattern in unaware_patterns
                ):
                    unaware.append(field)

            positive = []
            if not valid:
                positive_pattern = (
                    r"\b(?:achieved|correct results?|correctness (?:was )?"
                    r"(?:maintained|verified)|successfully (?:ran|passed|executed)|"
                    r"speedup of|\d+(?:\.\d+)?\s*[x×] speedup)\b"
                )
                for field, value in flattened_fields:
                    if re.search(positive_pattern, value, re.I):
                        positive.append(field)

            reflection_rows.append(
                {
                    "task": task,
                    "arm": arm,
                    "seed": seed,
                    "child_node": node_id,
                    "parent_node": parent_id,
                    "measurement_valid": valid,
                    "summary_missing": not bool(summary.strip()),
                    "concerns_missing": len(concerns) == 0,
                    "next_steps_missing": len(next_steps) == 0,
                    "summary_chars": len(summary),
                    "concerns_count": len(concerns),
                    "concerns_chars": sum(len(str(item)) for item in concerns),
                    "next_steps_count": len(next_steps),
                    "next_steps_chars": sum(len(str(item)) for item in next_steps),
                    "reflection_tokens": len(ENCODING.encode(reflection_text)),
                    "lexical_reuse_fraction": lexical_reuse,
                    "novel_next_steps": novel_steps,
                    "architecture_incompatible_items": len(incompatible),
                    "evaluator_unaware_fields_when_valid": len(unaware)
                    if valid
                    else 0,
                    "positive_claim_fields_when_invalid": len(positive)
                    if not valid
                    else 0,
                }
            )
            for item in incompatible:
                mismatch_examples.append(
                    {
                        "type": "architecture_incompatible",
                        "task": task,
                        "seed": seed,
                        "parent_node": parent_id,
                        **item,
                    }
                )
            if valid and unaware:
                mismatch_examples.append(
                    {
                        "type": "valid_but_reflection_says_unverified",
                        "task": task,
                        "seed": seed,
                        "parent_node": parent_id,
                        "fields": unaware,
                        "text": reflection_text,
                    }
                )
            if not valid and positive:
                invalid_positive_examples.append(
                    {
                        "task": task,
                        "seed": seed,
                        "parent_node": parent_id,
                        "fields": positive,
                        "text": reflection_text,
                    }
                )

        if arm == "code_only":
            assert handoff_count == 0, (run_dir, handoff_count)
        else:
            assert handoff_count == 9, (run_dir, handoff_count)

        if arm == "code_only":
            for node_id, (child_dir, report) in reports.items():
                parent_id = report.get("parent_id")
                if parent_id is None:
                    continue
                parent_dir, parent = reports[parent_id]
                source_path = parent_dir / CANDIDATE[task]
                current = (
                    collections.Counter(
                        extract_comments(source_path.read_text(errors="replace"))
                    )
                    if source_path.exists()
                    else collections.Counter()
                )
                added = list((current - baseline_comments[task]).elements())
                evaluation_comments = [
                    item
                    for item in added
                    if re.search(
                        r"\b(?:speedup|benchmark|measur\w*|correct\w*|error|"
                        r"self[- ]?test|performance|faster|runtime|timing|gflop)\b",
                        item,
                        re.I,
                    )
                ]
                optimization_comments = [
                    item
                    for item in added
                    if re.search(
                        r"\b(?:todo|next|future|try|should|could|potential|"
                        r"further|bottleneck|consider|optimi\w*|cache|"
                        r"til(?:e|ing)|block(?:ing)?|vector\w*|parallel\w*|"
                        r"unroll\w*|prefetch\w*|schedule)\b",
                        item,
                        re.I,
                    )
                ]
                extra_text = []
                for change in (parent.get("files_changed") or {}).get("added", []):
                    path = (
                        change.get("path", "")
                        if isinstance(change, dict)
                        else str(change)
                    )
                    name = Path(path).name.lower()
                    if (
                        Path(path).suffix.lower() in {".md", ".txt"}
                        and name
                        not in {
                            "candidate_flags.txt",
                            "results.txt",
                            "eval_output.txt",
                        }
                    ):
                        parent_file = parent_dir / path
                        child_file = child_dir / path
                        if (
                            parent_file.is_file()
                            and child_file.is_file()
                            and file_sha256(parent_file) == file_sha256(child_file)
                        ):
                            extra_text.append(path)
                comment_rows.append(
                    {
                        "task": task,
                        "arm": arm,
                        "seed": seed,
                        "child_node": node_id,
                        "parent_node": parent_id,
                        "added_comment_count": len(added),
                        "added_comment_chars": sum(len(item) for item in added),
                        "evaluation_comment_count": len(evaluation_comments),
                        "optimization_comment_count": len(optimization_comments),
                        "extra_text_file_count": len(extra_text),
                        "extra_text_files": "|".join(extra_text),
                        "comments": " || ".join(added),
                    }
                )

        selected_id = final["selected_node_id"]
        selected_dir, _ = reports[selected_id]
        source = (selected_dir / CANDIDATE[task]).read_text(errors="replace")
        executable_source = remove_comments(source)
        flags_path = selected_dir / "candidate_flags.txt"
        flags = flags_path.read_text(errors="replace").strip() if flags_path.exists() else ""
        selected_rows.append(
            {
                "task": task,
                "arm": arm,
                "seed": seed,
                "selected_node_id": selected_id,
                "openmp": bool(
                    re.search(
                        r"#\s*pragma\s+omp\s+(?:parallel|for)",
                        executable_source,
                        re.I,
                    )
                ),
                "simd_pragma": bool(
                    re.search(
                        r"#\s*pragma\s+(?:omp\s+simd|GCC\s+ivdep)",
                        executable_source,
                        re.I,
                    )
                ),
                "explicit_intrinsics": bool(
                    re.search(
                        r"(?:arm_sve|<arm_neon|<immintrin|"
                        r"\bsv[a-z0-9_]+\s*\()",
                        executable_source,
                        re.I,
                    )
                ),
                "blocking_marker": bool(
                    re.search(
                        r"\b(?:tile|tiling|block(?:ing)?|[ijk][bc]|block_size)\b",
                        executable_source,
                        re.I,
                    )
                ),
                "prefetch": bool(
                    re.search(
                        r"(?:__builtin_prefetch|\bprefetch\b)",
                        executable_source,
                        re.I,
                    )
                ),
                "manual_unroll_marker": bool(
                    re.search(
                        r"\b(?:unroll|unrolled)\b", executable_source, re.I
                    )
                ),
                "custom_flags": bool(flags),
                "flags": flags,
            }
        )

    run_frame = pd.DataFrame(rows).sort_values(["task", "seed", "arm"])
    handoff_frame = pd.DataFrame(handoff_rows)
    reflection_frame = pd.DataFrame(reflection_rows)
    comment_frame = pd.DataFrame(comment_rows)
    selected_frame = pd.DataFrame(selected_rows)

    run_frame.to_csv(OUT / "run_level_summary.csv", index=False)
    handoff_frame.to_csv(OUT / "handoff_message_audit.csv", index=False)
    reflection_frame.to_csv(OUT / "reflection_quality_audit.csv", index=False)
    comment_frame.to_csv(OUT / "code_only_leakage_audit.csv", index=False)
    selected_frame.to_csv(
        OUT / "selected_optimization_classification.csv", index=False
    )

    summary = build_summary(
        run_frame,
        handoff_frame,
        reflection_frame,
        comment_frame,
        selected_frame,
        mismatch_examples,
        invalid_positive_examples,
    )
    (OUT / "reviewer_response_analysis.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
    make_paired_figure(run_frame)
    make_difference_figure(run_frame)
    make_cost_figure(run_frame)

    print(
        json.dumps(
            {
                "runs": len(run_frame),
                "handoff": summary["handoff"],
                "reflection": summary["reflection"],
                "code_only_leakage": summary["code_only_leakage"],
                "failed_calls_total": int(run_frame.failed_llm_calls.sum()),
                "all_final_valid": bool(run_frame.valid.all()),
            },
            indent=2,
        )
    )


def build_summary(
    run_frame: pd.DataFrame,
    handoff_frame: pd.DataFrame,
    reflection_frame: pd.DataFrame,
    comment_frame: pd.DataFrame,
    selected_frame: pd.DataFrame,
    mismatch_examples: list[dict],
    invalid_positive_examples: list[dict],
) -> dict:
    summary = {
        "dataset": {
            "runs": len(run_frame),
            "all_final_valid": bool(run_frame.valid.all()),
        },
        "outcomes": {},
        "costs": {},
        "handoff": {},
        "reflection": {},
        "code_only_leakage": {},
        "absolute_performance": {},
        "allocation": {},
        "optimization_classification": {},
    }
    for task in TASKS:
        summary["outcomes"][task] = {}
        summary["costs"][task] = {}
        summary["absolute_performance"][task] = {}
        summary["allocation"][task] = {}
        summary["optimization_classification"][task] = {}
        for arm in ARMS:
            group = run_frame[
                (run_frame.task == task) & (run_frame.arm == arm)
            ]
            summary["outcomes"][task][arm] = quantile_stats(group.score)
            summary["costs"][task][arm] = {
                key: quantile_stats(group[key])
                for key in [
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "llm_calls",
                    "fallback_summary_calls",
                    "failed_llm_calls",
                    "elapsed_seconds",
                ]
            }
            performance = {
                "candidate_ms": quantile_stats(
                    group.absolute_candidate_ms_geomean_cases
                )
            }
            if task in {"gemm", "stencil"}:
                performance["rate"] = quantile_stats(
                    group.absolute_rate_geomean_cases
                )
            summary["absolute_performance"][task][arm] = performance
            summary["allocation"][task][arm] = {
                "host_counts": group.hostname.value_counts()
                .sort_index()
                .to_dict(),
                "array_index_min": int(group.slurm_array_task_id.min()),
                "array_index_max": int(group.slurm_array_task_id.max()),
                "first_start": group.started_at.min(),
                "last_complete": group.completed_at.max(),
            }
            selected = selected_frame[
                (selected_frame.task == task) & (selected_frame.arm == arm)
            ]
            summary["optimization_classification"][task][arm] = {
                key: int(selected[key].sum())
                for key in [
                    "openmp",
                    "simd_pragma",
                    "explicit_intrinsics",
                    "blocking_marker",
                    "prefetch",
                    "manual_unroll_marker",
                    "custom_flags",
                ]
            }

    for arm in ARMS:
        group = handoff_frame[handoff_frame.arm == arm]
        summary["handoff"][arm] = {"messages": len(group)}
        if len(group):
            summary["handoff"][arm].update(
                {
                    "tokens": quantile_stats(group.tokens),
                    "chars": quantile_stats(group.chars),
                }
            )
            if arm != "code_only":
                summary["handoff"][arm]["evidence_tokens"] = quantile_stats(
                    group.evidence_tokens
                )
            if arm == "evidence_plus_reflection":
                summary["handoff"][arm]["reflection_tokens"] = quantile_stats(
                    group.reflection_tokens
                )

    summary["reflection"] = {
        "handoffs": len(reflection_frame),
        "summary_missing": int(reflection_frame.summary_missing.sum()),
        "concerns_missing": int(reflection_frame.concerns_missing.sum()),
        "next_steps_missing": int(reflection_frame.next_steps_missing.sum()),
        "concerns_per_handoff": quantile_stats(reflection_frame.concerns_count),
        "next_steps_per_handoff": quantile_stats(reflection_frame.next_steps_count),
        "novel_next_steps_per_handoff": quantile_stats(
            reflection_frame.novel_next_steps
        ),
        "reflection_tokens": quantile_stats(reflection_frame.reflection_tokens),
        "lexical_reuse_fraction": quantile_stats(
            reflection_frame.lexical_reuse_fraction
        ),
        "architecture_incompatible_handoffs": int(
            (reflection_frame.architecture_incompatible_items > 0).sum()
        ),
        "architecture_incompatible_items": int(
            reflection_frame.architecture_incompatible_items.sum()
        ),
        "valid_evidence_but_reflection_unaware_handoffs": int(
            (reflection_frame.evaluator_unaware_fields_when_valid > 0).sum()
        ),
        "invalid_evidence_but_positive_claim_handoffs": int(
            (reflection_frame.positive_claim_fields_when_invalid > 0).sum()
        ),
        "invalid_parent_handoffs": int((~reflection_frame.measurement_valid).sum()),
    }
    summary["code_only_leakage"] = {
        "child_edges": len(comment_frame),
        "edges_with_agent_added_comments": int(
            (comment_frame.added_comment_count > 0).sum()
        ),
        "edges_with_evaluation_comments": int(
            (comment_frame.evaluation_comment_count > 0).sum()
        ),
        "edges_with_optimization_comments": int(
            (comment_frame.optimization_comment_count > 0).sum()
        ),
        "edges_with_extra_text_files": int(
            (comment_frame.extra_text_file_count > 0).sum()
        ),
        "runs_with_agent_added_comments": int(
            len(comment_frame.loc[
                comment_frame.added_comment_count > 0, ["task", "seed"]
            ].drop_duplicates())
        ),
        "runs_with_evaluation_comments": int(
            len(comment_frame.loc[
                comment_frame.evaluation_comment_count > 0, ["task", "seed"]
            ].drop_duplicates())
        ),
        "runs_with_optimization_comments": int(
            len(comment_frame.loc[
                comment_frame.optimization_comment_count > 0, ["task", "seed"]
            ].drop_duplicates())
        ),
        "runs_with_extra_text_files": int(
            len(comment_frame.loc[
                comment_frame.extra_text_file_count > 0, ["task", "seed"]
            ].drop_duplicates())
        ),
        "by_task": {},
    }
    for task in TASKS:
        task_rows = comment_frame[comment_frame.task == task]
        summary["code_only_leakage"]["by_task"][task] = {
            "edges": len(task_rows),
            "added_comments": int((task_rows.added_comment_count > 0).sum()),
            "evaluation_comments": int(
                (task_rows.evaluation_comment_count > 0).sum()
            ),
            "optimization_comments": int(
                (task_rows.optimization_comment_count > 0).sum()
            ),
            "extra_text_files": int(
                (task_rows.extra_text_file_count > 0).sum()
            ),
        }
    summary["audit_examples"] = {
        "architecture_or_evaluator_mismatch": mismatch_examples[:100],
        "invalid_with_positive_claim": invalid_positive_examples[:100],
    }

    comparisons = [
        ("evidence_only", "code_only", "E-C"),
        ("evidence_plus_reflection", "evidence_only", "R-E"),
    ]
    summary["paired_log_analysis"] = {}
    summary["aligned_randomization_ci"] = {}
    rng = np.random.default_rng(20260731)
    for task in TASKS:
        summary["paired_log_analysis"][task] = {}
        summary["aligned_randomization_ci"][task] = {}
        pivot = (
            run_frame[run_frame.task == task]
            .pivot(index="seed", columns="arm", values="score")
            .sort_index()
        )
        for arm_a, arm_b, label in comparisons:
            differences = np.log(pivot[arm_a].to_numpy()) - np.log(
                pivot[arm_b].to_numpy()
            )
            indices = rng.integers(
                0, len(differences), size=(200_000, len(differences))
            )
            bootstrap = differences[indices].mean(axis=1)
            low, high = np.quantile(bootstrap, [0.025, 0.975])
            signs = rng.choice(
                (-1.0, 1.0), size=(200_000, len(differences))
            )
            permutation = (signs * differences).mean(axis=1)
            p_value = (
                np.count_nonzero(
                    np.abs(permutation) >= abs(np.mean(differences))
                )
                + 1
            ) / (len(permutation) + 1)
            summary["paired_log_analysis"][task][label] = {
                "mean_log_difference": float(np.mean(differences)),
                "geometric_mean_ratio": float(np.exp(np.mean(differences))),
                "bootstrap_95_ci_log": [float(low), float(high)],
                "bootstrap_95_ci_ratio": [
                    float(np.exp(low)),
                    float(np.exp(high)),
                ],
                "sign_flip_p_200k": float(p_value),
                "differences": differences.tolist(),
            }
            arithmetic_differences = (
                pivot[arm_a].to_numpy() - pivot[arm_b].to_numpy()
            )
            summary["aligned_randomization_ci"][task][label] = (
                invert_sign_flip_test(arithmetic_differences, rng)
            )
    return summary


def invert_sign_flip_test(
    differences: np.ndarray, rng: np.random.Generator
) -> dict:
    """Invert one fixed 500k-draw sign-flip test for a 95% interval."""
    draws = 500_000
    signs = rng.choice((-1.0, 1.0), size=(draws, len(differences)))
    signed_data = (signs * differences).mean(axis=1)
    signed_constant = signs.mean(axis=1)
    observed = float(np.mean(differences))

    def p_value(null: float) -> float:
        permuted = np.abs(signed_data - null * signed_constant)
        statistic = abs(observed - null)
        return (np.count_nonzero(permuted >= statistic) + 1) / (draws + 1)

    span = max(10 * float(np.std(differences, ddof=1)), 1.0)
    outer = observed - span
    while p_value(outer) >= 0.05:
        outer -= span
        span *= 2
    low, high = outer, observed
    for _ in range(50):
        middle = (low + high) / 2
        if p_value(middle) >= 0.05:
            high = middle
        else:
            low = middle
    lower = high

    span = max(10 * float(np.std(differences, ddof=1)), 1.0)
    outer = observed + span
    while p_value(outer) >= 0.05:
        outer += span
        span *= 2
    low, high = observed, outer
    for _ in range(50):
        middle = (low + high) / 2
        if p_value(middle) >= 0.05:
            low = middle
        else:
            high = middle
    upper = low
    return {
        "mean_difference": observed,
        "p_zero": p_value(0.0),
        "randomization_95_ci": [float(lower), float(upper)],
        "draws": draws,
    }


def make_paired_figure(run_frame: pd.DataFrame) -> None:
    plt.rcParams.update(
        {
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
        }
    )
    comparisons = [
        ("evidence_only", "code_only", "E-C"),
        ("evidence_plus_reflection", "evidence_only", "R-E"),
    ]
    colors = {"E-C": "#167D8D", "R-E": "#B4493A"}
    figure, axes = plt.subplots(
        3, 2, figsize=(7.1, 8.0), constrained_layout=True
    )
    for row, task in enumerate(TASKS):
        pivot = (
            run_frame[run_frame.task == task]
            .pivot(index="seed", columns="arm", values="score")
            .sort_index()
        )
        for column, (arm_a, arm_b, label) in enumerate(comparisons):
            axis = axes[row, column]
            x = pivot[arm_b].to_numpy()
            y = pivot[arm_a].to_numpy()
            low = min(x.min(), y.min())
            high = max(x.max(), y.max())
            padding = (high - low) * 0.06 or 1
            axis.plot(
                [low - padding, high + padding],
                [low - padding, high + padding],
                color="#777777",
                linewidth=0.8,
                linestyle="--",
            )
            axis.scatter(
                x,
                y,
                s=17,
                color=colors[label],
                alpha=0.78,
                edgecolors="white",
                linewidths=0.25,
            )
            threshold = np.quantile(np.abs(y - x), 0.9)
            for seed, (x_value, y_value) in enumerate(zip(x, y)):
                if abs(y_value - x_value) > threshold:
                    axis.annotate(
                        str(seed),
                        (x_value, y_value),
                        xytext=(2, 2),
                        textcoords="offset points",
                        fontsize=5.5,
                    )
            axis.set_xlim(low - padding, high + padding)
            axis.set_ylim(low - padding, high + padding)
            axis.set_aspect("equal", adjustable="box")
            axis.grid(True, color="#DDDDDD", linewidth=0.4)
            axis.set_title(f"{TASK_LABEL[task]}: {label}")
            axis.set_xlabel(ARM_LABEL[arm_b])
            axis.set_ylabel(ARM_LABEL[arm_a])
    figure.suptitle(
        "Paired final speedups by seed (identity line dashed)", fontsize=10
    )
    figure.savefig(OUT / "paired_seed_outcomes.pdf", bbox_inches="tight")
    figure.savefig(
        OUT / "paired_seed_outcomes.png", dpi=220, bbox_inches="tight"
    )
    plt.close(figure)


def make_difference_figure(run_frame: pd.DataFrame) -> None:
    comparisons = [
        ("evidence_only", "code_only", "Evidence - Workspace"),
        (
            "evidence_plus_reflection",
            "evidence_only",
            "Self-Report - Evidence",
        ),
    ]
    colors = ["#167D8D", "#B4493A"]
    figure, axes = plt.subplots(
        3, 2, figsize=(7.1, 4.7), constrained_layout=True
    )
    for row, task in enumerate(TASKS):
        pivot = (
            run_frame[run_frame.task == task]
            .pivot(index="seed", columns="arm", values="score")
            .sort_index()
        )
        for column, (arm_a, arm_b, label) in enumerate(comparisons):
            axis = axes[row, column]
            differences = pivot[arm_a] - pivot[arm_b]
            axis.axhline(0, color="#555555", linewidth=0.8, linestyle="--")
            axis.scatter(
                differences.index,
                differences,
                s=16,
                color=colors[column],
                alpha=0.82,
                edgecolors="white",
                linewidths=0.25,
            )
            axis.axhline(
                differences.mean(), color=colors[column], linewidth=1.1
            )
            axis.grid(axis="y", color="#DDDDDD", linewidth=0.4)
            axis.set_xlim(-1, 30)
            axis.set_xticks([0, 5, 10, 15, 20, 25, 29])
            axis.set_title(f"{TASK_LABEL[task]}: {label}")
            axis.set_ylabel("Paired speedup difference")
            if row == 2:
                axis.set_xlabel("Seed")
    figure.savefig(OUT / "paired_difference_dotplot.pdf", bbox_inches="tight")
    figure.savefig(
        OUT / "paired_difference_dotplot.png", dpi=220, bbox_inches="tight"
    )
    plt.close(figure)


def make_cost_figure(run_frame: pd.DataFrame) -> None:
    figure, axes = plt.subplots(
        1, 2, figsize=(7.1, 3.0), constrained_layout=True
    )
    data = []
    positions = []
    position = 1.0
    for task in TASKS:
        for arm in ARMS:
            data.append(
                run_frame[
                    (run_frame.task == task) & (run_frame.arm == arm)
                ].total_tokens.to_numpy()
                / 1e6
            )
            positions.append(position)
            position += 1
        position += 0.6
    axes[0].boxplot(
        data,
        positions=positions,
        widths=0.65,
        showfliers=True,
        patch_artist=True,
        boxprops={"facecolor": "#D8E8E8"},
        medianprops={"color": "#222222"},
    )
    axes[0].set_xticks([2, 5.6, 9.2], ["GEMM", "SpMM", "Stencil"])
    axes[0].set_ylabel("LLM tokens per run (millions)")
    axes[0].grid(axis="y", color="#DDDDDD", linewidth=0.4)

    x = np.arange(3)
    width = 0.25
    for index, arm in enumerate(ARMS):
        medians = []
        lower = []
        upper = []
        for task in TASKS:
            values = (
                run_frame[
                    (run_frame.task == task) & (run_frame.arm == arm)
                ].elapsed_seconds.to_numpy()
                / 3600
            )
            median = np.median(values)
            medians.append(median)
            lower.append(median - np.quantile(values, 0.25))
            upper.append(np.quantile(values, 0.75) - median)
        axes[1].bar(
            x + (index - 1) * width,
            medians,
            width,
            label=ARM_LABEL[arm],
            yerr=np.array([lower, upper]),
            capsize=2,
        )
    axes[1].set_xticks(x, [task.upper() for task in TASKS])
    axes[1].set_ylabel("End-to-end hours per run, median (IQR)")
    axes[1].grid(axis="y", color="#DDDDDD", linewidth=0.4)
    axes[1].legend(fontsize=6)
    figure.savefig(OUT / "cost_elapsed_audit.pdf", bbox_inches="tight")
    figure.savefig(
        OUT / "cost_elapsed_audit.png", dpi=220, bbox_inches="tight"
    )
    plt.close(figure)


if __name__ == "__main__":
    main()
