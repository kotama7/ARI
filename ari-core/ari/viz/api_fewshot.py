"""ARI viz: api_fewshot — manage reviewer_rubrics/fewshot_examples/ corpus.

Endpoints exposed by viz/server.py:

- GET    /api/fewshot/<rubric_id>            list examples for a rubric
- POST   /api/fewshot/<rubric_id>/sync       run scripts/fewshot/sync.py --venue <id>
- POST   /api/fewshot/<rubric_id>/upload     multipart: json + optional pdf / txt
- DELETE /api/fewshot/<rubric_id>/<example>  remove an example (all extensions)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import state as _st

log = logging.getLogger(__name__)


def _fewshot_root() -> Path:
    return _st._ari_root / "ari-core" / "config" / "reviewer_rubrics" / "fewshot_examples"


def _safe_rubric_id(rubric_id: str) -> str:
    """Prevent path traversal — rubric ids are alnum/underscore/hyphen only."""
    return "".join(c for c in rubric_id if c.isalnum() or c in ("_", "-"))


def _rubric_is_known(rubric_id: str) -> bool:
    """True only when a matching <rubric_id>.yaml exists in reviewer_rubrics/.

    Refuses to create a fewshot directory for a rubric the system does not know
    about — this blocks attackers who bypass _safe_rubric_id by supplying an
    alnum path like 'etc' from provisioning arbitrary directories under
    reviewer_rubrics/fewshot_examples/.
    """
    rid = _safe_rubric_id(rubric_id)
    if not rid:
        return False
    rubrics_dir = _st._ari_root / "ari-core" / "config" / "reviewer_rubrics"
    return (rubrics_dir / f"{rid}.yaml").exists() or (rubrics_dir / f"{rid}.yml").exists()


def _api_fewshot_list(rubric_id: str) -> dict:
    rid = _safe_rubric_id(rubric_id)
    if not rid:
        return {"error": "invalid rubric_id"}
    base = _fewshot_root() / rid
    if not base.exists():
        return {"rubric_id": rid, "count": 0, "examples": []}
    entries: dict[str, dict] = {}
    allowed_exts = {"json", "pdf", "txt"}
    for f in sorted(base.iterdir()):
        if f.is_dir() or f.name.startswith(".") or f.name == "README.md":
            continue
        ext = f.suffix.lstrip(".").lower()
        if ext not in allowed_exts:
            continue
        stem = f.stem
        ent = entries.setdefault(stem, {"id": stem, "files": [], "source": "", "decision": "", "overall": None})
        ent["files"].append({"ext": ext, "size": f.stat().st_size})
        if ext == "json":
            try:
                data = json.loads(f.read_text())
                ent["source"] = data.get("_source", "") or data.get("_paper", "")
                ent["decision"] = data.get("decision") or data.get("Decision", "")
                ent["overall"] = data.get("overall") or data.get("Overall")
            except Exception:
                pass
    # Only keep entries that have at least a .json (real few-shot examples)
    entries = {k: v for k, v in entries.items() if any(fd["ext"] == "json" for fd in v["files"])}
    return {
        "rubric_id": rid,
        "count": len(entries),
        "examples": sorted(entries.values(), key=lambda e: e["id"]),
    }


def _rubric_is_closed_review(rubric_id: str) -> bool:
    """True when the rubric YAML sets `closed_review: true` (e.g. SC, CHI)."""
    rid = _safe_rubric_id(rubric_id)
    if not rid:
        return False
    try:
        import yaml  # type: ignore
    except ImportError:
        return False
    rubrics_dir = _st._ari_root / "ari-core" / "config" / "reviewer_rubrics"
    for suffix in (".yaml", ".yml"):
        p = rubrics_dir / f"{rid}{suffix}"
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text()) or {}
                return bool(data.get("closed_review", False))
            except Exception:
                return False
    return False


def _api_fewshot_sync(rubric_id: str) -> dict:
    """Run scripts/fewshot/sync.py --venue <rubric_id> to pull manifest entries."""
    rid = _safe_rubric_id(rubric_id)
    if not rid:
        return {"error": "invalid rubric_id"}
    if not _rubric_is_known(rid):
        return {"error": f"unknown rubric '{rid}' (not found in reviewer_rubrics/)"}
    script = _st._ari_root / "scripts" / "fewshot" / "sync.py"
    if not script.exists():
        return {"error": f"sync script not found at {script}"}
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--venue", rid],
            capture_output=True, text=True, timeout=300,
        )
        result = {
            "rubric_id": rid,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "updated": _api_fewshot_list(rid)["examples"],
        }
        # Helpful hint: sync succeeded (rc=0) but no examples exist and the
        # venue is closed-review. The manifest is intentionally empty because
        # public reviews are unavailable — users must upload samples manually.
        if (
            proc.returncode == 0
            and not result["updated"]
            and _rubric_is_closed_review(rid)
        ):
            result["hint"] = (
                f"{rid} is a closed-review venue: no public reviews are available "
                "on OpenReview or similar. Please upload samples manually."
            )
        return result
    except subprocess.TimeoutExpired:
        return {"error": "sync timed out after 300s"}
    except Exception as e:
        return {"error": f"sync failed: {e}"}


def _api_fewshot_upload(rubric_id: str, body_fields: dict) -> dict:
    """Accept a multipart upload.

    `body_fields` is expected to be parsed by the caller into:
        {
          "example_id":  "<stem>",   # filename stem (alnum/_-)
          "review_json": "<raw str>", # required
          "paper_txt":   "<raw str>", # optional
          "paper_pdf":   <bytes>,     # optional
        }
    """
    rid = _safe_rubric_id(rubric_id)
    if not rid:
        return {"error": "invalid rubric_id"}
    if not _rubric_is_known(rid):
        return {"error": f"unknown rubric '{rid}' (not found in reviewer_rubrics/)"}
    eid = "".join(
        c for c in str(body_fields.get("example_id", "") or "") if c.isalnum() or c in ("_", "-")
    )
    if not eid:
        return {"error": "example_id required (alnum/_-)"}

    base = _fewshot_root() / rid
    base.mkdir(parents=True, exist_ok=True)

    review_raw = body_fields.get("review_json")
    if not review_raw:
        return {"error": "review_json required"}
    try:
        review_obj = json.loads(review_raw) if isinstance(review_raw, str) else review_raw
    except Exception as e:
        return {"error": f"review_json parse error: {e}"}
    if not isinstance(review_obj, dict):
        return {"error": "review_json must be a JSON object"}

    # Tag provenance so later operators know the example came via GUI upload
    review_obj.setdefault("_source", f"GUI upload (rubric={rid})")
    (base / f"{eid}.json").write_text(
        json.dumps(review_obj, ensure_ascii=False, indent=2)
    )

    if body_fields.get("paper_txt"):
        (base / f"{eid}.txt").write_text(str(body_fields["paper_txt"])[:40000])
    if body_fields.get("paper_pdf"):
        data = body_fields["paper_pdf"]
        if isinstance(data, str):
            import base64
            try:
                data = base64.b64decode(data)
            except Exception:
                data = data.encode("utf-8", errors="ignore")
        (base / f"{eid}.pdf").write_bytes(data)

    return {"ok": True, "rubric_id": rid, "example_id": eid, "listing": _api_fewshot_list(rid)}


def _api_fewshot_delete(rubric_id: str, example_id: str) -> dict:
    rid = _safe_rubric_id(rubric_id)
    eid = "".join(
        c for c in str(example_id) if c.isalnum() or c in ("_", "-")
    )
    if not rid or not eid:
        return {"error": "invalid rubric_id / example_id"}
    if not _rubric_is_known(rid):
        return {"error": f"unknown rubric '{rid}' (not found in reviewer_rubrics/)"}
    base = _fewshot_root() / rid
    if not base.exists():
        return {"error": "rubric directory does not exist"}
    removed = []
    for ext in ("json", "pdf", "txt", "md"):
        p = base / f"{eid}.{ext}"
        if p.exists():
            p.unlink()
            removed.append(p.name)
    return {"ok": True, "removed": removed, "listing": _api_fewshot_list(rid)}
