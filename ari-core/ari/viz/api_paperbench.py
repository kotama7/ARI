"""PaperBench GUI API (v0.7.2 / PLAN_GUI_PAPERBENCH).

Endpoints powering the React-side **paper registry + PaperBench run wizard**:

  - GET    /api/paperbench/papers                      → list registered papers
  - POST   /api/paperbench/papers/import               → register a new paper
  - DELETE /api/paperbench/papers/<paper_id>           → unregister a paper
  - POST   /api/paperbench/papers/<paper_id>/metadata  → patch metadata
  - GET    /api/paperbench/papers/<paper_id>/license   → license classification
  - POST   /api/paperbench/run                         → enqueue PaperBench runs
  - GET    /api/paperbench/run/<job_id>                → run status snapshot
  - GET    /api/paperbench/run/<job_id>/results        → finished run results
  - GET    /api/paperbench/cost-estimate               → dry-run cost estimate

The on-disk layout for the registry mirrors PLAN_GUI_PAPERBENCH §5.1::

    {ARI_PAPER_REGISTRY_DIR or PathManager.paper_registry_root}/
    ├── manifest.jsonl                       # one paper per line
    └── papers/
        └── <paper_id>/
            ├── paper.pdf                    # required
            ├── ad.pdf                       # optional (artifact description)
            └── ae.pdf                       # optional (artifact evaluation)

Each ``manifest.jsonl`` line is a single JSON object with at minimum
``paper_id``, ``title``, ``license``, ``imported_at`` and ``source``
(``"doi"`` | ``"arxiv"`` | ``"upload"``). The actual schema is loose so the
frontend can stash additional fields (artifact_url, venue, year, authors)
without a schema migration.

License classification (``_classify_license``) maps a free-form license
string (typically scraped from arXiv's abs page or filled in by the user
during import) onto a structured ``{permissive, modifiable, redistributable,
note}`` quad so the import dialog can show "✅ usable" / "⚠️ NOT usable"
guidance. Only **permissive AND redistributable** licenses are auto-
approved; everything else is treated as a warning, not a hard block —
authoritative legal review is out of scope for this code.

PaperBench runs are launched in-process by spawning a worker thread that
shells out to the existing CLI ``ari run``. Job state is kept in an
in-memory dict keyed by ``job_id``; restart of the viz server forgets
historical jobs (they remain reproducible by re-launching from the
wizard).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ── on-disk registry helpers ──────────────────────────────────────────────


def _registry_root() -> Path:
    """Resolve the paper registry directory.

    Precedence: ``ARI_PAPER_REGISTRY_DIR`` env var →
    ``PathManager.paper_registry_root`` (a workspace-rooted directory,
    typically ``./paper_registry``). v0.5+ ARI no longer maintains a
    global per-user data directory; the central PathManager keeps the
    on-disk layout enforceable from one place.
    Created lazily on first write.
    """
    explicit = os.environ.get("ARI_PAPER_REGISTRY_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    from ari.paths import PathManager  # local import to avoid cycle
    return PathManager.from_env().paper_registry_root.resolve()


def _manifest_path() -> Path:
    return _registry_root() / "manifest.jsonl"


def _papers_dir() -> Path:
    return _registry_root() / "papers"


def _ensure_registry() -> None:
    root = _registry_root()
    root.mkdir(parents=True, exist_ok=True)
    _papers_dir().mkdir(parents=True, exist_ok=True)
    mp = _manifest_path()
    if not mp.exists():
        mp.touch()


def _read_manifest() -> list[dict]:
    """Return the manifest as a list of dicts (one entry per line)."""
    mp = _manifest_path()
    if not mp.is_file():
        return []
    out: list[dict] = []
    for line in mp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("skipping malformed manifest line: %s", line[:100])
    return out


def _write_manifest(entries: list[dict]) -> None:
    """Rewrite the manifest with the given entries (one JSON object per line)."""
    _ensure_registry()
    mp = _manifest_path()
    tmp = mp.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(mp)


# ── license classification ────────────────────────────────────────────────


_PERMISSIVE_LICENSES = {
    "cc0", "cc0 1.0", "cc-0", "public domain",
    "cc by", "cc by 4.0", "cc-by", "cc-by-4.0",
    "cc by-sa", "cc by-sa 4.0", "cc-by-sa", "cc-by-sa-4.0",
    "cc by-nc", "cc by-nc 4.0", "cc-by-nc", "cc-by-nc-4.0",  # research-only
    "mit", "apache-2.0", "apache 2.0", "bsd-3-clause", "bsd-2-clause",
    "arxiv non-exclusive",  # arXiv default
}
_PERMISSIVE_AND_MODIFIABLE = {
    "cc0", "cc0 1.0", "cc-0", "public domain",
    "cc by", "cc by 4.0", "cc-by", "cc-by-4.0",
    "cc by-sa", "cc by-sa 4.0", "cc-by-sa", "cc-by-sa-4.0",
    "mit", "apache-2.0", "apache 2.0", "bsd-3-clause", "bsd-2-clause",
}
_PERMISSIVE_AND_REDISTRIBUTABLE = _PERMISSIVE_AND_MODIFIABLE | {
    "arxiv non-exclusive",
}

# CC BY-NC is non-commercial: PLAN_GUI_PAPERBENCH §8#3 mandates a
# "NOT usable" warning for this class. The license is still permissive
# in the sense that academic redistribution is allowed, but ARI may be
# used commercially downstream so we conservatively flag it as
# non-usable rather than re-distributable.
_NON_COMMERCIAL_LICENSES = {
    "cc by-nc", "cc by-nc 4.0", "cc-by-nc", "cc-by-nc-4.0",
}


def _classify_license(raw: str | None) -> dict:
    """Return a structured assessment of a free-form license string.

    The returned dict matches the JSON shape consumed by
    ``PaperImportDialog`` to colour the "license" badge:

        {
            "license": "<canonical lower-case form>",
            "permissive": bool,
            "modifiable": bool,            # can we tweak the text?
            "redistributable": bool,        # can ari re-host an excerpt?
            "usable": bool,                 # permissive AND redistributable
            "note": str,
        }
    """
    if not raw:
        return {
            "license": "",
            "permissive": False,
            "modifiable": False,
            "redistributable": False,
            "usable": False,
            "note": "license unknown — manual review required",
        }
    norm = raw.strip().lower()
    permissive = norm in _PERMISSIVE_LICENSES
    modifiable = norm in _PERMISSIVE_AND_MODIFIABLE
    redistributable = norm in _PERMISSIVE_AND_REDISTRIBUTABLE
    non_commercial = norm in _NON_COMMERCIAL_LICENSES
    usable = permissive and redistributable and not non_commercial
    if non_commercial:
        note = "non-commercial ⚠ NOT usable — CC BY-NC restricts commercial reuse"
    elif usable:
        note = "permissive license — ari may use freely"
    elif permissive:
        note = "permissive but with restrictions — review before re-hosting"
    else:
        note = "non-permissive — NOT usable for ari without explicit permission"
    return {
        "license": norm,
        "permissive": permissive,
        "modifiable": modifiable,
        "redistributable": redistributable,
        "usable": usable,
        "note": note,
    }


# ── paper_id allocation ──────────────────────────────────────────────────


_PAPER_ID_PAT = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _normalize_paper_id(raw: str) -> str:
    """Sanitize a paper_id so it is filesystem-safe AND URL-safe.

    Accept ``[A-Za-z0-9._-]`` only; anything else → ``-``. Truncate to 64
    chars. Empty input becomes a random UUID4 hex slice.
    """
    if not raw:
        return uuid.uuid4().hex[:12]
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", raw)[:64]
    return cleaned or uuid.uuid4().hex[:12]


# ── arXiv metadata auto-fetch ────────────────────────────────────────────


_ARXIV_API = "https://export.arxiv.org/api/query"
_ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_ARXIV_ID_PAT = re.compile(
    r"^(?:arxiv:)?(?P<id>(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}))$",
    re.IGNORECASE,
)


def _normalize_arxiv_id(raw: str) -> str | None:
    """Return a canonical arXiv ID (no version suffix) or ``None`` on a non-match.

    Accepts both new-style (``2404.14193``, ``2404.14193v2``) and legacy
    (``cs.LG/0102030``) identifiers; also tolerates a leading ``arxiv:``
    scheme that some users paste.
    """
    if not raw:
        return None
    candidate = raw.strip()
    # Strip trailing version suffix; the arXiv search API resolves the
    # canonical metadata without it.
    m = _ARXIV_ID_PAT.match(candidate)
    if not m:
        return None
    aid = m.group("id")
    return re.sub(r"v\d+$", "", aid, flags=re.IGNORECASE)


def _api_arxiv_fetch(arxiv_id: str, *, timeout: float = 6.0) -> dict:
    """Fetch metadata from the public arXiv Atom API for a single paper.

    Returns a dict with ``title``, ``authors``, ``year``, ``license``,
    ``artifact_url``, ``pdf_url``, ``summary``. Network failures /
    non-200 responses return ``{"error": "..."}``. arXiv default license
    is the non-exclusive distribution licence (a permissive but
    non-commercial-modification arrangement) — we report it as
    ``"arXiv non-exclusive"`` and let ``_classify_license`` classify it
    as ``usable`` for ARI's purposes.
    """
    aid = _normalize_arxiv_id(arxiv_id)
    if not aid:
        return {"error": f"not a valid arXiv id: {arxiv_id!r}"}
    url = f"{_ARXIV_API}?{urllib.parse.urlencode({'id_list': aid})}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return {"error": f"arXiv API returned HTTP {resp.status}"}
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"error": f"arXiv fetch failed: {e}"}

    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        return {"error": f"arXiv response is not valid XML: {e}"}

    entries = root.findall("atom:entry", _ARXIV_NS)
    if not entries:
        return {"error": f"no arXiv entry for id {aid}"}
    entry = entries[0]

    def _text(tag: str) -> str:
        el = entry.find(tag, _ARXIV_NS)
        return (el.text or "").strip() if el is not None and el.text else ""

    title = re.sub(r"\s+", " ", _text("atom:title")).strip()
    summary = re.sub(r"\s+", " ", _text("atom:summary")).strip()
    published = _text("atom:published")
    year = None
    if len(published) >= 4 and published[:4].isdigit():
        year = int(published[:4])

    authors: list[str] = []
    for a in entry.findall("atom:author", _ARXIV_NS):
        name = a.find("atom:name", _ARXIV_NS)
        if name is not None and name.text:
            authors.append(name.text.strip())

    # PDF link is one of the <link> entries with title="pdf".
    pdf_url = ""
    for link in entry.findall("atom:link", _ARXIV_NS):
        if link.get("title") == "pdf":
            pdf_url = link.get("href") or ""
            break

    return {
        "arxiv_id": aid,
        "title": title,
        "authors": authors,
        "year": year,
        "license": "arXiv non-exclusive",
        "license_assessment": _classify_license("arXiv non-exclusive"),
        "summary": summary[:1000],  # cap for response size
        "pdf_url": pdf_url,
        "abs_url": f"https://arxiv.org/abs/{aid}",
    }


# ── GET /api/paperbench/papers ───────────────────────────────────────────


def _api_list_papers() -> dict:
    """Return the current registry as ``{"papers": [...]}``."""
    return {"papers": _read_manifest()}


# ── POST /api/paperbench/papers/import ───────────────────────────────────


def _api_import_paper(body: dict) -> dict:
    """Register a new paper. Returns the manifest entry on success.

    Required body keys:
      - ``source_type``: ``"doi"`` | ``"arxiv"`` | ``"upload"`` | ``"local"``
      - ``source``: the DOI / arXiv id / file path / pre-existing identifier
      - ``title``: paper title (free-form)
      - ``license``: free-form license string (will be classified)

    Optional:
      - ``authors``: list of strings
      - ``venue``: conference / journal name
      - ``year``: int
      - ``artifact_url``: code repo URL
      - ``paper_id``: explicit override (will be sanitized)
      - ``pdf_path``: absolute path to a local PDF (copied into the registry)
      - ``ad_pdf_path`` / ``ae_pdf_path``: optional AD/AE appendices

    Duplicate detection is by ``paper_id``; collisions return
    ``{"error": "...","paper_id": "..."}``. The caller can re-POST with
    ``overwrite=True`` to replace.
    """
    if not isinstance(body, dict):
        return {"error": "body must be an object"}
    source_type = (body.get("source_type") or "").strip().lower()
    if source_type not in {"doi", "arxiv", "upload", "local"}:
        return {"error": "source_type must be one of: doi, arxiv, upload, local"}
    source = (body.get("source") or "").strip()
    title = (body.get("title") or "").strip()
    if not source:
        return {"error": "source is required"}
    if not title:
        return {"error": "title is required"}

    raw_id = body.get("paper_id") or source
    paper_id = _normalize_paper_id(raw_id)
    overwrite = bool(body.get("overwrite", False))

    entries = _read_manifest()
    existing = {e["paper_id"]: i for i, e in enumerate(entries) if "paper_id" in e}
    if paper_id in existing and not overwrite:
        return {
            "error": f"paper_id already registered: {paper_id}",
            "paper_id": paper_id,
            "existing": entries[existing[paper_id]],
        }

    _ensure_registry()
    paper_dir = _papers_dir() / paper_id
    paper_dir.mkdir(parents=True, exist_ok=True)

    # Materialize attached PDFs (callers pass paths from /api/upload tmp).
    pdf_path = body.get("pdf_path")
    if pdf_path:
        try:
            shutil.copy2(Path(pdf_path).expanduser(), paper_dir / "paper.pdf")
        except OSError as e:
            return {"error": f"could not copy paper PDF: {e}"}
    ad = body.get("ad_pdf_path")
    if ad:
        try:
            shutil.copy2(Path(ad).expanduser(), paper_dir / "ad.pdf")
        except OSError as e:
            log.warning("could not copy AD PDF: %s", e)
    ae = body.get("ae_pdf_path")
    if ae:
        try:
            shutil.copy2(Path(ae).expanduser(), paper_dir / "ae.pdf")
        except OSError as e:
            log.warning("could not copy AE PDF: %s", e)

    license_info = _classify_license(body.get("license"))
    entry = {
        "paper_id": paper_id,
        "title": title,
        "authors": list(body.get("authors") or []),
        "venue": body.get("venue", ""),
        "year": int(body.get("year") or 0) or None,
        "source_type": source_type,
        "source": source,
        "artifact_url": body.get("artifact_url", ""),
        "license": license_info["license"],
        "license_assessment": license_info,
        "imported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "registry_dir": str(paper_dir),
    }
    if paper_id in existing:
        entries[existing[paper_id]] = entry  # overwrite
    else:
        entries.append(entry)
    _write_manifest(entries)
    return entry


# ── DELETE /api/paperbench/papers/<paper_id> ─────────────────────────────


def _api_delete_paper(paper_id: str) -> dict:
    """Drop the manifest entry and the paper directory.

    Idempotent: returns ``{"deleted": False, "reason": "not found"}`` when
    the id is unknown.
    """
    paper_id = _normalize_paper_id(paper_id)
    entries = _read_manifest()
    remaining = [e for e in entries if e.get("paper_id") != paper_id]
    if len(remaining) == len(entries):
        return {"deleted": False, "reason": "not found", "paper_id": paper_id}
    _write_manifest(remaining)
    paper_dir = _papers_dir() / paper_id
    if paper_dir.is_dir():
        shutil.rmtree(paper_dir, ignore_errors=True)
    return {"deleted": True, "paper_id": paper_id}


# ── POST /api/paperbench/papers/<paper_id>/metadata ──────────────────────


def _api_patch_paper_metadata(paper_id: str, body: dict) -> dict:
    """Merge ``body`` into the existing manifest entry."""
    paper_id = _normalize_paper_id(paper_id)
    if not isinstance(body, dict):
        return {"error": "body must be an object"}
    entries = _read_manifest()
    for i, e in enumerate(entries):
        if e.get("paper_id") == paper_id:
            # Re-classify license if changed
            if "license" in body:
                body["license_assessment"] = _classify_license(body["license"])
                body["license"] = (body["license"] or "").strip().lower()
            e.update(body)
            e["paper_id"] = paper_id  # paper_id is immutable
            entries[i] = e
            _write_manifest(entries)
            return e
    return {"error": "paper not found", "paper_id": paper_id}


# ── GET /api/paperbench/papers/<paper_id>/license ────────────────────────


def _api_paper_license(paper_id: str) -> dict:
    paper_id = _normalize_paper_id(paper_id)
    for e in _read_manifest():
        if e.get("paper_id") == paper_id:
            return e.get("license_assessment") or _classify_license(e.get("license"))
    return {"error": "paper not found", "paper_id": paper_id}


# ── POST /api/paperbench/run ────────────────────────────────────────────


# In-memory job table. Each entry: ``{job_id, paper_id, status, ...}``.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def _job_snapshot(job_id: str) -> dict:
    with _JOBS_LOCK:
        return dict(_JOBS.get(job_id, {}))


def _set_job_field(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(fields)


def _new_job(paper_id: str, configs: dict) -> dict:
    job_id = uuid.uuid4().hex
    entry = {
        "job_id": job_id,
        "paper_id": paper_id,
        "status": "queued",
        "current_stage": None,
        "progress": 0.0,
        "configs": configs,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": None,
        "error": None,
        "logs": [],  # list[dict]: {ts, level, msg}
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = entry
    return entry


def append_job_log(job_id: str, msg: str, *, level: str = "info") -> None:
    """Append one structured log line to a job's in-memory log buffer.

    Designed to be called by the background worker driving the actual
    PaperBench rollout. The SSE endpoint
    (``/api/paperbench/run/<job_id>/logs``) re-emits these entries to
    connected browsers. Buffer is capped at 2000 entries per job to
    bound memory.
    """
    with _JOBS_LOCK:
        if job_id not in _JOBS:
            return
        buf = _JOBS[job_id].setdefault("logs", [])
        buf.append({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z",
            "level": level,
            "msg": str(msg),
        })
        if len(buf) > 2000:
            del buf[: len(buf) - 2000]


def _job_logs_since(job_id: str, since: int = 0) -> list[dict]:
    """Return the slice of a job's log buffer starting at index ``since``.

    Used by the SSE handler to resume after a reconnect (the browser sends
    ``Last-Event-ID`` carrying the highest index it already saw).
    """
    with _JOBS_LOCK:
        buf = list(_JOBS.get(job_id, {}).get("logs") or [])
    return buf[since:]


def _estimate_cost(rubric_config: dict, reproduce_config: dict, judge_config: dict) -> dict:
    """Crude wall-time + LLM-cost estimate for dry-run mode.

    Values are derived from PaperBench paper §5.2 / §5.3 defaults:
      - rubric gen: ~2-5 min per paper (gpt-5-class models)
      - reproduce: ``reproduce_config.time_limit_sec`` (caller-controlled)
      - judge: ~1 min × n_runs

    Cost is a back-of-the-envelope estimate (assumes ~50K tokens in / 5K
    tokens out per rubric pass; ~$1/M input + $5/M output). Tune as
    needed — these are advisory.
    """
    rubric_two_stage = bool(rubric_config.get("two_stage", True))
    rubric_walltime = 300 if rubric_two_stage else 180  # sec
    rubric_cost_usd = 0.45 if rubric_two_stage else 0.20

    reproduce_walltime = int(reproduce_config.get("time_limit_sec") or 12 * 3600)
    reproduce_cost_usd = 2.0  # ballpark for a 12 h BasicAgent rollout

    judge_n_runs = int(judge_config.get("n_runs") or 1)
    judge_walltime = 60 * judge_n_runs
    judge_cost_usd = 0.10 * judge_n_runs

    return {
        "wall_time_sec": rubric_walltime + reproduce_walltime + judge_walltime,
        "llm_cost_usd": round(rubric_cost_usd + reproduce_cost_usd + judge_cost_usd, 2),
        "breakdown": {
            "rubric": {"wall_time_sec": rubric_walltime, "cost_usd": rubric_cost_usd},
            "reproduce": {"wall_time_sec": reproduce_walltime, "cost_usd": reproduce_cost_usd},
            "judge": {"wall_time_sec": judge_walltime, "cost_usd": judge_cost_usd},
        },
    }


def _api_launch_run(body: dict) -> dict:
    """Enqueue PaperBench runs for the supplied paper_ids.

    Body shape::

        {
          "paper_ids": ["sc24-00018", ...],          # >=1 required
          "rubric_config":     {...},                # forwarded to skill
          "reproduce_config":  {                     # also carries the
              "execution_profile_override": {...}    # 16 SLURM args (T8 spec)
          },
          "judge_config":      {...},
          "dry_run": false                           # estimate only
        }

    Returns ``{"job_ids": [...], "estimated_cost": {...}, "dry_run": bool}``
    when not a dry run; ``{"dry_run": true, "estimated_cost": {...}}`` when
    just estimating.
    """
    if not isinstance(body, dict):
        return {"error": "body must be an object"}
    paper_ids = body.get("paper_ids") or []
    if not isinstance(paper_ids, list) or not paper_ids:
        return {"error": "paper_ids must be a non-empty list"}
    rubric_config = dict(body.get("rubric_config") or {})
    reproduce_config = dict(body.get("reproduce_config") or {})
    judge_config = dict(body.get("judge_config") or {})
    dry_run = bool(body.get("dry_run"))

    est = _estimate_cost(rubric_config, reproduce_config, judge_config)

    if dry_run:
        return {
            "dry_run": True,
            "estimated_cost": est,
            "papers": len(paper_ids),
            "estimated_total_walltime_sec": est["wall_time_sec"] * len(paper_ids),
            "estimated_total_cost_usd": round(est["llm_cost_usd"] * len(paper_ids), 2),
        }

    # Persist a job per paper. Background execution is the caller's
    # responsibility (typically the existing CLI workflow runner); the API
    # just records intent.
    job_ids: list[str] = []
    registered = {e["paper_id"] for e in _read_manifest()}
    for pid in paper_ids:
        pid_norm = _normalize_paper_id(str(pid))
        if pid_norm not in registered:
            return {"error": f"paper not in registry: {pid_norm}"}
        entry = _new_job(
            paper_id=pid_norm,
            configs={
                "rubric": rubric_config,
                "reproduce": reproduce_config,
                "judge": judge_config,
            },
        )
        job_ids.append(entry["job_id"])
    return {
        "dry_run": False,
        "job_ids": job_ids,
        "estimated_cost": est,
    }


# ── GET /api/paperbench/run/<job_id> ────────────────────────────────────


def _api_run_status(job_id: str) -> dict:
    snap = _job_snapshot(job_id)
    if not snap:
        return {"error": "job not found", "job_id": job_id}
    return snap


# ── GET /api/paperbench/run/<job_id>/results ────────────────────────────


def _api_run_results(job_id: str) -> dict:
    snap = _job_snapshot(job_id)
    if not snap:
        return {"error": "job not found", "job_id": job_id}
    if snap.get("status") != "completed":
        return {"error": "results not available", "status": snap.get("status")}
    return snap.get("results") or {}


# ── GET /api/paperbench/cost-estimate ────────────────────────────────────


def _api_cost_estimate(query: dict) -> dict:
    """Same shape as ``_api_launch_run`` with ``dry_run=True``, but exposed
    as GET for the wizard's live-update path."""
    return _estimate_cost(
        rubric_config=query.get("rubric_config") or {},
        reproduce_config=query.get("reproduce_config") or {},
        judge_config=query.get("judge_config") or {},
    )


# ── GET /api/paperbench/run/<job_id>/report ──────────────────────────────


def _api_run_report(job_id: str, query: dict | None = None) -> dict:
    """Trigger / fetch an audit report for a completed job.

    Query (POST body or URL query):
      - languages:  list[str], default ``["en"]`` (subset of ``en``/``ja``/``zh``)
      - formats:    list[str], default ``["pdf", "html", "md"]``
      - output_root: optional override; defaults to
        ``{registry_root}/reports/<job_id>``

    Returns the renderer result ({status, languages, paths, harvest})
    plus a ``download_urls`` dict mapping ``<lang>/<fmt>`` → path.
    """
    query = dict(query or {})
    snap = _job_snapshot(job_id)
    if not snap:
        return {"error": "job not found", "job_id": job_id}
    if snap.get("status") != "completed":
        return {
            "error": "report not available until job completes",
            "status": snap.get("status"),
            "job_id": job_id,
        }

    languages = query.get("languages") or ["en"]
    formats = query.get("formats") or ["pdf", "html", "md"]
    output_root = (
        Path(query["output_root"]).expanduser().resolve()
        if query.get("output_root")
        else _registry_root() / "reports" / job_id
    )

    # Lazy import so the viz server stays loadable when the report scripts
    # are absent (e.g. minimal containers without the ``report/`` tree).
    import importlib.util
    import sys
    repo_root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "_paperbench_report_runtime",
        repo_root / "report" / "scripts" / "paperbench_report.py",
    )
    if spec is None or spec.loader is None:
        return {"error": "report/scripts/paperbench_report.py not found"}
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_paperbench_report_runtime", mod)
    spec.loader.exec_module(mod)

    # The job's checkpoint dir lives wherever the launcher placed it.
    checkpoint_dir = snap.get("checkpoint_dir") or snap.get("repo_dir")
    if not checkpoint_dir:
        return {
            "error": "job snapshot lacks checkpoint_dir; cannot render report",
            "job_id": job_id,
        }

    paper_id = snap.get("paper_id") or job_id
    res = mod.generate_paper_report(
        checkpoint_dir=Path(checkpoint_dir),
        paper_id=paper_id,
        output_root=output_root,
        languages=list(languages),
        formats=list(formats),
    )
    if res.get("status") != "ok":
        return res

    # Build download URLs: ``<output_root>/<lang>/main.<ext>``
    download_urls: dict[str, str] = {}
    for lang in languages:
        lang_dir = output_root / lang
        for fmt, fname in (
            ("pdf", "build/main.pdf"),
            ("html", "main.html"),
            ("md", "main.md"),
            ("tex", "main.tex"),
        ):
            target = lang_dir / fname
            if target.is_file():
                download_urls[f"{lang}/{fmt}"] = str(target)

    res["download_urls"] = download_urls
    res["job_id"] = job_id
    return res


__all__ = [
    "_classify_license",
    "_normalize_paper_id",
    "_registry_root",
    "_manifest_path",
    "_papers_dir",
    "_read_manifest",
    "_write_manifest",
    "_api_list_papers",
    "_api_import_paper",
    "_api_delete_paper",
    "_api_patch_paper_metadata",
    "_api_paper_license",
    "_api_launch_run",
    "_api_run_status",
    "_api_run_results",
    "_api_cost_estimate",
    "_api_run_report",
    "_api_arxiv_fetch",
    "_normalize_arxiv_id",
    "append_job_log",
    "_job_logs_since",
]
