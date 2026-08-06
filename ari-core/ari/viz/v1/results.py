"""Results / EAR read models for ``/api/v1`` (gui_refresh task 07 Wave 4d).

Plan 07 §Evidence, Results, and PaperBench: the v2 Results workspace reads
BOUNDED scalars — review scores, the ORS reproducibility-chain verdict, and
the EAR curate → preview → publish → promote lineage — over committed
checkpoint artifacts.  Same posture as :mod:`ari.viz.v1.queries`:

- pure filesystem reads (no ``viz.state`` mutation, no ``os.environ``
  writes, nothing is ever written);
- run resolution through ``checkpoint_finder._resolve_checkpoint_dir`` (the
  ``api_state`` facade deferral, so test monkeypatches are honored);
- honest absence: every block carries presence flags derived from artifact
  existence alone — an absent artifact is never fabricated into
  empty-but-healthy scalars, and a parse failure degrades (200 +
  ``degraded_reasons``), never 500s;
- the ORS verdict REUSES ``ari.viz.ear._synth_repro_report_from_ors``
  read-only (imported at call time; ``ear.py`` itself is not modified), so
  the v2 verdict can never drift from the legacy Results page's.

No file content rides these endpoints: the legacy ``#/results`` page remains
the full editor/PDF workspace (plan 07 migration sequence; Wave 5 embeds).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..checkpoint_finder import _resolve_checkpoint_dir
from .dto import (
    EarFileV1,
    EarManifestV1,
    EarPublishRecordV1,
    ResultEarV1,
    ResultOrsV1,
    ResultPaperV1,
    ResultReviewV1,
    ReviewDimensionV1,
    RunEarV1,
    RunResultsV1,
)
from .errors import error_response

log = logging.getLogger(__name__)

#: Bounded ``ear/`` listing size (plan 07: bounded query/render; the full
#: tree stays browsable on the legacy artifact surfaces).
_MAX_EAR_FILES = 500

# ORS chain stage artifacts (the OrsChainSection stage files — checkpoint_api
# reads the same names): (stage flag name, candidate file names).
_ORS_STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rubric_present", ("ors_rubric.meta.json", "ors_rubric.json")),
    ("replicator_present", ("ors_replicator.json",)),
    ("seed_present", ("ors_seed.json",)),
    ("phase1_present", ("ors_phase1.json",)),
    ("grade_present", ("ors_grade.json",)),
)


def _num(v: object) -> float | None:
    """Scalar number pass-through; bool/str/None never coerced."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _text(v: object) -> str | None:
    """Non-empty string pass-through; anything else is None (never str())."""
    return v if isinstance(v, str) and v != "" else None


def _load_json(p: Path) -> tuple[object | None, str | None]:
    """Parse one JSON artifact: ``(data, None)`` or ``(None, reason)``."""
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace")), None
    except (OSError, json.JSONDecodeError) as e:
        log.debug("v1 results parse error: %s", p, exc_info=True)
        return None, f"{p.name} is not valid JSON: {e}"


def _nonempty(p: Path) -> bool:
    try:
        return p.is_file() and p.stat().st_size > 0
    except OSError:
        return False


# ── block builders ─────────────────────────────────────────────────────────


def _paper_block(d: Path) -> ResultPaperV1:
    """Presence flags over the two historical paper locations (checkpoint
    root and ``paper/`` — the same candidates the legacy summary probes)."""
    return ResultPaperV1(
        tex_present=(d / "full_paper.tex").is_file()
        or (d / "paper" / "full_paper.tex").is_file(),
        pdf_present=(d / "full_paper.pdf").is_file()
        or (d / "paper" / "full_paper.pdf").is_file(),
    )


def _review_block(d: Path, degraded: list[str]) -> ResultReviewV1:
    p = d / "review_report.json"
    if not p.is_file():
        return ResultReviewV1(report_present=False)
    data, err = _load_json(p)
    if err is not None:
        degraded.append(err)
        return ResultReviewV1(report_present=True)
    if not isinstance(data, dict):
        degraded.append("review_report.json top level is not an object")
        return ResultReviewV1(report_present=True)

    # Legacy score fallbacks (ReviewScoresSection): overall_score|score,
    # abstract_score|scores.abstract, body_score|scores.body.
    scores = data.get("scores") if isinstance(data.get("scores"), dict) else {}

    def _score(primary: str, *fallbacks: object) -> float | None:
        v = _num(data.get(primary))
        for fb in fallbacks:
            if v is not None:
                break
            v = _num(fb)
        return v

    dims: list[ReviewDimensionV1] = []
    raw_dims = data.get("score_dimensions")
    if isinstance(raw_dims, list):
        dropped = 0
        for entry in raw_dims:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                dropped += 1
                continue
            scale = entry.get("scale")
            lo, hi = (None, None)
            if isinstance(scale, (list, tuple)) and len(scale) == 2:
                lo, hi = _num(scale[0]), _num(scale[1])
            dims.append(
                ReviewDimensionV1(
                    name=entry["name"],
                    value=_num(entry.get("value")),
                    scale_min=lo,
                    scale_max=hi,
                )
            )
        if dropped:
            degraded.append(
                f"score_dimensions: {dropped} malformed entr(y/ies) dropped"
            )
    elif raw_dims is not None:
        degraded.append("score_dimensions is not a list")

    return ResultReviewV1(
        report_present=True,
        overall_score=_score(
            "overall_score", data.get("score"), scores.get("overall")
        ),
        abstract_score=_score("abstract_score", scores.get("abstract")),
        body_score=_score("body_score", scores.get("body")),
        decision=_text(data.get("decision")),
        confidence=_num(data.get("confidence")),
        rubric_id=_text(data.get("rubric_id")),
        dimensions=dims,
    )


def _ors_block(d: Path) -> ResultOrsV1:
    flags = {
        name: any(_nonempty(d / f) for f in files) for name, files in _ORS_STAGES
    }
    out = ResultOrsV1(chain_present=any(flags.values()), **flags)
    if not out.chain_present:
        return out

    # READ-ONLY reuse of the legacy synthesis (local import keeps ear.py
    # inert until dispatched; the function only reads ors_*.json +
    # bfts_web_provenance.json and never writes).
    from ..ear import _synth_repro_report_from_ors

    synth = _synth_repro_report_from_ors(d)
    if not isinstance(synth, dict):
        return out
    out.verdict = _text(synth.get("verdict"))
    out.summary = _text(synth.get("summary"))
    out.ors_score = _num(synth.get("ors_score"))
    out.raw_score = _num(synth.get("raw_score"))
    passed = _num(synth.get("passed_leaves"))
    total = _num(synth.get("total_leaves"))
    out.passed_leaves = int(passed) if passed is not None else None
    out.total_leaves = int(total) if total is not None else None
    out.judge_model = _text(synth.get("judge_model"))
    return out


def _manifest_block(d: Path, degraded: list[str]) -> EarManifestV1:
    p = d / "ear_published" / "manifest.lock"
    if not p.is_file():
        return EarManifestV1(manifest_present=False)
    data, err = _load_json(p)
    if err is not None or not isinstance(data, dict):
        degraded.append(err or "manifest.lock top level is not an object")
        return EarManifestV1(manifest_present=True)
    files = data.get("files")
    excluded = _num(data.get("excluded_count"))
    pub = data.get("publish")
    return EarManifestV1(
        manifest_present=True,
        bundle_sha256=_text(data.get("bundle_sha256")),
        file_count=len(files) if isinstance(files, list) else None,
        excluded_count=int(excluded) if excluded is not None else None,
        visibility=_text(pub.get("visibility")) if isinstance(pub, dict) else None,
        created_at=_text(data.get("created_at")),
    )


def _publish_record_block(d: Path, degraded: list[str]) -> EarPublishRecordV1:
    p = d / "publish_record.json"
    if not p.is_file():
        return EarPublishRecordV1(record_present=False)
    data, err = _load_json(p)
    if err is not None or not isinstance(data, dict):
        degraded.append(err or "publish_record.json top level is not an object")
        return EarPublishRecordV1(record_present=True)
    return EarPublishRecordV1(
        record_present=True,
        backend=_text(data.get("backend")),
        ref=_text(data.get("ref")),
        bundle_sha256=_text(data.get("bundle_sha256")),
        visibility=_text(data.get("visibility")),
        dry_run=data.get("dry_run") if isinstance(data.get("dry_run"), bool) else None,
        timestamp=_text(data.get("timestamp")),
        promoted_at=_text(data.get("promoted_at")),
    )


def _ear_block(d: Path, degraded: list[str]) -> ResultEarV1:
    manifest = _manifest_block(d, degraded)
    record = _publish_record_block(d, degraded)
    visibility: str | None = None
    visibility_source: str | None = None
    if record.record_present and record.visibility is not None:
        visibility, visibility_source = record.visibility, "publish_record"
    elif manifest.manifest_present and manifest.visibility is not None:
        visibility, visibility_source = manifest.visibility, "manifest_lock"
    return ResultEarV1(
        present=(d / "ear").is_dir(),
        curated=manifest.manifest_present,
        published=record.record_present,
        visibility=visibility,
        visibility_source=visibility_source,
        dry_run=record.dry_run,
        promoted_at=record.promoted_at,
    )


# ── query surface (one function per v1 resource) ───────────────────────────


def get_run_results(run_id: str) -> RunResultsV1 | dict:
    """GET /api/v1/runs/{run_id}/results."""
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return error_response(
            "not_found", f"unknown run: {run_id}", request_id="", status=404
        )
    degraded: list[str] = []
    return RunResultsV1(
        run_id=run_id,
        paper=_paper_block(d),
        review=_review_block(d, degraded),
        ors=_ors_block(d),
        ear=_ear_block(d, degraded),
        degraded_reasons=degraded,
    )


def get_run_ear(run_id: str) -> RunEarV1 | dict:
    """GET /api/v1/runs/{run_id}/ear — listing metadata + lineage scalars."""
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return error_response(
            "not_found", f"unknown run: {run_id}", request_id="", status=404
        )
    degraded: list[str] = []
    ear_dir = d / "ear"
    present = ear_dir.is_dir()

    files: list[EarFileV1] = []
    file_count = 0
    truncated = False
    if present:
        for f in sorted(ear_dir.rglob("*")):
            try:
                rel = str(f.relative_to(ear_dir))
            except ValueError:
                continue
            is_dir = f.is_dir()
            if not is_dir:
                file_count += 1
            if len(files) >= _MAX_EAR_FILES:
                truncated = True
                continue
            size: int | None = None
            if not is_dir:
                try:
                    size = f.stat().st_size
                except OSError:
                    degraded.append(f"stat failed for ear/{rel}")
            files.append(
                EarFileV1(path=rel, kind="dir" if is_dir else "file", size=size)
            )

    return RunEarV1(
        run_id=run_id,
        present=present,
        publish_yaml_present=(ear_dir / "publish.yaml").is_file(),
        files=files,
        file_count=file_count,
        truncated=truncated,
        curated=_manifest_block(d, degraded),
        published=_publish_record_block(d, degraded),
        degraded_reasons=degraded,
    )
