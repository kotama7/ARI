"""Best-First Tree Search for experiment orchestration."""

from __future__ import annotations

import json
import logging
import re as _re
import threading
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass

from ari.config import BFTSConfig

logger = logging.getLogger(__name__)
from ari.llm.client import LLMClient, LLMMessage
from ari.memory.client import MemoryClient
from ari.orchestrator.node import Node, NodeLabel


# ─────────────────────────────────────────
# Prompt budget (L-2): centralize the truncation/list limits used to keep
# expand() / select_next_node() prompts within model context windows.
# ─────────────────────────────────────────
@dataclass(frozen=True)
class _PromptBudget:
    parent_delta_chars: int = 240
    parent_concern_chars: int = 200
    parent_hint_chars: int = 200
    candidate_summary_select_chars: int = 120
    candidate_summary_expand_chars: int = 150
    sibling_direction_chars: int = 160
    list_top_n: int = 5


_BUDGET = _PromptBudget()


# ─────────────────────────────────────────
# Path / run-id resolution helper (I-5)
# ─────────────────────────────────────────
def _resolve_pm_and_run_id():
    """Return ``(PathManager, run_id)`` from ``ARI_CHECKPOINT_DIR``, or ``None``.

    Callers use this to read per-node files (node_report.json) without
    duplicating the env-resolution boilerplate. Returns ``None`` if the
    checkpoint dir is not set or cannot be resolved.
    """
    import os as _os

    from ari.paths import PathManager as _PM
    ckpt_path = _PM.checkpoint_dir_from_env()
    if ckpt_path is None:
        return None
    try:
        pm = _PM.from_checkpoint_dir(ckpt_path)
        run_id = _os.path.basename(str(ckpt_path).rstrip("/"))
        return pm, run_id
    except Exception:
        return None


def _format_parent_report_block(node: Node) -> str:
    """Read node_report.json (if present) and format it for expand()'s prompt.

    Returns "" on any failure so expand() falls back to the legacy text
    summary path.
    """
    import json as _json

    resolved = _resolve_pm_and_run_id()
    if resolved is None:
        return ""
    pm, run_id = resolved
    try:
        rp = pm.node_work_dir(run_id, node.id) / "node_report.json"
        if not rp.is_file():
            return ""
        rep = _json.loads(rp.read_text())
    except Exception:
        return ""

    sa = rep.get("self_assessment") or {}
    concerns = sa.get("concerns") or []
    hints = rep.get("next_steps_hints") or []
    delta = (rep.get("delta_vs_parent") or "").strip()
    fc = rep.get("files_changed") or {}
    added = [e.get("path") for e in (fc.get("added") or [])][: _BUDGET.list_top_n]
    modified = [e.get("path") for e in (fc.get("modified") or [])][: _BUDGET.list_top_n]
    parts = ["\nParent node_report (structured self-report):"]
    if delta:
        parts.append(f"  delta_vs_parent: {delta[: _BUDGET.parent_delta_chars]}")
    if added:
        parts.append(f"  files added: {added}")
    if modified:
        parts.append(f"  files modified: {modified}")
    if concerns:
        parts.append("  concerns flagged by evaluator:")
        for c in concerns[: _BUDGET.list_top_n]:
            parts.append(f"    - {c[: _BUDGET.parent_concern_chars]}")
    if hints:
        parts.append("  next-step hints from evaluator axes:")
        for h in hints[: _BUDGET.list_top_n]:
            parts.append(f"    - {h[: _BUDGET.parent_hint_chars]}")
    if len(parts) == 1:
        return ""
    return "\n".join(parts) + "\n"


def _normalize_for_name(s: str) -> str:
    """Normalize a string for human-readable node naming (L-1).

    - NFKC normalisation (fold full-width / compatibility characters).
    - Collapse runs of whitespace into a single space.
    - Trim leading/trailing whitespace.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = " ".join(s.split())
    return s.strip()


def _make_node_name(label: str, direction_text: str, depth: int) -> str:
    """Generate a short human-readable name from label + direction text."""
    label = _normalize_for_name(label)
    direction_text = _normalize_for_name(direction_text)
    # Take first sentence or first 50 chars of direction_text
    first = direction_text.split(".")[0].split("\n")[0].strip()
    # Remove leading bullet/number/symbol
    first = _re.sub(r"^[-*#\d.\s]+", "", first).strip()
    # Truncate
    if len(first) > 48:
        first = first[:45].rsplit(" ", 1)[0] + "…"
    if not first:
        first = label
    return f"{label}: {first}" if first.lower() != label.lower() else label


# ─────────────────────────────────────────
# JSON extraction (B-9): handle <think> blocks, multiple [...] groups, and
# stray prose around the directions array.
# ─────────────────────────────────────────
def _extract_directions_json(raw: str) -> list:
    """Return a list of direction items parsed from a (possibly noisy) LLM reply.

    Steps (each fails through to the next):
      1. Strip ``<think>...</think>`` reasoning blocks.
      2. Try non-greedy ``[ ... ]`` extraction.
      3. Try first-balanced-array scan.
      4. Try standalone ``{ ... }`` and wrap in a list.
      5. Fall back to ``[raw_stripped]`` as a single string direction.
    """
    if not raw:
        return []
    cleaned = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
    if not cleaned:
        return []

    # 2. Non-greedy bracket pair.
    m = _re.search(r"\[[\s\S]*?\]", cleaned)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    # 3. Balanced scan for the first [...] block.
    depth = 0
    start = -1
    for i, ch in enumerate(cleaned):
        if ch == "[":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    data = json.loads(cleaned[start : i + 1])
                    if isinstance(data, list):
                        return data
                except json.JSONDecodeError:
                    pass
                start = -1

    # 4. Lone {...} object.
    m = _re.search(r"\{[\s\S]*?\}", cleaned)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return [obj]
        except json.JSONDecodeError:
            pass

    # 5. Last resort.
    return [cleaned]


# ─────────────────────────────────────────
# Label-inference helper for the string fallback path (I-6).
# Uses word-boundary regexes so substrings like "invalid" don't trip
# the "validation" heuristic.
# ─────────────────────────────────────────
_LABEL_KEYWORDS: list[tuple[NodeLabel, _re.Pattern[str]]] = [
    (
        NodeLabel.ABLATION,
        _re.compile(
            r"\b(ablat\w*|disable|drop\s+component|remove\s+component|without\s+\w+)\b",
            _re.IGNORECASE,
        ),
    ),
    (
        NodeLabel.VALIDATION,
        _re.compile(
            r"\b(validation|validate|reproduc\w*|seed\s*=?\s*\d+|"
            r"different\s+seeds|edge\s+case|stress\s+test)\b",
            _re.IGNORECASE,
        ),
    ),
    (
        NodeLabel.IMPROVE,
        _re.compile(
            r"\b(improv\w*|optim\w*|tun\w*|faster|speedup|tighten|reduce\s+latency)\b",
            _re.IGNORECASE,
        ),
    ),
]


def _infer_label_from_text(text: str, parent_has_real_data: bool) -> NodeLabel:
    """Infer node label from free-form text using keyword patterns.

    Priority order: DEBUG (parent lacks real data) → ABLATION → VALIDATION →
    IMPROVE → DRAFT. Patterns use ``\\b`` word boundaries so e.g. "invalid"
    no longer matches the "validation" group.
    """
    if not parent_has_real_data:
        return NodeLabel.DEBUG
    for label, pattern in _LABEL_KEYWORDS:
        if pattern.search(text or ""):
            return label
    return NodeLabel.DRAFT


class BFTS:
    def __init__(self, config: BFTSConfig, llm: LLMClient) -> None:
        self.config = config
        self.llm = llm
        # Recently-run node labels (most recent last). Used by diversity_bonus()
        # to softly reward exploration of underrepresented exploration types.
        self._recent_label_history: list[str] = []
        self._max_recent_labels: int = 20
        # B-6: count how many times each frontier node has been expanded so
        # the run-loop can retire chronic re-expansions.
        self._expansion_count: dict[str, int] = {}
        # I-8: mtime-keyed cache of node_report.json for sibling/parent reads.
        self._report_cache: dict[str, tuple[int, dict]] = {}
        # I-9: protect mutable state across worker threads.
        self._lock = threading.Lock()

    # ── B-6: expansion count accessor ─────────────────────────────────
    def expansion_count(self, node_id: str) -> int:
        with self._lock:
            return self._expansion_count.get(node_id, 0)

    def record_run(self, node: Node) -> None:
        """Record that a node has just *finished* executing.

        Called from the run-loop after ``future.result()`` returns, regardless
        of success/failure. Used by :meth:`select_next_node` /
        :meth:`diversity_bonus` to track which exploration labels have been
        over- or under-represented among *actually-executed* nodes.
        """
        if node is None:
            return
        try:
            label = node.label.value if hasattr(node.label, "value") else str(node.label or "")
        except Exception:
            label = ""
        if not label:
            return
        with self._lock:
            self._recent_label_history.append(label)
            if len(self._recent_label_history) > self._max_recent_labels:
                self._recent_label_history = self._recent_label_history[
                    -self._max_recent_labels :
                ]

    def diversity_bonus(self, node: Node) -> float:
        """Return a small additive score bonus for nodes with underrepresented labels.

        - +0.05 if this node's label appears at most half as often as the most
          common label in the recent run history (i.e.
          ``my_count * 2 <= max_count``).
        - 0.0 otherwise.

        This is intentionally soft: scientific_score still dominates ranking.
        """
        with self._lock:
            history_snapshot = list(self._recent_label_history)
        if not history_snapshot:
            return 0.0
        try:
            label = node.label.value if hasattr(node.label, "value") else str(node.label or "")
        except Exception:
            return 0.0
        if not label:
            return 0.0
        counts = Counter(history_snapshot)
        max_count = max(counts.values())
        my_count = counts.get(label, 0)
        if my_count * 2 <= max_count:
            return 0.05
        return 0.0

    # ── L-3: shared deterministic fallback for both selectors. ─────────
    def _fallback_score(self, n: Node, *, frontier_size: int = 0) -> float:
        """Score a candidate node for the deterministic selector fallback.

        Strategy is controlled by ``BFTSConfig.frontier_score``:
          - ``scientific_only``: raw ``_scientific_score`` only.
          - ``scientific_plus_diversity`` (default): adds the diversity
            bonus so chronic-label nodes lose ties.
          - ``depth_penalized``: subtracts ``depth_penalty_lambda * depth``
            so the frontier spreads horizontally.
          - ``ucb_like``: adds a UCB1-style exploration term scaled by
            ``ucb_c``; ``visits`` counts how many times this node has
            already been expanded, ``N`` is the total visit count plus
            frontier size as a floor.
        """
        sci = float((n.metrics or {}).get("_scientific_score") or 0.0)
        strat = getattr(self.config, "frontier_score", "scientific_plus_diversity")
        if strat == "scientific_only":
            return sci
        if strat == "depth_penalized":
            lam = float(getattr(self.config, "depth_penalty_lambda", 0.05) or 0.0)
            return sci + self.diversity_bonus(n) - lam * float(n.depth or 0)
        if strat == "ucb_like":
            import math as _math
            c = float(getattr(self.config, "ucb_c", 0.5) or 0.0)
            with self._lock:
                visits = self._expansion_count.get(n.id, 0) + 1
                total_visits = sum(self._expansion_count.values())
            N = max(1, total_visits + max(0, int(frontier_size)))
            return sci + self.diversity_bonus(n) + c * _math.sqrt(
                _math.log(N) / visits
            )
        # default: scientific_plus_diversity
        return sci + self.diversity_bonus(n)

    def _select_fallback(self, candidates: list[Node]) -> Node:
        """Deterministic fallback when the LLM fails to pick a candidate.

        Preference order:
          1. Nodes with has_real_data=True (chain on real measurements).
          2. Highest ``_fallback_score`` under the configured strategy.
        """
        real = [n for n in candidates if n.has_real_data]
        pool = real or candidates
        frontier_size = len(candidates)
        return max(
            pool,
            key=lambda n: self._fallback_score(n, frontier_size=frontier_size),
        )

    # ── I-8: cached node_report.json loader. ──────────────────────────
    def _get_node_report(self, node_id: str) -> dict | None:
        """Cached read of ``node_report.json`` for *node_id*.

        Returns the parsed dict, or ``None`` if the file does not exist.
        Re-reads from disk when the file mtime advances.
        """
        resolved = _resolve_pm_and_run_id()
        if resolved is None:
            return None
        pm, run_id = resolved
        path = pm.node_work_dir(run_id, node_id) / "node_report.json"
        if not path.is_file():
            with self._lock:
                self._report_cache.pop(node_id, None)
            return None
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            return None

        with self._lock:
            cached = self._report_cache.get(node_id)
        if cached and cached[0] == mtime_ns:
            return cached[1]

        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

        with self._lock:
            self._report_cache[node_id] = (mtime_ns, data)
        return data

    def _load_sibling_node_reports(self, siblings: list["Node"]) -> dict[str, dict]:
        """Best-effort: load ``node_report.json`` for every sibling."""
        out: dict[str, dict] = {}
        for c in siblings:
            try:
                rep = self._get_node_report(c.id)
                if rep:
                    out[c.id] = rep
            except Exception:
                continue
        return out

    def select_next_node(
        self,
        candidates: list[Node],
        experiment_goal: str,
        memory: MemoryClient,
    ) -> Node:
        """LLM selects the next node to expand from the candidate list.

        BFTS is the core reasoning engine, where multi-variable and semantic
        judgments by LLM are appropriate. Unlike MCP skills, LLM usage here
        is justified by design.

        Evaluation criteria (information passed to LLM):
        - has_real_data: whether actual measurements exist
        - metrics: full metrics dict (multi-objective evaluation)
        - depth: exploration depth
        - eval_summary: evaluation summary from previous run
        - experiment goal and past memory: semantic context

        ARI does not retry failed nodes; failures produce DEBUG children
        instead, so ``retry_count`` is not surfaced here.
        """
        if not candidates:
            raise ValueError("No candidate nodes to select from")

        if len(candidates) == 1:
            return candidates[0]

        memories = memory.search(experiment_goal, limit=5)
        memory_context = (
            json.dumps(memories, ensure_ascii=False) if memories else "No relevant memories."
        )

        candidate_descriptions = []
        for i, node in enumerate(candidates):
            metrics_str = (
                json.dumps(node.metrics, ensure_ascii=False)
                if node.metrics else "not_yet_measured"
            )
            bonus = self.diversity_bonus(node)
            bonus_note = f", diversity_bonus=+{bonus:.2f}" if bonus > 0 else ""
            label_str = (
                node.label.value if hasattr(node.label, "value") else str(node.label or "?")
            )
            desc = (
                f"[{i}] id={node.id[-8:]}, depth={node.depth}, "
                f"label={label_str}, "
                f"has_real_data={node.has_real_data}, "
                f"metrics={metrics_str}, "
                f"summary={repr((node.eval_summary or 'none')[: _BUDGET.candidate_summary_select_chars])}"
                f"{bonus_note}"
            )
            candidate_descriptions.append(desc)

        # Phase PC5: see ``ari/prompts/orchestrator/bfts_select.md``.
        # BFTSConfig.select_prompt lets a config swap in an alternative
        # template (must accept the same placeholders).
        from ari.prompts import FilesystemPromptLoader as _PL_bs
        _prompt_key = getattr(
            self.config, "select_prompt", "orchestrator/bfts_select"
        )
        prompt = _PL_bs().load(_prompt_key).format(
            experiment_goal=experiment_goal,
            memory_context=memory_context,
            candidates="\n".join(candidate_descriptions),
        )

        response = self.llm.complete(
            [LLMMessage(role="user", content=prompt)],
            phase="bfts", skill="select_next_node",
        )
        try:
            idx = int(response.content.strip())
            if 0 <= idx < len(candidates):
                return candidates[idx]
        except (ValueError, AttributeError):
            pass

        return self._select_fallback(candidates)

    def should_prune(self, node: Node, *, current_total: int) -> bool:
        """Decide whether to prune this frontier node (never re-expand it).

        Hard cutoffs only. LLM judgement happens elsewhere.

        - ``current_total`` is the live count of ``all_nodes`` passed by the
          caller (B-1; replaces the previous BFTS-internal counter).
        - ``node.depth >= max_depth`` activates the previously dead-config
          depth limit (B-2).
        - ``metrics['_sterile'] is True`` retires nodes flagged sterile by
          the file-diff gate in the run loop (B-4).
        """
        cfg = self.config
        if current_total >= cfg.max_total_nodes:
            return True
        if node.depth >= cfg.max_depth:
            return True
        metrics = node.metrics or {}
        if metrics.get("_sterile") is True:
            return True
        return False

    def select_best_to_expand(
        self,
        frontier: list[Node],
        experiment_goal: str,
        memory: "MemoryClient",
    ) -> Node:
        """Select the best completed node to expand next (true BFTS step).

        Unlike select_next_node (which picks a node to *run*), this picks
        which completed node is most worth *expanding* into children.
        Nodes with higher scientific_score and stronger metrics are preferred.
        """
        if not frontier:
            raise ValueError("No frontier nodes to select from")
        if len(frontier) == 1:
            return frontier[0]

        candidate_descriptions = []
        for i, node in enumerate(frontier):
            metrics_str = (
                json.dumps(node.metrics, ensure_ascii=False)
                if node.metrics else "not_yet_measured"
            )
            desc = (
                f"[{i}] id={node.id[-8:]}, depth={node.depth}, "
                f"label={node.label.value if node.label else 'unknown'}, "
                f"has_real_data={node.has_real_data}, "
                f"metrics={metrics_str}, "
                f"summary={repr((node.eval_summary or 'none')[: _BUDGET.candidate_summary_expand_chars])}"
            )
            candidate_descriptions.append(desc)

        # Phase PC5: see ``ari/prompts/orchestrator/bfts_expand_select.md``.
        from ari.prompts import FilesystemPromptLoader as _PL_bes
        _expand_key = getattr(
            self.config,
            "expand_select_prompt",
            "orchestrator/bfts_expand_select",
        )
        prompt = _PL_bes().load(_expand_key).format(
            experiment_goal=experiment_goal,
            candidates="\n".join(candidate_descriptions),
        )

        response = self.llm.complete(
            [LLMMessage(role="user", content=prompt)],
            phase="bfts", skill="select_best_to_expand",
        )
        try:
            idx = int(response.content.strip())
            if 0 <= idx < len(frontier):
                return frontier[idx]
        except (ValueError, AttributeError):
            pass

        return self._select_fallback(frontier)

    def expand(
        self,
        node: Node,
        experiment_goal: str = "",
        idea_context: str = "",
        siblings: list[Node] | None = None,
        ancestors: list[Node] | None = None,
        all_run_nodes: list[Node] | None = None,
        existing_children: list[Node] | None = None,
        budget_remaining: int | None = None,
    ) -> list[Node]:
        """Expand a node and generate exactly one child node.

        expand() always yields at most one new child per call so that workers
        create new nodes one at a time (no pre-batching). Callers that want
        more children for the same parent should call expand() repeatedly,
        passing the previously-created children via ``existing_children`` so
        the LLM can avoid proposing duplicate directions.

        Label decisions emerge from LLM judgment based on context. The prompt
        provides:
          - Parent summary, score, status, depth/max_depth, remaining budget
          - Sibling scores at the same depth (if any)
          - All ancestor scores
          - Tree diversity metrics (unique labels seen so far, depth distribution)
          - Already-spawned children of this parent (to avoid duplication)
        """
        parent_status = "succeeded" if node.has_real_data else "failed/no-real-data"
        goal_line = f"Experiment goal: {experiment_goal}\n" if experiment_goal else ""
        sci_score = (node.metrics or {}).get("_scientific_score")
        sci_note = (
            f"Parent scientific score: {sci_score:.2f}/1.0\n"
            if sci_score is not None
            else "Parent scientific score: not yet evaluated\n"
        )
        idea_block = (
            f"\nResearch direction (from upstream idea generation):\n{idea_context}\n"
            if idea_context
            else ""
        )

        # I-4: depth and budget signals to the planner.
        depth_note = (
            f"Current depth: {node.depth} / max_depth {self.config.max_depth} "
            f"(child will be at depth {node.depth + 1})\n"
        )
        budget_note = (
            f"Remaining node budget: {budget_remaining} / {self.config.max_total_nodes}\n"
            if budget_remaining is not None
            else ""
        )

        # ── Parent's node_report (delta_vs_parent / concerns / hints) ──
        # Best-effort: when present, this enriches the prompt with the
        # parent's structured self-assessment so the planner can target
        # specific weaknesses or follow up on concrete next-step hints.
        parent_report_block = _format_parent_report_block(node)

        # ── Sibling scores at same depth ──
        sibling_lines: list[str] = []
        for s in siblings or []:
            if s.id == node.id:
                continue
            ss = (s.metrics or {}).get("_scientific_score")
            sl = s.label.value if hasattr(s.label, "value") else str(s.label or "?")
            sibling_lines.append(
                f"  - id={s.id[-8:]} label={sl} score="
                + (f"{float(ss):.2f}" if ss is not None else "n/a")
            )
        siblings_block = (
            "Sibling scores at same depth:\n" + "\n".join(sibling_lines) + "\n\n"
            if sibling_lines
            else "Sibling scores at same depth: (none)\n\n"
        )

        # ── Ancestor scores (root → parent) ──
        ancestor_lines: list[str] = []
        for a in ancestors or []:
            ass = (a.metrics or {}).get("_scientific_score")
            al = a.label.value if hasattr(a.label, "value") else str(a.label or "?")
            ancestor_lines.append(
                f"  - depth={a.depth} id={a.id[-8:]} label={al} score="
                + (f"{float(ass):.2f}" if ass is not None else "n/a")
            )
        ancestors_block = (
            "Ancestor scores:\n" + "\n".join(ancestor_lines) + "\n\n"
            if ancestor_lines
            else "Ancestor scores: (none)\n\n"
        )

        # ── Already-spawned children of this parent (avoid duplicating) ──
        sibling_reports = self._load_sibling_node_reports(existing_children or [])
        sibling_label_counts: Counter = Counter()
        existing_lines: list[str] = []
        for c in (existing_children or []):
            cl = c.label.value if hasattr(c.label, "value") else str(c.label or "?")
            sibling_label_counts[cl] += 1
            cdir = (c.eval_summary or "").strip().replace("\n", " ")
            cstatus = c.status.value if hasattr(c.status, "value") else str(c.status or "?")
            cscore = (c.metrics or {}).get("_scientific_score")
            score_part = f" score={float(cscore):.2f}" if isinstance(cscore, (int, float)) else ""
            line = (
                f"  - id={c.id[-8:]} label={cl} status={cstatus}{score_part}"
                f" direction={repr(cdir[: _BUDGET.sibling_direction_chars])}"
            )
            rep = sibling_reports.get(c.id)
            if rep:
                fc = rep.get("files_changed") or {}
                added = [e.get("path") for e in (fc.get("added") or [])][: _BUDGET.list_top_n]
                if added:
                    line += f" files_added={added}"
            existing_lines.append(line)

        if existing_lines:
            label_dist_str = ", ".join(
                f"{lbl}={cnt}" for lbl, cnt in sorted(sibling_label_counts.items())
            )
            # L-6: saturation threshold is now a config knob, default 2.
            threshold = int(getattr(self.config, "label_saturation_threshold", 2) or 2)
            saturated = sorted(
                lbl for lbl, cnt in sibling_label_counts.items() if cnt >= threshold
            )
            quota_lines = [
                f"  label distribution among THIS parent's existing children: "
                f"{{{label_dist_str}}}"
            ]
            if saturated:
                quota_lines.append(
                    f"  labels already saturated (≥{threshold} appearances): {saturated} — "
                    "propose a DIFFERENT label unless you have a strong scientific "
                    "reason to repeat one of these."
                )
            existing_block = (
                "Already-spawned children of THIS parent (do NOT duplicate these "
                "directions; propose something complementary):\n"
                + "\n".join(existing_lines) + "\n"
                + "\n".join(quota_lines) + "\n\n"
            )
        else:
            existing_block = (
                "Already-spawned children of THIS parent: "
                "(none — this is the first child)\n\n"
            )

        # ── Tree diversity metrics ──
        seen_labels: list[str] = []
        depth_counts: dict[int, int] = {}
        for n in all_run_nodes or []:
            try:
                lbl = n.label.value if hasattr(n.label, "value") else str(n.label or "")
            except Exception:
                lbl = ""
            if lbl and lbl not in seen_labels:
                seen_labels.append(lbl)
            try:
                d = int(getattr(n, "depth", 0) or 0)
            except (TypeError, ValueError):
                d = 0
            depth_counts[d] = depth_counts.get(d, 0) + 1
        diversity_block = (
            "Tree diversity so far:\n"
            f"  unique labels observed: {seen_labels if seen_labels else '(none)'}\n"
            f"  depth distribution: {depth_counts if depth_counts else '(empty)'}\n\n"
        )

        # Phase PC5: see ``ari/prompts/orchestrator/bfts_expand.md``.
        from ari.prompts import FilesystemPromptLoader as _PL_be
        prompt = _PL_be().load("orchestrator/bfts_expand").format(
            goal_line=goal_line,
            parent_id_short=node.id[-8:],
            parent_depth=node.depth,
            parent_status=parent_status,
            depth_note=depth_note,
            budget_note=budget_note,
            parent_metrics_json=json.dumps(node.metrics, ensure_ascii=False),
            parent_summary=node.eval_summary or 'none',
            sci_note=sci_note,
            idea_block=idea_block,
            parent_report_block=parent_report_block,
            siblings_block=siblings_block,
            ancestors_block=ancestors_block,
            existing_block=existing_block,
            diversity_block=diversity_block,
        )

        response = self.llm.complete(
            [LLMMessage(role="user", content=prompt)],
            node_id=node.id, phase="bfts", skill="expand",
        )

        # B-9: robust direction extraction across thinking-style responses.
        directions = _extract_directions_json(response.content or "")
        if not isinstance(directions, list):
            directions = [str(directions)]

        # Hard cap: expand() must yield at most one child per call.
        directions = directions[:1]

        children: list[Node] = []
        for item in directions:
            child_id = f"node_{uuid.uuid4().hex[:8]}"
            raw_label_text = ""
            if isinstance(item, dict):
                raw_label_text = str(item.get("label", "")).strip()
                label = NodeLabel.from_str(raw_label_text or "draft")
                direction_text = item.get("direction", str(item))
            else:
                # I-6: regex-based fallback with word boundaries.
                label = _infer_label_from_text(str(item), node.has_real_data)
                direction_text = str(item)

            child = Node(
                id=child_id,
                parent_id=node.id,
                depth=node.depth + 1,
                memory_snapshot=list(node.memory_snapshot),
                label=label,
                raw_label=raw_label_text,
                ancestor_ids=list(node.ancestor_ids) + [node.id],
            )
            child.eval_summary = direction_text
            child.original_direction = direction_text
            display_label = (
                raw_label_text
                if (label == NodeLabel.OTHER and raw_label_text)
                else (label.value if hasattr(label, "value") else str(label))
            )
            child.name = _make_node_name(display_label, direction_text, node.depth + 1)
            node.children.append(child_id)
            children.append(child)

        # B-7: fallback child must inherit memory_snapshot / direction / etc.
        if not children:
            fallback_label = NodeLabel.DEBUG if not node.has_real_data else NodeLabel.IMPROVE
            fallback_direction = (
                "(LLM returned no direction — fallback "
                f"{fallback_label.value}; investigate parent state)"
            )
            fb_child = Node(
                id=f"node_{uuid.uuid4().hex[:8]}",
                parent_id=node.id,
                depth=node.depth + 1,
                memory_snapshot=list(node.memory_snapshot),
                label=fallback_label,
                raw_label="",
                ancestor_ids=list(node.ancestor_ids or []) + [node.id],
            )
            fb_child.eval_summary = fallback_direction
            fb_child.original_direction = fallback_direction
            fb_label_text = (
                fallback_label.value
                if hasattr(fallback_label, "value")
                else str(fallback_label)
            )
            fb_child.name = _make_node_name(
                fb_label_text, fallback_direction, node.depth + 1
            )
            node.children.append(fb_child.id)
            children.append(fb_child)
            logger.warning(
                "expand(): LLM returned no directions, created fallback %s node",
                fallback_label,
            )

        # B-6: bump expansion count for the parent we just expanded.
        with self._lock:
            self._expansion_count[node.id] = self._expansion_count.get(node.id, 0) + 1

        return children
