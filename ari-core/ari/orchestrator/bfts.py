"""Best-First Tree Search for experiment orchestration."""

from __future__ import annotations

import json
import uuid

from ari.config import BFTSConfig
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
            desc = (
                f"[{i}] id={node.id[-8:]}, depth={node.depth}, "
                f"retry={node.retry_count}, "
                f"has_real_data={node.has_real_data}, "
                f"metrics={metrics_str}, "
                f"summary={repr((node.eval_summary or 'none')[:120])}"
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
            f"Reply with ONLY the index number (0-based) of the best node."
        )

        response = self.llm.complete([LLMMessage(role="user", content=prompt)])
        try:
            idx = int(response.content.strip())
            if 0 <= idx < len(candidates):
                return candidates[idx]
        except (ValueError, AttributeError):
            pass

        # Fallback: prefer nodes with has_real_data=True, otherwise pick first
        real_nodes = [n for n in candidates if n.has_real_data]
        return real_nodes[0] if real_nodes else candidates[0]

    def should_prune(self, node: Node) -> bool:
        """Determine whether to prune this node.

        Only hard cutoffs (resource constraints) are applied.
        depth is treated as a soft constraint passed to LLM as reference information;
        Not pruned here. Accounts for good nodes appearing at deep levels.
        """
        # Resource exhaustion: total nodes in search space reached the limit
        if self.total_nodes >= self.config.max_total_nodes:
            return True
        # A node that has real data (succeeded) should NEVER be pruned based on retry count.
        # Only prune failing nodes that have exhausted retries.
        if not node.has_real_data and node.retry_count >= self.config.max_retries_per_node:
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

        response = self.llm.complete([LLMMessage(role="user", content=prompt)])
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

    def expand(self, node: Node, experiment_goal: str = "") -> list[Node]:
        """Expand a node and generate child nodes. Each child is assigned a label."""
        parent_status = "succeeded" if node.has_real_data else "failed/no-real-data"
        goal_line = f"Experiment goal: {experiment_goal}\n" if experiment_goal else ""
        # Rule-based label guidance based on parent state
        if not node.has_real_data:
            label_hint = "Parent FAILED — prefer \"debug\" or \"draft\" to fix the issue."
        elif node.depth == 0:
            label_hint = "Root node succeeded — suggest \"improve\", \"ablation\", and \"validation\" directions."
        else:
            label_hint = "Parent succeeded — prefer \"improve\", \"ablation\", or \"validation\"; use \"draft\" only for fundamentally new approaches."
        sci_score = (node.metrics or {}).get("_scientific_score")
        sci_note = (
            f"Scientific quality score from peer review: {sci_score:.2f}/1.0\n"
            if sci_score is not None else ""
        )
        prompt = (
            f"You are expanding a BFTS research tree node.\n\n"
            f"{goal_line}"
            f"Parent node: id={node.id[-8:]}, depth={node.depth}, status={parent_status}\n"
            f"Parent metrics: {json.dumps(node.metrics, ensure_ascii=False)}\n"
            f"Parent summary: {node.eval_summary or 'none'}\n"
            f"{sci_note}"
            f"\n{label_hint}\n\n"
            f"⚠️ ABLATION STUDY REQUIREMENT: If you suggest an ablation, you MUST:\n"
            f"  1. Identify what component/parameter to remove or vary (be specific)\n"
            f"  2. State the baseline: parent metrics = {json.dumps(node.metrics or {}, ensure_ascii=False)[:300]}\n"
            f"  3. Predict what delta you expect and why it matters scientifically\n"
            f"  An ablation without a defined baseline is scientifically invalid.\n\n"
            f"Suggest 2-3 child research directions. For each, assign a label from:\n"
            f"  draft      - new implementation from scratch\n"
            f"  improve    - improve parent results (tune flags/params)\n"
            f"  debug      - fix parent failure/error\n"
            f"  ablation   - remove ONE component and compare metric vs parent baseline; must quantify the delta\n"
            f"  validation - re-run parent with different seeds/conditions\n\n"
            f"Reply ONLY with a JSON array, each element: {{\"label\": \"...\", \"direction\": \"...\"}}\n"
            f"Example: [{{\"label\": \"improve\", \"direction\": \"Try -Ofast flag\"}}, ...]"
        )

        response = self.llm.complete([LLMMessage(role="user", content=prompt)])

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

        children: list[Node] = []
        for item in directions:
            child_id = f"node_{uuid.uuid4().hex[:8]}"
            if isinstance(item, dict):
                label = NodeLabel.from_str(item.get("label", "draft"))
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
                ancestor_ids=list(node.ancestor_ids) + [node.id],
                # ↑ ancestor chain: parent ancestors + parent itself
                # child nodes can only access memories in ancestor_ids
            )
            child.eval_summary = direction_text
            child.name = _make_node_name(label.value if hasattr(label, "value") else str(label), direction_text, node.depth + 1)
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
