"""Deterministic failure injection (RQGM Task 13 §5.3/§7).

Two mechanisms, no LLM in either (P2):

- ``fixture`` — a crafted checkpoint fragment committed under
  ``ari-core/tests/fixtures/rqgm_eval/<payload_ref>/`` is copied into the
  target checkpoint (deterministic and idempotent: same spec ⇒ byte-identical
  files).
- ``scripted_component`` — a deterministic double (``doubles.py``) is
  substituted for one role via ``rqgm.eval.scripted_components``; no files
  are written by ``apply_injection``.

Any run with injections active carries ``rqgm_injection_provenance.json``
(the ``bfts_web_provenance.json`` precedent) so an injected trajectory can
never be mistaken for a real one. Injection ids live in the ``eval_*``
namespace, disjoint by construction from governance's ``adv_*`` replay cases
and ``anchor_*`` cases (the held-out-eval-set rule, enforced by
``spec_violations``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path

import yaml

from ari.rqgm.events import canonical_json

log = logging.getLogger(__name__)

INJECTION_PROVENANCE_FILENAME = "rqgm_injection_provenance.json"
INJECTION_PROVENANCE_SCHEMA_VERSION = 1
HARNESS_VERSION = 1

#: The eval namespace and the case namespaces it must stay disjoint from
#: (plan 13 §5.3: the eval set is held out from what governance trains on).
EVAL_ID_PREFIX = "eval_"
RESERVED_CASE_PREFIXES: tuple[str, ...] = ("adv_", "anchor_")

MECHANISMS: tuple[str, ...] = ("fixture", "scripted_component")
GROUND_TRUTH_LABELS: tuple[str, ...] = ("bad", "good")


def default_specs_path() -> Path:
    """``scripts/rqgm_eval/failure_injections.yaml`` at the repo root."""
    return (
        Path(__file__).resolve().parents[4]
        / "scripts" / "rqgm_eval" / "failure_injections.yaml"
    )


def fixtures_root() -> Path:
    """``ari-core/tests/fixtures/rqgm_eval/`` (fixture payload home)."""
    return (
        Path(__file__).resolve().parents[3]
        / "tests" / "fixtures" / "rqgm_eval"
    )


def load_injection_specs(path: "str | Path | None" = None) -> dict:
    """Parse ``failure_injections.yaml`` into
    ``{"injections": [...], "controls": [...], "paper_injections": [...]}``.

    ``paper_injections`` (paper-archive Task 07 §5.8, PI1-PI3) is additive and
    absence-tolerant — an old specs file without the key yields ``[]`` and the
    exploration ``injections``/``controls`` lists are byte-unchanged."""
    p = Path(path) if path is not None else default_specs_path()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "injections" not in data:
        raise ValueError(f"{p} has no `injections:` list")
    return {
        "injections": [dict(s) for s in data.get("injections") or ()],
        "controls": [dict(s) for s in data.get("controls") or ()],
        "paper_injections": [
            dict(s) for s in data.get("paper_injections") or ()
        ],
    }


def spec_violations(spec: dict) -> list[str]:
    """Deterministic FailureInjectionSpec checks (empty == valid)."""
    d = dict(spec or {})
    out: list[str] = []
    injection_id = str(d.get("injection_id") or "")
    if not injection_id.startswith(EVAL_ID_PREFIX):
        out.append(
            f"injection_id {injection_id!r} is outside the "
            f"{EVAL_ID_PREFIX}* namespace"
        )
    if injection_id.startswith(RESERVED_CASE_PREFIXES):
        out.append(
            f"injection_id {injection_id!r} collides with a reserved case "
            f"namespace {RESERVED_CASE_PREFIXES}"
        )
    mechanism = str(d.get("mechanism") or "")
    if mechanism not in MECHANISMS:
        out.append(f"mechanism {mechanism!r} is outside {MECHANISMS}")
    if str(d.get("ground_truth_label") or "") not in GROUND_TRUTH_LABELS:
        out.append(
            f"ground_truth_label {d.get('ground_truth_label')!r} is outside "
            f"{GROUND_TRUTH_LABELS}"
        )
    if mechanism == "fixture" and not str(d.get("payload_ref") or ""):
        out.append("fixture injection has no payload_ref")
    if mechanism == "scripted_component":
        if not str(d.get("target_role") or ""):
            out.append("scripted_component injection has no target_role")
        if not str(d.get("double") or ""):
            out.append("scripted_component injection names no double")
    expected = d.get("expected_detection")
    if not isinstance(expected, dict):
        out.append("expected_detection is missing")
    else:
        if not expected.get("channels"):
            out.append("expected_detection.channels is empty")
        try:
            int(expected.get("max_latency_epochs"))
        except (TypeError, ValueError):
            out.append("expected_detection.max_latency_epochs is not an int")
    if not str(d.get("min_condition") or ""):
        out.append("min_condition is missing")
    return out


def smoke_only_spec_ids(specs: list) -> list[str]:
    """Ids of ``scripted_component`` specs — smoke-tier only (plan 13 §5.3
    mechanism S).

    No production code path consumes ``rqgm.eval.scripted_components`` (the
    doubles registry is engaged only by the Tier-2 smoke runner), so a
    Tier-3 ``ari run`` handed such a spec would record a never-applied fault
    as active and corrupt the detection metrics (metric 4 would count it as
    ground-truth-bad). The harness refuses these outside ``--smoke``.
    """
    return sorted(
        str(s.get("injection_id") or "")
        for s in specs or ()
        if str(s.get("mechanism")) == "scripted_component"
    )


def _payload_dir(spec: dict) -> Path:
    """Resolve ``payload_ref`` against the committed fixture root. The
    ``fixtures/rqgm_eval/`` prefix of the plan's §6 example is accepted."""
    ref = str(spec.get("payload_ref") or "").strip("/")
    prefix = "fixtures/rqgm_eval/"
    if ref.startswith(prefix):
        ref = ref[len(prefix):]
    return fixtures_root() / ref


def apply_injection(spec: dict, checkpoint_dir: Path) -> list[str]:
    """Apply one injection to *checkpoint_dir* (deterministic, idempotent).

    ``fixture``: copy the committed payload fragment file-for-file into the
    checkpoint (stable sorted walk; re-application overwrites with identical
    bytes). ``scripted_component``: nothing to copy — the double is engaged
    via ``rqgm.eval.scripted_components`` config. Returns the
    checkpoint-relative paths written (sorted).
    """
    ckpt = Path(checkpoint_dir)
    mechanism = str((spec or {}).get("mechanism") or "")
    if mechanism == "scripted_component":
        return []
    if mechanism != "fixture":
        raise ValueError(f"unknown injection mechanism {mechanism!r}")
    payload = _payload_dir(spec)
    if not payload.is_dir():
        raise FileNotFoundError(
            f"fixture payload {payload} for "
            f"{spec.get('injection_id')!r} does not exist"
        )
    written: list[str] = []
    for src in sorted(p for p in payload.rglob("*") if p.is_file()):
        rel = src.relative_to(payload)
        dst = ckpt / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        written.append(str(rel))
    return sorted(written)


def specs_digest(specs: list) -> str:
    """hash12 of the canonical spec list (id-sorted; pure content)."""
    ordered = sorted(
        (dict(s) for s in specs or ()),
        key=lambda s: str(s.get("injection_id") or ""),
    )
    return hashlib.sha256(
        canonical_json(ordered).encode("utf-8")
    ).hexdigest()[:12]


def write_injection_provenance(checkpoint_dir: Path, specs: list) -> Path:
    """The durable synthetic-trajectory marker (plan 13 §6)."""
    payload = {
        "schema_version": INJECTION_PROVENANCE_SCHEMA_VERSION,
        "injection_ids": sorted(
            str(s.get("injection_id") or "") for s in specs or ()
        ),
        "specs_digest": specs_digest(specs),
        "harness_version": HARNESS_VERSION,
    }
    path = Path(checkpoint_dir) / INJECTION_PROVENANCE_FILENAME
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def read_injection_provenance(checkpoint_dir: Path) -> "dict | None":
    path = Path(checkpoint_dir) / INJECTION_PROVENANCE_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def gate_detection_report(checkpoint_dir: Path, *, phase: str = "final") -> dict:
    """Run the existing deterministic claim gate against an (injected)
    checkpoint fragment without touching disk (plan 13 §4:
    ``run_hard_gate(write=False)``) — the fixture-tier detection channel for
    injections 1 (metric gaming) and 2 (overclaim).

    Reads ``science_data.json`` / ``full_paper.tex`` /
    ``paper_claim_links.json`` from the checkpoint root; absence degrades to
    empty inputs (the gate itself is absence-tolerant).
    """
    from ari.pipeline.claim_gate.gate import run_hard_gate

    ckpt = Path(checkpoint_dir)
    science_data: dict = {}
    sd_path = ckpt / "science_data.json"
    if sd_path.is_file():
        try:
            loaded = json.loads(sd_path.read_text(encoding="utf-8"))
            science_data = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            science_data = {}
    paper_tex = ""
    tex_path = ckpt / "full_paper.tex"
    if tex_path.is_file():
        paper_tex = tex_path.read_text(encoding="utf-8", errors="replace")
    links = None
    links_path = ckpt / "paper_claim_links.json"
    if links_path.is_file():
        try:
            loaded = json.loads(links_path.read_text(encoding="utf-8"))
            links = loaded if isinstance(loaded, dict) else None
        except (OSError, json.JSONDecodeError):
            links = None
    return run_hard_gate(
        ckpt,
        paper_tex=paper_tex,
        science_data=science_data,
        paper_claim_links=links,
        phase=phase,
        write=False,
    )
