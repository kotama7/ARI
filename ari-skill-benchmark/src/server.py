"""Deterministic, provenance-preserving scientific analysis MCP server."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import platform
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import scipy
from mcp.server.fastmcp import FastMCP
from scipy import stats

from ari.public.analysis import (
    AnalysisArtifactV1,
    AnalysisObservationV1,
    AnalysisRequestV1,
    AnalysisResultV1,
    AnalysisSummaryV1,
    MetricSampleSetV1,
    RunComparisonRequestV1,
    RunComparisonResultV1,
    StatisticalComparisonResultV1,
    StatisticalComparisonV1,
    StatisticalTestRequestV1,
    canonical_analysis_digest,
)


mcp = FastMCP("benchmark-skill")

_LIBRARY_VERSIONS = {
    "python": platform.python_version(),
    "numpy": np.__version__,
    "scipy": scipy.__version__,
}


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _json_safe(value: Any) -> Any:
    """Encode caller-declared missing floats without permitting JSON NaN."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else "+Infinity" if value > 0 else "-Infinity"
    return value


def _column_name(source: Any, names: list[str]) -> str:
    if source.value_column is not None:
        if source.value_column not in names:
            raise ValueError(
                f"value column {source.value_column!r} is absent from analysis source"
            )
        return source.value_column
    identity_columns = {
        source.replicate_id_column,
        source.pair_id_column,
        source.backend_id_column,
        source.environment_digest_column,
    }
    candidates = [name for name in names if name not in identity_columns]
    if len(candidates) != 1:
        raise ValueError(
            "value_column is required when an analysis source has multiple data columns"
        )
    return candidates[0]


def _cell(row: dict[str, Any], column: str | None) -> str | None:
    if column is None:
        return None
    if column not in row:
        raise ValueError(f"identity column {column!r} is absent from analysis source")
    raw = row[column]
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _numeric_value(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"analysis value {raw!r} is not numeric") from exc


def _rows_to_observations(rows: list[dict[str, Any]], source: Any) -> list[AnalysisObservationV1]:
    if not rows:
        return []
    names: list[str] = []
    for row in rows:
        for name in row:
            if name not in names:
                names.append(name)
    value_column = _column_name(source, names)
    return [
        AnalysisObservationV1(
            value=_numeric_value(row.get(value_column)),
            replicate_id=_cell(row, source.replicate_id_column),
            pair_id=_cell(row, source.pair_id_column),
            backend_id=_cell(row, source.backend_id_column),
            environment_digest=_cell(row, source.environment_digest_column),
        )
        for row in rows
    ]


def _load_json(payload: bytes, source: Any) -> list[AnalysisObservationV1]:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("analysis JSON source is not valid UTF-8 JSON") from exc

    if isinstance(document, list):
        if not document:
            return []
        if all(not isinstance(item, dict) for item in document):
            if any(
                column is not None
                for column in (
                    source.value_column,
                    source.replicate_id_column,
                    source.pair_id_column,
                    source.backend_id_column,
                    source.environment_digest_column,
                )
            ):
                raise ValueError("JSON scalar arrays cannot declare source columns")
            return [AnalysisObservationV1(value=_numeric_value(item)) for item in document]
        if not all(isinstance(item, dict) for item in document):
            raise ValueError("analysis JSON arrays cannot mix objects and scalar values")
        return _rows_to_observations(document, source)

    if isinstance(document, dict):
        if source.value_column is None:
            if len(document) != 1:
                raise ValueError("value_column is required for multi-column JSON objects")
            value_column = next(iter(document))
        else:
            value_column = source.value_column
        values = document.get(value_column)
        if not isinstance(values, list):
            raise ValueError("analysis JSON object value_column must contain an array")
        lengths = {
            len(value)
            for value in document.values()
            if isinstance(value, list)
        }
        if len(lengths) != 1:
            raise ValueError("analysis JSON column arrays must have equal lengths")
        rows = [
            {name: value[index] for name, value in document.items() if isinstance(value, list)}
            for index in range(len(values))
        ]
        source = source.model_copy(update={"value_column": value_column})
        return _rows_to_observations(rows, source)
    raise ValueError("analysis JSON source must be an array or object")


def _load_csv(payload: bytes, source: Any) -> list[AnalysisObservationV1]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("analysis CSV source is not valid UTF-8") from exc
    # Instrument outputs commonly prefix RFC-4180 data with ``#`` metadata.
    # Comments are excluded from the typed table, while the source digest still
    # binds the complete original byte stream (including those metadata lines).
    text = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("analysis CSV source has no header")
    return _rows_to_observations(list(reader), source)


def _load_npy(payload: bytes, source: Any) -> list[AnalysisObservationV1]:
    if any(
        column is not None
        for column in (
            source.replicate_id_column,
            source.pair_id_column,
            source.backend_id_column,
            source.environment_digest_column,
        )
    ):
        raise ValueError("npy sources cannot declare identity columns")
    try:
        array = np.load(io.BytesIO(payload), allow_pickle=False)
    except (ValueError, OSError) as exc:
        raise ValueError("analysis npy source is invalid or uses object data") from exc
    if array.dtype.names:
        if source.value_column is None or source.value_column not in array.dtype.names:
            raise ValueError("structured npy source requires a valid value_column")
        array = array[source.value_column]
    elif array.ndim == 2:
        if source.value_column is None:
            raise ValueError("two-dimensional npy source requires a numeric value_column")
        try:
            index = int(source.value_column)
        except ValueError as exc:
            raise ValueError("npy value_column must be a numeric column index") from exc
        if index < 0 or index >= array.shape[1]:
            raise ValueError("npy value_column is outside the array bounds")
        array = array[:, index]
    elif array.ndim != 1:
        raise ValueError("analysis npy source must be one- or two-dimensional")
    return [AnalysisObservationV1(value=_numeric_value(item)) for item in array.tolist()]


def _load_source(source: Any) -> tuple[list[AnalysisObservationV1], str]:
    payload = source.workspace.read_bytes(source.relative_path, max_bytes=source.max_bytes)
    digest = _sha256(payload)
    if digest != source.expected_digest:
        raise ValueError(
            f"analysis source digest mismatch: expected {source.expected_digest}, got {digest}"
        )
    source_format = source.format
    if source_format == "auto":
        suffix = Path(source.relative_path).suffix.lower()
        source_format = {".csv": "csv", ".json": "json", ".npy": "npy"}.get(suffix)
        if source_format is None:
            raise ValueError(f"unsupported analysis source extension: {suffix or '<none>'}")
    if source_format == "csv":
        observations = _load_csv(payload, source)
    elif source_format == "json":
        observations = _load_json(payload, source)
    elif source_format == "npy":
        observations = _load_npy(payload, source)
    else:  # pragma: no cover - Literal validation makes this unreachable
        raise ValueError(f"unsupported analysis source format: {source_format}")
    return observations, digest


def _resolve_dataset(
    dataset: MetricSampleSetV1,
    missing_policy: str,
) -> tuple[list[AnalysisObservationV1], int, str]:
    if dataset.source is not None:
        observations, source_digest = _load_source(dataset.source)
    else:
        observations = list(dataset.observations or [])
        source_digest = canonical_analysis_digest(
            _json_safe(observations)
        )
    if not observations:
        raise ValueError(f"metric {dataset.metric_id!r} has an empty sample")
    finite: list[AnalysisObservationV1] = []
    missing_count = 0
    for observation in observations:
        value = observation.value
        if value is None or not math.isfinite(value):
            missing_count += 1
            if missing_policy == "error":
                raise ValueError(
                    f"metric {dataset.metric_id!r} contains a missing or non-finite value"
                )
            continue
        finite.append(observation)
    if not finite:
        raise ValueError(f"metric {dataset.metric_id!r} contains only missing values")
    return finite, missing_count, source_digest


def _independence_status(observations: Iterable[AnalysisObservationV1]) -> str:
    items = list(observations)
    ids = [item.replicate_id for item in items]
    if all(ids) and len(set(ids)) == len(ids):
        return "declared"
    return "not-established"


def _mean_ci(values: np.ndarray, confidence: float) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    standard_error = float(stats.sem(values))
    if not math.isfinite(standard_error):
        return None
    radius = float(stats.t.ppf((1.0 + confidence) / 2.0, len(values) - 1)) * standard_error
    mean = float(np.mean(values))
    return mean - radius, mean + radius


def _summary(
    dataset: MetricSampleSetV1,
    observations: list[AnalysisObservationV1],
    missing_count: int,
    source_digest: str,
    confidence: float,
) -> AnalysisSummaryV1:
    values = np.asarray([item.value for item in observations], dtype=float)
    count = len(values)
    std = float(np.std(values, ddof=1)) if count > 1 else None
    variance = float(np.var(values, ddof=1)) if count > 1 else None
    q25, median, q75 = np.quantile(values, [0.25, 0.5, 0.75]).tolist()
    return AnalysisSummaryV1(
        metric_id=dataset.metric_id,
        unit=dataset.unit,
        count=count,
        missing_count=missing_count,
        mean=float(np.mean(values)),
        std=std,
        variance=variance,
        minimum=float(np.min(values)),
        q25=float(q25),
        median=float(median),
        q75=float(q75),
        maximum=float(np.max(values)),
        mean_confidence_interval=_mean_ci(values, confidence),
        constant_data=bool(np.ptp(values) == 0),
        independence_status=_independence_status(observations),
        source_digest=source_digest,
    )


def _normality(values: np.ndarray) -> dict[str, Any]:
    if len(values) < 3:
        return {"method": "not-tested", "reason": "fewer-than-3-samples"}
    if np.ptp(values) == 0:
        return {"method": "not-tested", "reason": "constant-data"}
    if len(values) <= 5_000:
        statistic, p_value = stats.shapiro(values)
        method = "shapiro-wilk"
    else:
        statistic, p_value = stats.normaltest(values)
        method = "dagostino-pearson"
    return {
        "method": method,
        "statistic": float(statistic),
        "p_value": float(p_value),
        "normal_at_0_05": bool(p_value >= 0.05),
    }


def _align_paired(
    comparison: StatisticalComparisonV1,
    a: list[AnalysisObservationV1],
    b: list[AnalysisObservationV1],
    missing_policy: str,
) -> tuple[list[AnalysisObservationV1], list[AnalysisObservationV1]]:
    if comparison.pairing == "ordered":
        if len(a) != len(b):
            raise ValueError(
                f"comparison {comparison.comparison_id!r} has unequal paired lengths"
            )
        return a, b
    if comparison.pairing != "pair_id":
        return a, b
    if any(item.pair_id is None for item in a + b):
        raise ValueError("pair_id pairing requires every retained observation to have pair_id")
    map_a = {item.pair_id: item for item in a}
    map_b = {item.pair_id: item for item in b}
    if len(map_a) != len(a) or len(map_b) != len(b):
        raise ValueError("pair_id values must be unique within each sample group")
    if set(map_a) != set(map_b) and missing_policy == "error":
        raise ValueError("pair_id groups do not contain the same pairs")
    common = sorted(set(map_a) & set(map_b))
    if not common:
        raise ValueError("paired comparison has no common pair_id values")
    return [map_a[key] for key in common], [map_b[key] for key in common]


def _select_test(
    comparison: StatisticalComparisonV1,
    a: np.ndarray,
    b: np.ndarray,
) -> str:
    if comparison.test_family != "auto":
        return comparison.test_family
    paired = comparison.pairing != "unpaired"
    if paired:
        differences = a - b
        normal = _normality(differences)
        return "paired_t" if normal.get("normal_at_0_05") else "wilcoxon"
    normal_a = _normality(a)
    normal_b = _normality(b)
    if normal_a.get("normal_at_0_05") and normal_b.get("normal_at_0_05"):
        return "welch_t"
    return "mann_whitney"


def _mean_difference_ci(
    a: np.ndarray,
    b: np.ndarray,
    confidence: float,
    *,
    paired: bool,
    equal_var: bool = False,
) -> tuple[float, float]:
    if paired:
        differences = a - b
        if len(differences) < 2:
            raise ValueError("paired mean confidence interval requires at least two pairs")
        mean = float(np.mean(differences))
        se = float(stats.sem(differences))
        df = len(differences) - 1
    else:
        if len(a) < 2 or len(b) < 2:
            raise ValueError("mean confidence interval requires two samples per group")
        mean = float(np.mean(a) - np.mean(b))
        variance_a = float(np.var(a, ddof=1))
        variance_b = float(np.var(b, ddof=1))
        if equal_var:
            df = len(a) + len(b) - 2
            pooled = ((len(a) - 1) * variance_a + (len(b) - 1) * variance_b) / df
            se = math.sqrt(pooled * (1 / len(a) + 1 / len(b)))
        else:
            term_a = variance_a / len(a)
            term_b = variance_b / len(b)
            se = math.sqrt(term_a + term_b)
            denominator = term_a**2 / (len(a) - 1) + term_b**2 / (len(b) - 1)
            df = (term_a + term_b) ** 2 / denominator if denominator else math.inf
    if not math.isfinite(se) or se == 0:
        raise ValueError("mean difference is undefined for the supplied constant data")
    critical = float(stats.t.ppf((1 + confidence) / 2, df))
    return mean - critical * se, mean + critical * se


def _cohens_d(a: np.ndarray, b: np.ndarray, *, paired: bool) -> float:
    if paired:
        differences = a - b
        denominator = float(np.std(differences, ddof=1))
        if denominator == 0:
            raise ValueError("paired effect size is undefined for constant differences")
        return float(np.mean(differences) / denominator)
    denominator_df = len(a) + len(b) - 2
    if denominator_df <= 0:
        raise ValueError("effect size requires at least two total degrees of freedom")
    pooled_variance = (
        (len(a) - 1) * float(np.var(a, ddof=1))
        + (len(b) - 1) * float(np.var(b, ddof=1))
    ) / denominator_df
    if pooled_variance <= 0:
        raise ValueError("effect size is undefined for constant samples")
    return float((np.mean(a) - np.mean(b)) / math.sqrt(pooled_variance))


def _rank_biserial_ci(effect: float, n_a: int, n_b: int, confidence: float) -> tuple[float, float]:
    z = float(stats.norm.ppf((1 + confidence) / 2))
    standard_error = math.sqrt((n_a + n_b + 1) / (3 * n_a * n_b))
    return max(-1.0, effect - z * standard_error), min(1.0, effect + z * standard_error)


def _run_comparison_test(
    comparison: StatisticalComparisonV1,
    observations_a: list[AnalysisObservationV1],
    observations_b: list[AnalysisObservationV1],
    missing_a: int,
    missing_b: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    a = np.asarray([item.value for item in observations_a], dtype=float)
    b = np.asarray([item.value for item in observations_b], dtype=float)
    family = _select_test(comparison, a, b)
    assumptions: dict[str, Any] = {
        "normality_a": _normality(a),
        "normality_b": _normality(b),
        "independence_a": _independence_status(observations_a),
        "independence_b": _independence_status(observations_b),
        "pairing_verified": comparison.pairing == "pair_id",
        "missing_count_a": missing_a,
        "missing_count_b": missing_b,
    }
    if len(a) > 1 and len(b) > 1 and np.ptp(a) and np.ptp(b):
        levene_stat, levene_p = stats.levene(a, b, center="median")
        assumptions["equal_variance"] = {
            "method": "brown-forsythe",
            "statistic": float(levene_stat),
            "p_value": float(levene_p),
            "equal_at_0_05": bool(levene_p >= 0.05),
        }
    else:
        assumptions["equal_variance"] = {
            "method": "not-tested",
            "reason": "constant-or-singleton-data",
        }

    if family == "welch_t":
        if np.ptp(a) == 0 and np.ptp(b) == 0:
            raise ValueError("parametric effect is undefined for constant samples")
        statistic, p_value = stats.ttest_ind(
            a, b, equal_var=False, alternative=comparison.alternative
        )
        effect_name = "cohens_d"
        effect = _cohens_d(a, b, paired=False)
        ci_name = "mean_difference"
        interval = _mean_difference_ci(a, b, comparison.confidence_level, paired=False)
    elif family == "student_t":
        if np.ptp(a) == 0 and np.ptp(b) == 0:
            raise ValueError("parametric effect is undefined for constant samples")
        statistic, p_value = stats.ttest_ind(
            a, b, equal_var=True, alternative=comparison.alternative
        )
        effect_name = "cohens_d"
        effect = _cohens_d(a, b, paired=False)
        ci_name = "mean_difference"
        interval = _mean_difference_ci(
            a, b, comparison.confidence_level, paired=False, equal_var=True
        )
    elif family == "paired_t":
        if np.ptp(a - b) == 0:
            raise ValueError("paired effect size is undefined for constant differences")
        statistic, p_value = stats.ttest_rel(a, b, alternative=comparison.alternative)
        effect_name = "cohens_dz"
        effect = _cohens_d(a, b, paired=True)
        ci_name = "paired_mean_difference"
        interval = _mean_difference_ci(a, b, comparison.confidence_level, paired=True)
    elif family == "mann_whitney":
        statistic, p_value = stats.mannwhitneyu(
            a, b, alternative=comparison.alternative, method="auto"
        )
        effect_name = "rank_biserial"
        effect = float(2 * statistic / (len(a) * len(b)) - 1)
        ci_name = "rank_biserial_normal_approximation"
        interval = _rank_biserial_ci(effect, len(a), len(b), comparison.confidence_level)
    elif family == "wilcoxon":
        differences = a - b
        if np.all(differences == 0):
            raise ValueError("wilcoxon test is undefined when every paired difference is zero")
        statistic, p_value = stats.wilcoxon(
            a,
            b,
            alternative=comparison.alternative,
            zero_method="wilcox",
            method="auto",
        )
        ranks = stats.rankdata(np.abs(differences[differences != 0]))
        signed = differences[differences != 0]
        positive = float(np.sum(ranks[signed > 0]))
        negative = float(np.sum(ranks[signed < 0]))
        effect_name = "matched_pairs_rank_biserial"
        effect = (positive - negative) / (positive + negative)
        ci_name = "rank_biserial_normal_approximation"
        interval = _rank_biserial_ci(effect, len(signed), len(signed), comparison.confidence_level)
    else:  # pragma: no cover - selection is closed above
        raise ValueError(f"unsupported statistical test family: {family}")

    if not all(math.isfinite(float(value)) for value in (statistic, p_value, effect, *interval)):
        raise ValueError("statistical result is undefined for the supplied samples")
    result = {
        "test_family": family,
        "statistic": float(statistic),
        "p_value": float(p_value),
        "effect_size_name": effect_name,
        "effect_size": float(effect),
        "confidence_interval_name": ci_name,
        "confidence_interval": (float(interval[0]), float(interval[1])),
    }
    return result, assumptions


def _adjust_p_values(p_values: list[float], correction: str) -> list[float]:
    count = len(p_values)
    if correction == "none":
        return list(p_values)
    if correction == "bonferroni":
        return [min(1.0, value * count) for value in p_values]
    order = sorted(range(count), key=lambda index: (p_values[index], index))
    adjusted = [0.0] * count
    if correction == "holm":
        running = 0.0
        for rank, index in enumerate(order):
            candidate = min(1.0, (count - rank) * p_values[index])
            running = max(running, candidate)
            adjusted[index] = running
        return adjusted
    if correction == "benjamini_hochberg":
        running = 1.0
        for rank in range(count, 0, -1):
            index = order[rank - 1]
            candidate = min(1.0, p_values[index] * count / rank)
            running = min(running, candidate)
            # Guard against a sub-ulp round-off below the raw p-value.
            adjusted[index] = max(p_values[index], running)
        return adjusted
    raise ValueError(f"unsupported multiple-comparison correction: {correction}")


def _artifact_rows(result: AnalysisResultV1) -> tuple[list[str], list[list[Any]]]:
    if result.kind == "summary":
        header = [
            "metric_id", "unit", "count", "missing_count", "mean", "std",
            "minimum", "q25", "median", "q75", "maximum", "source_digest",
        ]
        rows = [
            [
                item.metric_id, item.unit, item.count, item.missing_count, item.mean,
                item.std, item.minimum, item.q25, item.median, item.q75,
                item.maximum, item.source_digest,
            ]
            for item in result.summaries
        ]
        return header, rows
    if result.kind == "statistical-test":
        header = [
            "comparison_id", "metric_id", "unit", "test_family", "statistic",
            "p_value", "adjusted_p_value", "effect_size_name", "effect_size",
            "significant", "input_digest",
        ]
        rows = [
            [
                item.comparison_id, item.metric_id, item.unit, item.test_family,
                item.statistic, item.p_value, item.adjusted_p_value,
                item.effect_size_name, item.effect_size, item.significant,
                item.input_digest,
            ]
            for item in result.comparisons
        ]
        return header, rows
    assert result.run_comparison is not None
    header = ["rank", "run_id", "value", "delta", "relative_delta"]
    rows = [
        [item["rank"], item["run_id"], item["value"], item["delta"], item["relative_delta"]]
        for item in result.run_comparison.ranking
    ]
    return header, rows


def _with_artifacts(result: AnalysisResultV1, target: Any) -> AnalysisResultV1:
    if target is None:
        return result
    digest_slug = result.input_digest.removeprefix("sha256:")
    base = f"{target.relative_directory}/{digest_slug}"
    machine_path = f"{base}/result.json"
    table_path = f"{base}/table.csv"
    machine_payload = (
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    header, rows = _artifact_rows(result)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    table_payload = output.getvalue().encode("utf-8")
    target.workspace.atomic_write_bytes(machine_path, machine_payload)
    target.workspace.atomic_write_bytes(table_path, table_payload)
    artifacts = [
        AnalysisArtifactV1(
            relative_path=machine_path,
            digest=_sha256(machine_payload),
            size_bytes=len(machine_payload),
            media_type="application/json",
            logical_role="analysis-json",
        ),
        AnalysisArtifactV1(
            relative_path=table_path,
            digest=_sha256(table_payload),
            size_bytes=len(table_payload),
            media_type="text/csv; charset=utf-8",
            logical_role="analysis-table",
        ),
    ]
    return result.model_copy(update={"artifacts": artifacts})


@mcp.tool()
def analyze_results(request: dict[str, Any]) -> dict[str, Any]:
    """Summarize typed, unit-bearing samples under ``AnalysisRequestV1``."""

    parsed = AnalysisRequestV1.model_validate(request)
    summaries: list[AnalysisSummaryV1] = []
    resolved_identity: list[dict[str, Any]] = []
    for dataset in parsed.datasets:
        observations, missing_count, source_digest = _resolve_dataset(
            dataset, parsed.missing_policy
        )
        summaries.append(
            _summary(
                dataset,
                observations,
                missing_count,
                source_digest,
                parsed.confidence_level,
            )
        )
        resolved_identity.append(
            {
                "metric_id": dataset.metric_id,
                "unit": dataset.unit,
                "observations": [item.model_dump(mode="json") for item in observations],
                "missing_count": missing_count,
                "source_digest": source_digest,
            }
        )
    input_digest = canonical_analysis_digest(
        {
            "schema_version": parsed.schema_version,
            "datasets": resolved_identity,
            "missing_policy": parsed.missing_policy,
            "confidence_level": parsed.confidence_level,
            "analysis_plan_digest": parsed.analysis_plan_digest,
        }
    )
    result = AnalysisResultV1(
        kind="summary",
        input_digest=input_digest,
        analysis_plan_digest=parsed.analysis_plan_digest,
        library_versions=_LIBRARY_VERSIONS,
        summaries=summaries,
    )
    return _with_artifacts(result, parsed.artifact_target).model_dump(mode="json")


@mcp.tool()
def statistical_test(request: dict[str, Any]) -> dict[str, Any]:
    """Run a pre-declared statistical family with effect sizes and corrected p-values."""

    parsed = StatisticalTestRequestV1.model_validate(request)
    provisional: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    for comparison in parsed.comparisons:
        a, missing_a, digest_a = _resolve_dataset(comparison.group_a, parsed.missing_policy)
        b, missing_b, digest_b = _resolve_dataset(comparison.group_b, parsed.missing_policy)
        a, b = _align_paired(comparison, a, b, parsed.missing_policy)
        test_result, assumptions = _run_comparison_test(
            comparison, a, b, missing_a, missing_b
        )
        identity = {
            "comparison": _json_safe(comparison),
            "resolved_a": [item.model_dump(mode="json") for item in a],
            "resolved_b": [item.model_dump(mode="json") for item in b],
            "source_digest_a": digest_a,
            "source_digest_b": digest_b,
            "missing_count_a": missing_a,
            "missing_count_b": missing_b,
        }
        comparison_digest = canonical_analysis_digest(identity)
        identities.append(identity)
        provisional.append(
            {
                "comparison": comparison,
                "observations_a": a,
                "observations_b": b,
                "missing_a": missing_a,
                "missing_b": missing_b,
                "test": test_result,
                "assumptions": assumptions,
                "input_digest": comparison_digest,
            }
        )
    adjusted = _adjust_p_values(
        [item["test"]["p_value"] for item in provisional], parsed.correction
    )
    comparisons: list[StatisticalComparisonResultV1] = []
    for item, adjusted_p in zip(provisional, adjusted, strict=True):
        comparison = item["comparison"]
        test_result = item["test"]
        comparisons.append(
            StatisticalComparisonResultV1(
                comparison_id=comparison.comparison_id,
                metric_id=comparison.group_a.metric_id,
                unit=comparison.group_a.unit,
                test_family=test_result["test_family"],
                alternative=comparison.alternative,
                pairing=comparison.pairing,
                sample_count_a=len(item["observations_a"]),
                sample_count_b=len(item["observations_b"]),
                missing_count_a=item["missing_a"],
                missing_count_b=item["missing_b"],
                statistic=test_result["statistic"],
                p_value=test_result["p_value"],
                adjusted_p_value=adjusted_p,
                alpha=comparison.alpha,
                significant=bool(adjusted_p < comparison.alpha),
                effect_size_name=test_result["effect_size_name"],
                effect_size=test_result["effect_size"],
                confidence_interval_name=test_result["confidence_interval_name"],
                confidence_interval=test_result["confidence_interval"],
                assumptions={
                    **item["assumptions"],
                    "multiple_comparison_correction": parsed.correction,
                },
                input_digest=item["input_digest"],
            )
        )
    input_digest = canonical_analysis_digest(
        {
            "schema_version": parsed.schema_version,
            "comparisons": identities,
            "missing_policy": parsed.missing_policy,
            "correction": parsed.correction,
            "analysis_plan_digest": parsed.analysis_plan_digest,
        }
    )
    result = AnalysisResultV1(
        kind="statistical-test",
        input_digest=input_digest,
        analysis_plan_digest=parsed.analysis_plan_digest,
        library_versions=_LIBRARY_VERSIONS,
        comparisons=comparisons,
    )
    return _with_artifacts(result, parsed.artifact_target).model_dump(mode="json")


def _provenance_differences(runs: list[Any], baseline: Any) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    baseline_values = {
        "backend_id": baseline.backend_id,
        "environment_digest": baseline.environment_digest,
        "input_digest": baseline.input_digest,
        "provenance_digest": baseline.provenance_digest,
        "library_versions": baseline.library_versions,
    }
    for run in runs:
        changed = {
            field: {"baseline": baseline_values[field], "candidate": value}
            for field, value in {
                "backend_id": run.backend_id,
                "environment_digest": run.environment_digest,
                "input_digest": run.input_digest,
                "provenance_digest": run.provenance_digest,
                "library_versions": run.library_versions,
            }.items()
            if value != baseline_values[field]
        }
        if changed:
            differences.append({"run_id": run.run_id, "changes": changed})
    return differences


@mcp.tool()
def compare_runs(request: dict[str, Any]) -> dict[str, Any]:
    """Rank scalar runs and report environment/provenance compatibility."""

    parsed = RunComparisonRequestV1.model_validate(request)
    substrates: dict[tuple[str, str], list[str]] = defaultdict(list)
    for run in parsed.runs:
        substrates[(run.backend_id, run.environment_digest)].append(run.run_id)
    environment_compatible = len(substrates) == 1
    if parsed.require_compatible_environment and not environment_compatible:
        raise ValueError(
            "run comparison environments differ; set require_compatible_environment=false "
            "to obtain a caveated cross-environment ranking"
        )
    baseline_id = parsed.baseline_run_id or parsed.runs[0].run_id
    by_id = {run.run_id: run for run in parsed.runs}
    baseline = by_id[baseline_id]
    reverse = parsed.direction == "higher"
    ranked = sorted(parsed.runs, key=lambda run: (run.value, run.run_id), reverse=reverse)
    ranking: list[dict[str, Any]] = []
    for rank, run in enumerate(ranked, start=1):
        delta = run.value - baseline.value
        relative = delta / abs(baseline.value) if baseline.value != 0 else None
        ranking.append(
            {
                "rank": rank,
                "run_id": run.run_id,
                "value": run.value,
                "delta": delta,
                "relative_delta": relative,
                "backend_id": run.backend_id,
                "environment_digest": run.environment_digest,
                "replicate_id": run.replicate_id,
            }
        )
    replicate_ids = [run.replicate_id for run in parsed.runs]
    if all(replicate_ids) and len(set(replicate_ids)) == len(replicate_ids):
        independence_status = "declared"
        independent_count: int | None = len(set(replicate_ids))
    else:
        independence_status = "not-established"
        independent_count = None
    environment_groups = [
        {
            "backend_id": backend_id,
            "environment_digest": environment_digest,
            "run_ids": sorted(run_ids),
            "shared_substrate": len(run_ids) > 1,
            "independence_inference": "not-permitted",
        }
        for (backend_id, environment_digest), run_ids in sorted(substrates.items())
    ]
    run_result = RunComparisonResultV1(
        metric_id=parsed.runs[0].metric_id,
        unit=parsed.runs[0].unit,
        direction=parsed.direction,
        ranking=ranking,
        baseline_run_id=baseline_id,
        environment_compatible=environment_compatible,
        environment_groups=environment_groups,
        independence_status=independence_status,
        independent_replicate_count=independent_count,
        provenance_differences=_provenance_differences(parsed.runs, baseline),
    )
    input_digest = canonical_analysis_digest(
        {
            "schema_version": parsed.schema_version,
            "runs": [run.model_dump(mode="json") for run in parsed.runs],
            "direction": parsed.direction,
            "baseline_run_id": baseline_id,
            "require_compatible_environment": parsed.require_compatible_environment,
            "analysis_plan_digest": parsed.analysis_plan_digest,
        }
    )
    result = AnalysisResultV1(
        kind="run-comparison",
        input_digest=input_digest,
        analysis_plan_digest=parsed.analysis_plan_digest,
        library_versions=_LIBRARY_VERSIONS,
        run_comparison=run_result,
    )
    return _with_artifacts(result, parsed.artifact_target).model_dump(mode="json")


if __name__ == "__main__":
    mcp.run()
