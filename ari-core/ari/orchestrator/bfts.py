"""Best-First Tree Search for experiment orchestration."""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter

from ari.config import BFTSConfig

logger = logging.getLogger(__name__)
from ari.llm.client import LLMClient, LLMMessage
from ari.memory.client import MemoryClient
from ari.orchestrator.node import Node, NodeLabel, NodeStatus


def _make_node_name(label: str, direction_text: str, depth: int) -> str:
    """Generate a short human-readable name from label + direction text."""
    import re as _re
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


class BFTS:
    def __init__(self, config: BFTSConfig, llm: LLMClient) -> None:
        self.config = config
        self.llm = llm
        self.total_nodes: int = 0
        # Recently-run node labels (most recent last). Used by diversity_bonus()
        # to softly reward exploration of underrepresented exploration types.
        self._recent_label_history: list[str] = []
        self._max_recent_labels: int = 20

    def record_run(self, node: Node) -> None:
        """Record that a node has just been (or is about to be) executed.

        Used by select_next_node()/diversity_bonus() to track which
        exploration labels have been over- or under-represented recently.
        """
        if node is None:
            return
        try:
            label = node.label.value if hasattr(node.label, "value") else str(node.label or "")
        except Exception:
            label = ""
        if not label:
            return
        self._recent_label_history.append(label)
        if len(self._recent_label_history) > self._max_recent_labels:
            self._recent_label_history = self._recent_label_history[-self._max_recent_labels :]

    def diversity_bonus(self, node: Node) -> float:
        """Return a small additive score bonus for nodes with underrepresented labels.

        - +0.05 if this node's label is underrepresented in the recent history
          (count strictly less than the most common label's count).
        - 0.0 otherwise.

        This is intentionally soft: scientific_score still dominates ranking.
        """
        if not self._recent_label_history:
            return 0.0
        try:
            label = node.label.value if hasattr(node.label, "value") else str(node.label or "")
        except Exception:
            return 0.0
        if not label:
            return 0.0
        counts = Counter(self._recent_label_history)
        max_count = max(counts.values())
        my_count = counts.get(label, 0)
        # "Underrepresented" = at most half the most common label's count
        if my_count * 2 <= max_count:
            return 0.05
        return 0.0

    def select_next_node(
        self,
        candidates: list[Node],
        experiment_goal: str,
        memory: MemoryClient,
    ) -> Node:
        """LLM selects the next node to expand from the candidate list.

        BFTS is the core reasoning engine, where multi-variable and semantic judgments by LLM are
        appropriate. Unlike MCP skills, LLM usage here is justified by design.

        Evaluation criteria (information passed to LLM):
        - has_real_data: whether actual measurements exist
        - metrics: full metrics dict (multi-objective evaluation)
        - depth / retry_count: exploration cost
        - eval_summary: evaluation summary from previous run
        - experiment goal and past memory: semantic context
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
            desc = (
                f"[{i}] id={node.id[-8:]}, depth={node.depth}, "
                f"retry={node.retry_count}, "
                f"has_real_data={node.has_real_data}, "
                f"metrics={metrics_str}, "
                f"summary={repr((node.eval_summary or 'none')[:120])}"
                f"{bonus_note}"
            )
            candidate_descriptions.append(desc)

        prompt = (
            f"You are selecting the most promising node to explore next in a research tree.\n\n"
            f"Experiment goal: {experiment_goal}\n\n"
            f"Relevant past memories:\n{memory_context}\n\n"
            f"Candidates:\n" + "\n".join(candidate_descriptions) + "\n\n"
            f"Selection criteria:\n"
            f"- Nodes with has_real_data=True and strong metrics are high-value\n"
            f"- Prefer unexplored directions (low retry) over already-tried paths\n"
            f"- Consider all metrics holistically (multi-objective)\n"
            f"- Deeper nodes with excellent results are worth continuing\n"
            f"- A small diversity_bonus is awarded to underrepresented exploration "
            f"types; treat it as a soft tiebreaker, not a primary signal\n"
            f"Reply with ONLY the index number (0-based) of the best node."
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

        # Fallback: prefer nodes with has_real_data=True, then rank by
        # scientific_score + diversity_bonus, then pick first.
        def _fallback_score(n: Node) -> float:
            sci = float((n.metrics or {}).get("_scientific_score") or 0.0)
            return sci + self.diversity_bonus(n)

        real_nodes = [n for n in candidates if n.has_real_data]
        pool = real_nodes if real_nodes else candidates
        return max(pool, key=_fallback_score)

    def should_prune(self, node: Node) -> bool:
        """Determine whether to prune this node.

        Only hard cutoffs (resource constraints) are applied.
        depth is treated as a soft constraint passed to LLM as reference information;
        Not pruned here. Accounts for good nodes appearing at deep levels.
        """
        # Resource exhaustion: total nodes in search space reached the limit
        if self.total_nodes >= self.config.max_total_nodes:
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
                f"summary={repr((node.eval_summary or 'none')[:150])}"
            )
            candidate_descriptions.append(desc)

        prompt = (
            f"You are selecting which completed research node to expand next in a BFTS tree.\n\n"
            f"Experiment goal: {experiment_goal}\n\n"
            f"Completed nodes awaiting expansion:\n"
            + "\n".join(candidate_descriptions)
            + "\n\nSelect the single most promising node to expand. "
            "Prefer nodes with high scientific_score, strong metrics, and unexplored directions. "
            "Avoid nodes that have already been retried many times or are at excessive depth.\n"
            "Reply with ONLY the index number (0-based)."
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

        # Fallback: pick by highest _scientific_score
        return max(
            frontier,
            key=lambda n: float((n.metrics or {}).get("_scientific_score") or 0),
        )

    def expand(
        self,
        node: Node,
        experiment_goal: str = "",
        idea_context: str = "",
        siblings: list[Node] | None = None,
        ancestors: list[Node] | None = None,
        all_run_nodes: list[Node] | None = None,
        existing_children: list[Node] | None = None,
    ) -> list[Node]:
        """Expand a node and generate exactly one child node.

        expand() always yields at most one new child per call so that workers
        create new nodes one at a time (no pre-batching). Callers that want
        more children for the same parent should call expand() repeatedly,
        passing the previously-created children via ``existing_children`` so
        the LLM can avoid proposing duplicate directions.

        Label decisions emerge from LLM judgment based on context, not from
        a hardcoded template. The prompt provides:
          - Parent summary, score, and status
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
            f"\nResearch direction (from upstream idea generation):\n{idea_context[:800]}\n"
            if idea_context
            else ""
        )

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
        existing_lines: list[str] = []
        for c in existing_children or []:
            cl = c.label.value if hasattr(c.label, "value") else str(c.label or "?")
            cdir = (c.eval_summary or "").strip().replace("\n", " ")
            existing_lines.append(
                f"  - id={c.id[-8:]} label={cl} direction={repr(cdir[:160])}"
            )
        existing_block = (
            "Already-spawned children of THIS parent (do NOT duplicate these directions; "
            "propose something complementary):\n"
            + "\n".join(existing_lines) + "\n\n"
            if existing_lines
            else "Already-spawned children of THIS parent: (none — this is the first child)\n\n"
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

        prompt = (
            "You are expanding a BFTS research tree node.\n\n"
            f"{goal_line}"
            f"Parent node id={node.id[-8:]}, depth={node.depth}, status={parent_status}\n"
            f"Parent metrics: {json.dumps(node.metrics, ensure_ascii=False)}\n"
            f"Parent summary: {node.eval_summary or 'none'}\n"
            f"{sci_note}"
            f"{idea_block}\n"
            f"{siblings_block}"
            f"{ancestors_block}"
            f"{existing_block}"
            f"{diversity_block}"
            "Propose exactly ONE child research direction that is the most scientifically "
            "valuable next step. The \"label\" field MUST be exactly one of these five "
            "values (all lowercase, no other strings allowed, no synonyms, no inventions): "
            "draft, improve, debug, ablation, validation. "
            "Base your choice on the experimental context above, not on a fixed template.\n\n"
            "Label selection guidance:\n"
            "- 'debug': parent FAILED or has no real data — diagnose and fix it.\n"
            "- 'improve': parent succeeded and you want to push its metrics higher by tuning "
            "parameters, flags, or algorithms.\n"
            "- 'ablation': isolate which component drives the parent's gains by removing or "
            "varying ONE component. State explicitly what is removed/varied and what delta vs. "
            "the parent metrics you expect.\n"
            "- 'validation': rigorously verify the parent's claims (different seeds, edge "
            "cases, stress tests, expected-degradation checks).\n"
            "- 'draft': start a fresh implementation from scratch to introduce a fundamentally "
            "NEW perspective (use this instead of inventing a new label like 'replication' or "
            "'generalization').\n\n"
            "Reply ONLY with a JSON array containing exactly one element: "
            "[{\"label\": \"<one of: draft|improve|debug|ablation|validation>\", "
            "\"direction\": \"...\"}]\n"
            "Example: [{\"label\": \"validation\", \"direction\": \"<one-sentence plan>\"}]"
        )

        response = self.llm.complete(
            [LLMMessage(role="user", content=prompt)],
            node_id=node.id, phase="bfts", skill="expand",
        )

        try:
            raw = response.content.strip()
            import re as _re
            m = _re.search(r"\[.*\]", raw, _re.DOTALL)
            if m:
                raw = m.group(0)
            directions = json.loads(raw)
        except (json.JSONDecodeError, Exception):
            directions = [response.content.strip()]

        if not isinstance(directions, list):
            directions = [str(directions)]

        # Hard cap: expand() must yield at most one child per call.
        # Workers create new nodes one at a time; we never pre-create batches.
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
                # Fallback: auto-infer label when item is a plain string
                text = str(item).lower()
                if not node.has_real_data:
                    label = NodeLabel.DEBUG
                elif "ablat" in text or "without" in text or "remove" in text:
                    label = NodeLabel.ABLATION
                elif "valid" in text or "seed" in text or "repro" in text:
                    label = NodeLabel.VALIDATION
                elif "improv" in text or "optim" in text or "faster" in text or "tuning" in text:
                    label = NodeLabel.IMPROVE
                else:
                    label = NodeLabel.DRAFT
                direction_text = str(item)

            child = Node(
                id=child_id,
                parent_id=node.id,
                depth=node.depth + 1,
                memory_snapshot=list(node.memory_snapshot),
                label=label,
                raw_label=raw_label_text,
                ancestor_ids=list(node.ancestor_ids) + [node.id],
                # ↑ ancestor chain: parent ancestors + parent itself
                # child nodes can only access memories in ancestor_ids
            )
            child.eval_summary = direction_text
            # Prefer the raw LLM label for naming when label==OTHER
            display_label = (
                raw_label_text
                if (label == NodeLabel.OTHER and raw_label_text)
                else (label.value if hasattr(label, "value") else str(label))
            )
            child.name = _make_node_name(display_label, direction_text, node.depth + 1)
            node.children.append(child_id)
            children.append(child)
            self.total_nodes += 1

        # Fallback: if LLM returned no directions, create at least one child
        if not children:
            import uuid as _uuid_fb
            fallback_label = NodeLabel.DEBUG if not node.has_real_data else NodeLabel.IMPROVE
            fb_child = Node(
                id=f"node_{_uuid_fb.uuid4().hex[:8]}",
                parent_id=node.id,
                depth=node.depth + 1,
                label=fallback_label,
                ancestor_ids=list(node.ancestor_ids or []) + [node.id],
            )
            fb_child.name = _make_node_name(fallback_label.value if hasattr(fallback_label, "value") else str(fallback_label), "fallback", node.depth + 1)
            node.children.append(fb_child.id)
            children.append(fb_child)
            self.total_nodes += 1
            logger.warning("expand(): LLM returned no directions, created fallback %s node", fallback_label)

        return children
