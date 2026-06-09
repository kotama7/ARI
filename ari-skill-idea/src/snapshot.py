"""ari-skill-idea — Semantic Scholar live-snapshot builder for the VirSci wrap.

Builds a single *live* snapshot (no era split — see PLAN §0.1) that grounds
VirSci's real deliberation engine:

  - corpus       : topic papers from S2 (title/abstract/year/citation/authors),
                   each with its pre-computed ``embedding.specter_v2`` vector.
  - SPECTER2 idx : a faiss-cpu cosine index (IndexFlatIP over L2-normalised
                   vectors) over the corpus — the retrieval source for
                   ``LivePlatform.reference_paper``. Papers missing an embedding
                   are kept for keyword fallback but excluded from the index.
  - authors      : per-author profile text (``books/author_<i>.txt``) built from
                   each seed author's representative papers — the *diversity*
                   source consumed as SciAgent ``sys_prompt``.
  - adjacency    : a symmetric integer co-author matrix (``adjacency.txt``,
                   np.loadtxt(dtype=int)-compatible) — the *freshness* source
                   consumed by ``Platform.select_coauthors``.

Everything is frozen under ``<out_dir>/virsci_snapshot/`` with a
``snapshot_manifest.json`` so a run is reproducible and not subject to S2 live
drift. A re-build with a matching manifest reuses the frozen artifacts.

Vendor under ``vendor/virsci`` is never touched — this module only produces the
files/objects ``LivePlatform`` (see ``virsci_runtime.py``) loads.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import requests

S2_BASE = "https://api.semanticscholar.org/graph/v1"
# embedding.specter_v2 → S2's pre-computed SPECTER2 vector (≈768-dim); free.
_CORPUS_FIELDS = "title,abstract,year,citationCount,authors,embedding.specter_v2"
_AUTHOR_PAPER_FIELDS = "title,abstract,year"

log = logging.getLogger(__name__)


def _s2_api_key() -> str:
    return os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "") or os.environ.get("S2_API_KEY", "")


def _s2_headers() -> dict:
    key = _s2_api_key()
    return {"x-api-key": key} if key else {}


def _s2_get(path: str, params: dict, *, timeout: int = 20, retries: int = 4) -> dict | None:
    """GET an S2 endpoint with exponential backoff on 429/5xx."""
    url = f"{S2_BASE}/{path.lstrip('/')}"
    delay = 1.0
    last_err = ""
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=_s2_headers(), timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"status {r.status_code}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = str(e)
            if attempt == retries - 1:
                # Surface the failure instead of swallowing it silently: a 429
                # rate-limit here is exactly what produced an ungrounded 0-paper
                # snapshot, and a silent None left no trace in the logs.
                log.warning(
                    "S2 GET %s failed after %d attempt(s) (%s); returning None",
                    path, retries, last_err,
                )
                return None
            time.sleep(delay)
            delay = min(delay * 2, 16.0)
    return None


def _s2_post(path: str, json_body: dict, params: dict, *, timeout: int = 30, retries: int = 4) -> Any:
    url = f"{S2_BASE}/{path.lstrip('/')}"
    delay = 1.0
    for attempt in range(retries):
        try:
            r = requests.post(url, params=params, json=json_body, headers=_s2_headers(), timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"status {r.status_code}")
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(delay)
            delay = min(delay * 2, 16.0)
    return None


@dataclass
class Snapshot:
    """Frozen, reproducible S2 snapshot consumed by ``LivePlatform``."""

    dir: Path
    n_authors: int
    n_papers: int
    specter2_dim: int
    # corpus[i] aligns with row i of the faiss index (indexed papers only)
    corpus: list[dict] = field(default_factory=list)
    # full paper_dicts (incl. embedding-less) for vendor ``paper_dicts`` compat
    paper_dicts: list[dict] = field(default_factory=list)
    embeddings: np.ndarray | None = None  # (n_indexed, dim), L2-normalised
    topic: str = ""

    @property
    def books_dir(self) -> Path:
        return self.dir / "books"

    @property
    def adjacency_path(self) -> Path:
        return self.dir / "adjacency.txt"

    @property
    def papers_dir(self) -> Path:
        return self.dir / "papers"

    @property
    def index_path(self) -> Path:
        return self.dir / "specter2_index.npy"

    def build_faiss_index(self):
        """Build the in-memory faiss IndexFlatIP (cosine via normalised IP)."""
        import faiss

        if self.embeddings is None or len(self.embeddings) == 0:
            return None
        index = faiss.IndexFlatIP(self.specter2_dim)
        index.add(self.embeddings.astype("float32"))
        return index


def _norm_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "topic"


def _condense_query(topic: str) -> str:
    """Reduce a free-text experiment description to a short KEYWORD query for S2.

    ``/paper/search`` is a keyword endpoint: passing the whole multi-sentence
    description (incl. a ``Metrics: ...`` tail) returns 0 hits even with a valid API
    key, which silently degraded the VirSci snapshot to an ungrounded re-impl run.
    Take the first clause (before ``;`` / ``.`` / ``Metrics:``), drop parentheticals,
    and keep the leading keywords. Empty -> a short prefix of the original.
    """
    import re as _re
    t = topic.split("Metrics:")[0]
    t = _re.split(r"[.;:\n]", t, 1)[0]          # first clause only
    t = _re.sub(r"\([^)]*\)", " ", t)            # drop parentheticals e.g. "(SpMM)"
    words = _re.findall(r"[A-Za-z][A-Za-z0-9+\-]*", t)
    return " ".join(words[:10]) or (topic.strip()[:80])


def _fetch_corpus(topic: str, n_papers: int) -> list[dict]:
    """Fetch up to ``n_papers`` topic papers with SPECTER2 vectors.

    Uses paginated ``/paper/search`` (≤100/page, offset≤1000), requesting the
    embedding inline. Papers without ``embedding.specter_v2`` are still returned
    (kept for keyword fallback, excluded from the index downstream). The free-text
    topic is condensed to a keyword query first (a full description returns 0 hits).
    """
    papers: list[dict] = []
    seen: set[str] = set()
    page = 100
    query = _condense_query(topic)
    for offset in range(0, min(n_papers, 1000), page):
        limit = min(page, n_papers - offset)
        data = _s2_get(
            "paper/search",
            {"query": query, "offset": offset, "limit": limit, "fields": _CORPUS_FIELDS},
        )
        if not data:
            break
        batch = data.get("data") or []
        for p in batch:
            pid = p.get("paperId")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            papers.append(p)
        if not data.get("next"):
            break
    return papers


def _fetch_corpus_by_ids(paper_ids: list[str]) -> list[dict]:
    """Fetch full corpus records for known paperIds via ``/paper/batch``.

    Fallback for when the topic ``/paper/search`` returns nothing (e.g. a 429
    rate-limit or a sparse query): the already-vetted survey paperIds are
    fetched directly with the same corpus fields (incl. ``embedding.specter_v2``
    and ``authors``). ``/paper/batch`` is keyed by id so it is both more
    targeted and less likely to be throttled than relevance search.
    """
    ids = [pid for pid in paper_ids if pid]
    if not ids:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for i in range(0, len(ids), 500):  # /paper/batch accepts ≤500 ids/call
        data = _s2_post(
            "paper/batch",
            {"ids": ids[i:i + 500]},
            {"fields": _CORPUS_FIELDS},
        )
        if not data:
            continue
        for p in data:  # batch returns a list aligned to ids; null for misses
            if not p:
                continue
            pid = p.get("paperId")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            out.append(p)
    return out


def _build_adjacency(authors: list[dict]) -> np.ndarray:
    """Symmetric int co-author matrix with +1 Laplacian smoothing.

    ``adjacency[i][j]`` = (#shared papers between author i and j) + 1 baseline,
    diagonal 0. The +1 baseline guarantees no zero-rows so
    ``Platform.select_coauthors``'s ``arr / sum(arr)`` is always well-defined,
    while real co-authorship still biases the freshness sampling.
    """
    n = len(authors)
    paper_sets = [set(a.get("paper_ids") or []) for a in authors]
    adj = np.ones((n, n), dtype=int)  # +1 baseline
    np.fill_diagonal(adj, 0)
    for i in range(n):
        for j in range(i + 1, n):
            shared = len(paper_sets[i] & paper_sets[j])
            if shared:
                adj[i, j] += shared
                adj[j, i] += shared
    return adj


def _select_authors(corpus: list[dict], n_authors: int) -> list[dict]:
    """Pick ``n_authors`` seed authors from the topic corpus' top papers.

    Authors are de-duplicated by S2 authorId, ordered by first appearance in the
    (relevance-sorted) corpus, and each one's profile papers are fetched to
    build its expertise text + co-authorship edges.
    """
    ordered: list[dict] = []
    seen: set[str] = set()
    for p in corpus:
        for a in p.get("authors") or []:
            aid = a.get("authorId")
            name = a.get("name") or ""
            if not aid or aid in seen:
                continue
            seen.add(aid)
            ordered.append({"authorId": aid, "name": name})
            if len(ordered) >= n_authors:
                break
        if len(ordered) >= n_authors:
            break

    # enrich each author with representative papers (profile + co-author ids)
    for a in ordered:
        data = _s2_get(
            f"author/{a['authorId']}/papers",
            {"limit": 20, "fields": _AUTHOR_PAPER_FIELDS},
        )
        papers = (data or {}).get("data") or []
        a["papers"] = papers
        a["paper_ids"] = [p.get("paperId") for p in papers if p.get("paperId")]
    return ordered


def _author_profile_text(author: dict) -> str:
    """Build a SciAgent sys_prompt from an author's representative papers."""
    name = author.get("name") or "Scientist"
    lines = [f"You are {name}, a researcher. Your recent work includes:"]
    for p in (author.get("papers") or [])[:8]:
        title = (p.get("title") or "").strip()
        abstract = (p.get("abstract") or "")[:280].strip()
        if title:
            lines.append(f"- {title}. {abstract}")
    if len(lines) == 1:
        lines.append("- (broad interests across the topic area)")
    return "\n".join(lines)


def _manifest_signature(topic: str, n_authors: int, n_papers: int) -> str:
    raw = f"{topic}|{n_authors}|{n_papers}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def build_snapshot(
    topic: str,
    out_dir: str | Path,
    n_authors: int = 16,
    n_papers: int = 800,
    *,
    force: bool = False,
    seed_papers: list[dict] | None = None,
) -> Snapshot:
    """Build (or reuse) a frozen S2 snapshot under ``<out_dir>/virsci_snapshot/``.

    Returns a :class:`Snapshot` ready for ``LivePlatform``. Re-uses a cached
    snapshot whose manifest signature matches ``(topic, n_authors, n_papers)``.
    """
    base = Path(out_dir) / "virsci_snapshot"
    manifest_path = base / "snapshot_manifest.json"
    sig = _manifest_signature(topic, n_authors, n_papers)

    if manifest_path.exists() and not force:
        try:
            man = json.loads(manifest_path.read_text())
            # Only reuse a NON-EMPTY frozen snapshot. A cached manifest with
            # n_papers==0 is a poisoned cache from a throttled/failed build —
            # reusing it would silently serve an ungrounded snapshot forever.
            if man.get("sha") == sig and int(man.get("n_papers", 0) or 0) > 0:
                return _load_snapshot(base, man)
        except Exception:
            pass  # corrupt cache → rebuild

    base.mkdir(parents=True, exist_ok=True)
    (base / "books").mkdir(exist_ok=True)
    (base / "papers").mkdir(exist_ok=True)

    corpus_raw = _fetch_corpus(topic, n_papers)
    used_seed = False
    if not corpus_raw and seed_papers:
        # Topic /paper/search came back empty (e.g. 429 rate-limit / sparse
        # query). Fall back to the already-vetted survey paperIds via
        # /paper/batch so the snapshot can still be grounded on real papers
        # (with authors + embeddings) instead of degrading to an ungrounded run.
        seed_ids = [p.get("paperId") for p in seed_papers if isinstance(p, dict)]
        corpus_raw = _fetch_corpus_by_ids(seed_ids)
        if corpus_raw:
            used_seed = True
            log.info(
                "snapshot: topic search empty; grounded on %d seed paper(s) via /paper/batch",
                len(corpus_raw),
            )
    if not corpus_raw:
        # Empty fetch (S2 429 rate-limit / network failure / no search hits) and
        # no usable seed papers. Do NOT proceed to write a "successful" 0-paper
        # manifest with placeholder authors — that silently runs VirSci fully
        # ungrounded and records it as a real_wrap success. Raise so the caller
        # (generate_ideas) degrades to the re-impl loop honestly and visibly.
        raise RuntimeError(
            f"S2 corpus fetch returned 0 papers for topic={topic!r} "
            f"(likely 429 rate-limit / network failure / no search hits); "
            f"refusing to build an ungrounded VirSci snapshot."
        )

    # split corpus into indexed (has specter_v2) + full paper_dicts
    indexed_corpus: list[dict] = []
    embeddings: list[list[float]] = []
    paper_dicts: list[dict] = []
    for i, p in enumerate(corpus_raw):
        rec = {
            "title": p.get("title") or "",
            "abstract": p.get("abstract") or "",
            "year": p.get("year"),
            "citation": p.get("citationCount", 0),
        }
        paper_dicts.append(rec)
        # persist papers/<i>.txt (eval-able dict literal, vendor read_txt_files_as_dict)
        (base / "papers" / f"{i}.txt").write_text(repr(rec))
        emb = (p.get("embedding") or {}).get("vector")
        if emb:
            indexed_corpus.append(rec)
            embeddings.append(emb)

    emb_arr = np.array(embeddings, dtype="float32") if embeddings else np.zeros((0, 768), dtype="float32")
    specter2_dim = emb_arr.shape[1] if emb_arr.size else 768
    emb_arr = _norm_rows(emb_arr) if emb_arr.size else emb_arr
    if emb_arr.size:
        np.save(base / "specter2_index.npy", emb_arr)
    else:
        # No embeddings this build: remove any stale index from a prior build so
        # the .npy row count never disagrees with corpus_indexed.json on reload.
        (base / "specter2_index.npy").unlink(missing_ok=True)
    # Persist the indexed corpus aligned 1:1 with emb_arr rows, so a cache
    # reload keeps reference_paper's index→{title,abstract} mapping exact even
    # when embedding-less papers interleave the full paper_dicts.
    (base / "corpus_indexed.json").write_text(json.dumps(indexed_corpus))

    authors = _select_authors(corpus_raw, n_authors)
    # pad with placeholder authors if S2 returned fewer than requested. Keep at
    # least 2 (truncating to max(2, n_authors), NOT n_authors) so the co-author
    # adjacency is never 1×1: a single author yields an all-zero row and
    # select_coauthors' arr/sum(arr) divides by zero (NaN). The real path needs
    # >=2 agents to deliberate anyway.
    while len(authors) < max(2, n_authors):
        authors.append({"authorId": None, "name": f"Researcher{len(authors)}", "papers": [], "paper_ids": []})
    authors = authors[: max(2, n_authors)]

    for i, a in enumerate(authors):
        (base / "books" / f"author_{i}.txt").write_text(_author_profile_text(a))

    adjacency = _build_adjacency(authors)
    np.savetxt(base / "adjacency.txt", adjacency, fmt="%d")

    manifest = {
        "topic": topic,
        "sha": sig,
        "n_authors": len(authors),
        "n_papers": len(paper_dicts),
        "s2_query": topic,
        "specter2_dim": specter2_dim,
        "indexed_papers": len(indexed_corpus),
        "has_api_key": bool(_s2_api_key()),
        "seed_fallback": used_seed,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))

    return Snapshot(
        dir=base,
        n_authors=len(authors),
        n_papers=len(paper_dicts),
        specter2_dim=specter2_dim,
        corpus=indexed_corpus,
        paper_dicts=paper_dicts,
        embeddings=emb_arr if emb_arr.size else None,
        topic=topic,
    )


def _load_snapshot(base: Path, man: dict) -> Snapshot:
    """Reconstruct a :class:`Snapshot` from frozen artifacts."""
    paper_dicts: list[dict] = []
    papers_dir = base / "papers"
    if papers_dir.exists():
        files = sorted(papers_dir.glob("*.txt"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0)
        for f in files:
            try:
                paper_dicts.append(eval(f.read_text()))  # noqa: S307 — our own repr()
            except Exception:
                continue
    emb_arr = None
    idx_path = base / "specter2_index.npy"
    if idx_path.exists():
        emb_arr = np.load(idx_path)
    # indexed corpus persisted aligned 1:1 with emb_arr rows (build_snapshot)
    indexed_corpus: list[dict] = []
    ci_path = base / "corpus_indexed.json"
    if ci_path.exists():
        try:
            indexed_corpus = json.loads(ci_path.read_text())
        except Exception:
            indexed_corpus = []
    return Snapshot(
        dir=base,
        n_authors=man.get("n_authors", 0),
        n_papers=man.get("n_papers", 0),
        specter2_dim=man.get("specter2_dim", 768),
        corpus=indexed_corpus,
        paper_dicts=paper_dicts,
        embeddings=emb_arr,
        topic=man.get("topic", ""),
    )
