"""Build artifact-grounded verified context for paper generation.

The verifiable research-memory layer (ari-skill-memory) exposes
``get_verified_context`` — artifact-grounded, reproducibility-aware claims.
This module scopes it to the *best* node's root→best lineage and writes
``{checkpoint_dir}/verified_context.json`` so the write_paper stage can ground
its quantitative claims (PLAN §8.4 — "Artifact-grounded generation").

Graceful by design: when the typed store is empty (consolidation off / no
typed entries) it writes an artifact with empty ``usable_for_claims`` and the
paper stage injects nothing — existing behavior is unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _scientific_score(node: Any) -> float:
    """Best-node ranking key: LLM scientific score, else max float metric."""
    m = getattr(node, "metrics", {}) or {}
    if isinstance(m, dict):
        s = m.get("_scientific_score")
        if isinstance(s, (int, float)) and not isinstance(s, bool):
            return float(s)
        floats = [
            v for v in m.values()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]
        if floats:
            return max(floats)
    return -1.0


def _valid_for_selection(node: Any) -> bool:
    m = getattr(node, "metrics", None)
    if not isinstance(m, dict):
        return True
    return m.get("_valid_for_frontier", True) is not False


def select_best_node(all_nodes: list[Any]) -> Any | None:
    """Pick the winning node whose lineage the paper is about.

    Nodes erased by RQGM selective erasure
    (``metrics['_valid_for_frontier'] is False``) are excluded outright —
    their scores were produced under a retired policy/prompt and must not
    ground the paper, its candidate escalation, or the archive seed. The key
    is only ever written by RQGM machinery (the FrontierRepairEngine on the
    exploration tree; the paper-archive runtime on draft nodes), so this
    clause is inert on the default paths (the ``_sterile`` pattern in
    ``BFTS.should_prune``). All nodes erased ⇒ ``None`` — contaminated
    evidence does not become clean by being the only evidence left.

    Among the remaining nodes, prefers ones with real experimental data,
    ranked by scientific score; falls back to any valid node if none carry
    real data.
    """
    nodes = [n for n in (all_nodes or []) if _valid_for_selection(n)]
    if not nodes:
        return None
    cand = [n for n in nodes if getattr(n, "has_real_data", False)]
    if not cand:
        cand = nodes
    cand.sort(key=_scientific_score, reverse=True)
    return cand[0]


def build_verified_context(
    checkpoint_dir: str | Path,
    all_nodes: list[Any],
    *,
    backend: Any | None = None,
) -> dict:
    """Return verified context for the best node's root→best lineage.

    Shape: ``{best_node_id, lineage, claims, limitations, usable_for_claims}``.
    Empty (no usable claims) when the typed store has no grounded entries.
    """
    empty = {
        "best_node_id": None, "lineage": [],
        "claims": [], "limitations": [], "usable_for_claims": [],
    }
    best = select_best_node(all_nodes)
    if best is None:
        return empty
    lineage = list(getattr(best, "ancestor_ids", []) or []) + [getattr(best, "id", "")]
    # Erasure never propagates to descendants automatically, so a VALID
    # winner can carry an ERASED ancestor. Its memory entries must not
    # ground the paper's claims — drop known-erased ids from the lineage
    # (unknown ids are kept: absence of the node is not evidence of
    # contamination).
    by_id = {str(getattr(n, "id", "") or ""): n for n in (all_nodes or [])}
    lineage = [
        nid for nid in lineage
        if nid and (nid not in by_id or _valid_for_selection(by_id[nid]))
    ]
    try:
        if backend is None:
            from ari.memory import get_backend
            backend = get_backend(checkpoint_dir)
        # Alias to avoid shadowing this module's own build_verified_context.
        from ari.memory import build_verified_context as _build_vc
        ctx = _build_vc(backend, lineage, purpose="paper")
    except Exception:
        return {**empty, "best_node_id": getattr(best, "id", None), "lineage": lineage}
    return {"best_node_id": getattr(best, "id", ""), "lineage": lineage, **ctx}


def write_verified_context(
    checkpoint_dir: str | Path,
    all_nodes: list[Any],
    *,
    backend: Any | None = None,
) -> dict:
    """Build + write ``{checkpoint_dir}/verified_context.json``. Best-effort.

    Only writes the artifact when there is at least one grounded claim, so an
    empty typed store leaves no file behind — the write_paper stage then sees
    no input and behaves exactly as before (no flow change).
    """
    data = build_verified_context(checkpoint_dir, all_nodes, backend=backend)
    path = Path(checkpoint_dir) / "verified_context.json"
    if not (data.get("usable_for_claims") or data.get("claims")):
        # A prior invocation's artifact may name a best node — or a lineage
        # member — that has since been erased (selective erasure); left in
        # place it would keep grounding the paper on contaminated claims.
        # Remove it when the winner OR the (erasure-filtered) lineage
        # changed; keep it when both are unchanged (a transient backend
        # failure must not discard a still-valid artifact).
        try:
            if path.exists():
                stale = json.loads(path.read_text())
                if (stale.get("best_node_id") != data.get("best_node_id")
                        or stale.get("lineage") != data.get("lineage")):
                    path.unlink()
        except Exception:
            pass
        return data
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        pass
    return data


def render_grounded_block(verified_context: dict, *, max_claims: int = 20) -> str:
    """Render usable_for_claims into a prompt block, or '' when none.

    Used by the write_paper stage to instruct the LLM to ground quantitative
    claims only in verified, artifact-backed (ideally reproduced) results.
    """
    usable = (verified_context or {}).get("usable_for_claims") or []
    if not usable:
        return ""
    lines = []
    for c in usable[:max_claims]:
        status = c.get("repro_status") or "unverified"
        arts = c.get("artifact_refs") or []
        art_paths = ", ".join(
            a.get("path", "") for a in arts if isinstance(a, dict)
        )[:200]
        lines.append(
            f"- [{status}] {(c.get('text') or '').strip()[:300]}"
            + (f"  (artifacts: {art_paths})" if art_paths else "")
        )
    return (
        "\n══ VERIFIED CONTEXT — GROUNDED CLAIMS ══\n"
        "Base every quantitative / reproducible claim in the paper body ONLY on "
        "the verified results below (each is artifact-backed; '[rerun_passed]' "
        "means independently reproduced). Do NOT invent numbers or assert "
        "results absent from this list.\n"
        + "\n".join(lines)
        + "\n══ END VERIFIED CONTEXT ══\n"
    )
