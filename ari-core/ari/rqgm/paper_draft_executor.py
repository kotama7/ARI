"""The draft NodeExecutor over ``ari-skill-paper`` (paper-archive Task 02,
docs/plans/ari_rqgm_paper/02 §5.4).

:class:`PaperDraftExecutor` satisfies ``ari.protocols.search.NodeExecutor``
(``run(node, experiment) -> Node``) and wraps the paper subprocess as the
"hands", exactly as coding skills are the hands for exploration nodes. It
executes ONE node with exactly ONE generative skill call:

- a SEED (depth 1): ``write_paper_iterative`` into a per-node ``.tex`` path;
- a REFINE child (depth >= 2): one ``paper_refine`` against the PARENT draft.

The refine LOOP lives in the tree (the driver's frontier, §5.3), not inside
the executor. The reviewer is an INJECTED scoring oracle (its prompt/utility
live in Tasks 03/04); the substrate is testable with a stub scorer. The
executor never calls ``compile_paper`` (lazy compile is the runtime's,
§5.5).

Plan-vs-code note: the plan sketch reads ``out["latex_path"]`` from the skill,
but the shipped ``write_paper_iterative`` / ``paper_refine`` return the LaTeX
CONTENT under ``latex`` (server.py:1124 / :2475). The executor therefore owns
writing that content to the per-node ``.tex`` path (the archive versions
drafts as content-hashed files, never overwrites — §6.1 / Q-49).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ari.orchestrator.node import Node
from ari.rqgm.paper_archive import (
    PAPER_DRAFT_ARCHIVE_SCHEMA_VERSION,
    read_paper_draft_archive,
    write_paper_draft_record,
)

log = logging.getLogger(__name__)


class PaperSkillCallError(RuntimeError):
    """A ``ari-skill-paper`` draft call did not return a usable payload.

    Raised so a failed draft call behaves EXACTLY like the already-tested
    "archive interrupted" contract (``InterruptingPaperMCP`` raises; the records
    already appended survive, no winner is finalised, ``run_archive`` fail-opens
    to linear WITH a logged traceback). Production could not reach that contract
    on its own: ``MCPClient.call_tool`` never raises on tool failure — it
    RETURNS ``{"error": …}`` or wraps the tool's error text as
    ``{"result": "<non-JSON text>"}`` — which the executor read as "no latex"
    and wrote as a silent 0-byte draft."""


def _unwrap_tool_result(out, tool_name: str = "") -> dict:
    """Peel the shipped ``MCPClient.call_tool`` envelope, or RAISE.

    The production client (``ari/mcp/client.py``:227-239) does NOT hand back the
    tool's payload dict — it serialises the tool return to text and wraps it as
    ``{"result": "<json-string>"}`` (the SAME envelope
    ``ari/pipeline/stage_runner.py`` unwraps for the linear pipeline). The
    archive executor reads ``latex`` straight off the tool payload, so it MUST
    peel that envelope first; without it every ``write_paper_iterative`` /
    ``paper_refine`` call read ``{}`` and each draft collapsed to an
    empty-string ``.tex`` (``tex_sha256`` e3b0c44…) — the whole archive degraded
    to K empty copies and fell back to linear (observed 2026-07-19).

    The FAILURE shapes raise :class:`PaperSkillCallError` rather than degrading
    to an empty payload. The shipped paper skill RAISES on error
    (``ari-skill-paper/src/server.py`` write_paper_iterative), which the MCP
    layer turns into an error-text envelope; treating that as "no latex" was the
    same silent-empty-draft bug one layer down, and it additionally stamped
    ``anchors_preserved: True`` on a file containing zero anchors.

    Backward-compatible with the test doubles that return the raw payload dict
    (no ``result``/``error`` key => the dict passes through unchanged)."""
    if isinstance(out, dict) and "error" in out and "result" not in out:
        raise PaperSkillCallError(
            f"paper skill tool {tool_name or '?'} returned an error envelope: "
            f"{str(out.get('error'))[:400]}"
        )
    if isinstance(out, dict) and "result" in out:
        inner = out["result"]
        if isinstance(inner, str):
            try:
                parsed = json.loads(inner)
            except Exception:
                # Not a serialised tool payload — the shipped client puts the
                # tool's ERROR TEXT here when the tool raised. Never a draft.
                raise PaperSkillCallError(
                    f"paper skill tool {tool_name or '?'} returned non-JSON "
                    f"text (the tool most likely raised): {inner[:400]}"
                ) from None
            if isinstance(parsed, dict):
                return parsed
            raise PaperSkillCallError(
                f"paper skill tool {tool_name or '?'} returned a non-object "
                f"payload: {type(parsed).__name__}"
            )
        return inner if isinstance(inner, dict) else out
    if isinstance(out, str):
        try:
            parsed = json.loads(out)
        except Exception:
            raise PaperSkillCallError(
                f"paper skill tool {tool_name or '?'} returned bare non-JSON "
                f"text: {out[:400]}"
            ) from None
        if isinstance(parsed, dict):
            return parsed
        raise PaperSkillCallError(
            f"paper skill tool {tool_name or '?'} returned a non-object payload"
        )
    if isinstance(out, dict):
        return out
    raise PaperSkillCallError(
        f"paper skill tool {tool_name or '?'} returned {type(out).__name__}, "
        "not a payload dict"
    )


def _require_latex(payload: dict, tool_name: str, node) -> str:
    """The draft body, or RAISE.

    An EMPTY ``latex`` is never a draft: it produces a 0-byte ``.tex`` whose
    ``tex_sha256`` is the empty-string digest (e3b0c44…) and — on the refine
    branch — a record stamping ``anchors_preserved: True`` for a file containing
    zero anchors, i.e. a fabricated value a downstream consumer trusts. Recording
    it was how a wholly failed archive still looked like K completed drafts."""
    latex = payload.get("latex", "") or ""
    if not str(latex).strip():
        raise PaperSkillCallError(
            f"paper skill tool {tool_name} returned no latex for node "
            f"{getattr(node, 'id', '?')} (payload keys: "
            f"{sorted(payload)[:8]}) — refusing to record a 0-byte draft"
        )
    return latex


class PaperDraftExecutor:
    """One node, one generative call. Satisfies ``NodeExecutor``."""

    def __init__(
        self,
        mcp_paper,
        *,
        reviewer,
        checkpoint_dir,
        base_seed: int = 1000,
        epoch_id: str = "epoch_000",
    ) -> None:
        self.mcp = mcp_paper
        self.reviewer = reviewer              # governed paper_reviewer oracle (03/04)
        self.ckpt = Path(checkpoint_dir)
        self.base_seed = int(base_seed)
        self.epoch_id = str(epoch_id)
        self._records: dict[str, dict] = {}   # node_id -> archive record (this run)
        self._seed_order: list[str] = []       # creation order of seed nodes

    # ── skill dispatch (call_tool is the shipped MCPClient surface) ──────
    def _call(self, tool_name: str, args: dict) -> dict:
        fn = getattr(self.mcp, "call_tool", None) or getattr(self.mcp, "call", None)
        if fn is None:
            raise RuntimeError("mcp client exposes neither call_tool nor call")
        out = fn(tool_name, args)
        return _unwrap_tool_result(out, tool_name)

    def restore(self, prior_nodes: list) -> None:
        """Prime the per-run seed indexing from a resumed round's restored nodes
        (§8.6, §9 "producing the same node set as the uninterrupted run (P2)").

        ``_seed_index`` derives ``decode_seed`` and the writer framing from the
        per-run ``_seed_order``. Without this, a resume that restored ``draft_0``
        / ``draft_1`` would hand a freshly minted ``draft_2`` index 0 — i.e.
        ``base_seed`` and ``hashes[0]`` — instead of index 2, silently producing a
        DIFFERENT node set than the uninterrupted run. Seeding the order in
        creation order keeps the next index correct.
        """
        for n in prior_nodes or []:
            if getattr(n, "original_direction", None) == "seed":
                nid = str(getattr(n, "id", ""))
                if nid and nid not in self._seed_order:
                    self._seed_order.append(nid)

    def _seed_index(self, node: Node) -> int:
        if node.id not in self._seed_order:
            self._seed_order.append(node.id)
        return self._seed_order.index(node.id)

    def _rel_tex_path(self, node: Node) -> str:
        """``archive/{epoch_id}/{node.id}/full_paper[.rN].tex`` — a
        node-work-dir-like subtree, EPOCH-SCOPED.

        §6.1: "every draft is a content-hashed record, never an in-place
        overwrite of `full_paper.tex`" — drafts are versioned, not overwritten.
        The path used to key off ``node.id`` alone, but node ids are NOT unique
        across rounds: ``_run_one_round`` builds a fresh ``PaperArchiveStrategy``
        per round, so ``_fanout`` restarts and ``expand`` re-mints ``draft_0``,
        ``draft_0.r1``, … every epoch. Round 1's ``draft_0`` therefore
        `write_text`-overwrote round 0's, and every earlier record's
        ``tex_sha256`` went stale against the bytes at its OWN ``tex_path`` —
        breaking exactly the per-epoch draft-versioning half of Q-49 this schema
        exists to resolve. ``self.epoch_id`` is already in hand, so scoping the
        FILESYSTEM by epoch restores the invariant while keeping the node ids the
        plan's §6.1 example and §9 topology tests pin (``draft_0`` /
        ``draft_0.r1``).
        """
        if node.original_direction == "seed":
            return f"archive/{self.epoch_id}/{node.id}/full_paper.tex"
        return (f"archive/{self.epoch_id}/{node.parent_id}/"
                f"{node.id.replace('.', '_')}.tex")

    def _abs(self, rel_tex_path: str) -> Path:
        return self.ckpt / rel_tex_path

    def _write_tex(self, rel_tex_path: str, latex: str) -> None:
        p = self._abs(rel_tex_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(latex or "", encoding="utf-8")

    def _archive_record(self, node_id: str) -> dict:
        rec = self._records.get(node_id)
        if rec is not None:
            return rec
        # Resume path (§8.6): rebuild from the persisted archive. Scoped to THIS
        # epoch — node ids are re-minted every round, so an unscoped scan returns
        # a prior epoch's homonym and a refine would be built against the wrong
        # parent draft (its `tex_path` / `decode_seed` / framing). LAST match
        # wins: the archive is append-only, so the last write is that node's
        # current state.
        found: dict = {}
        for r in read_paper_draft_archive(self.ckpt):
            if (str(r.get("node_id")) == str(node_id)
                    and str(r.get("epoch_id", "")) == self.epoch_id):
                found = r
        if found:
            self._records[node_id] = found
        return found

    def run(self, node: Node, experiment: dict) -> Node:
        manuscript = dict(experiment.get("manuscript_binding") or {})
        fixed_block = str(experiment.get("manuscript_fixed_block") or "")
        bind_reviewer = getattr(self.reviewer, "bind_manuscript_inputs", None)
        if callable(bind_reviewer):
            bind_reviewer(manuscript, fixed_block)
        writer_prompt = str(experiment.get("writer_prompt_text") or "")
        if fixed_block:
            writer_prompt = (
                f"{writer_prompt}\n\n{fixed_block}" if writer_prompt else fixed_block
            )
        rel_tex = self._rel_tex_path(node)
        if node.original_direction == "seed":
            i = self._seed_index(node)
            hashes = experiment.get("writer_prompt_hashes") or ["founding"]
            framing = str(hashes[i % len(hashes)])           # -> _framing_key (§5.2)
            decode_seed = self.base_seed + i
            out = self._call(
                "write_paper_iterative",
                {
                    "experiment_summary": experiment.get("experiment_summary", ""),
                    "verified_context_json": experiment.get("verified_context_json", ""),
                    "science_data_json": experiment.get("science_data_json", ""),
                    "figures_manifest_json": experiment.get("figures_manifest_json", ""),
                    "refs_json": experiment.get("refs_json", ""),
                    "nodes_json_path": experiment.get("nodes_json_path", ""),
                    "venue": experiment.get("venue", "arxiv"),
                    "author_name": experiment.get("author_name", ""),
                    # §5.8: the epoch's ACTIVE governed paper_writer prompt bytes
                    # DRIVE the skill's reflection instruction ("" => linear
                    # byte-identical). The evolving bytes live only in ari-core.
                    "writer_prompt_override": experiment.get(
                        "writer_prompt_text", ""
                    ) if not fixed_block else writer_prompt,
                    # §5.4 decision 5: candidate i is SAMPLED under its own seed.
                    # Recording the seed without sending it made every record
                    # advertise a decode identity nothing honoured — with n == 1
                    # writer prompt (the shipped default) this is the ONLY
                    # diversity lever, so K seeds collapsed to K copies (R1).
                    "decode_seed": decode_seed,
                },
            )
            latex = _require_latex(out, "write_paper_iterative", node)
            self._write_tex(rel_tex, latex)
            anchors = True
            refine_pass = 0
            parent_draft_id = None
            suggested_ref = ""                 # seed: no parent review drove it
        else:
            parent = self._archive_record(node.parent_id)
            parent_rel = parent.get("tex_path") or self._rel_tex_path(
                Node(id=node.parent_id, parent_id=None, depth=node.depth - 1)
            )
            parent_abs = str(self._abs(parent_rel))
            review = self.reviewer.review(parent_abs)         # suggested_revisions
            # A refine INHERITS its parent draft's decode identity (as it does
            # its framing), so the child is sampled under the same seed the
            # record advertises. Resolved BEFORE the call — it is now an input
            # to it, not just a column written afterwards.
            decode_seed = int(parent.get("decode_seed", self.base_seed))
            out = self._call(
                "paper_refine",
                {
                    "tex_path": parent_abs,
                    "suggested_revisions_json": getattr(
                        review, "suggested_revisions_json", ""
                    ) or "",
                    "venue": experiment.get("venue", "arxiv"),
                    "writer_prompt_override": experiment.get(
                        "writer_prompt_text", ""
                    ) if not fixed_block else writer_prompt,
                    "decode_seed": decode_seed,
                },
            )
            latex = _require_latex(out, "paper_refine", node)
            self._write_tex(rel_tex, latex)
            anchors = bool(out.get("anchors_preserved", True))
            framing = str(parent.get("writer_prompt_hash", ""))   # a refine keeps its framing
            refine_pass = node.depth - 1
            parent_draft_id = node.parent_id
            # §6.1 provenance: persist the parent review that drove THIS refine
            # and record its ref, so the draft archive is auditable. Content is
            # only as rich as the injected reviewer (empty under the default
            # LLM-free reviewer; populated once Task 03/04's governed
            # paper_reviewer supplies real revisions).
            # Epoch-scoped for the same reason the tex path is: a re-minted
            # node id would otherwise overwrite a prior round's review record.
            suggested_ref = (f"archive/{self.epoch_id}/{node.id}/"
                             f"review.r{refine_pass}.json")
            _rev = getattr(review, "suggested_revisions_json", "") or ""
            _rp = self._abs(suggested_ref)
            _rp.parent.mkdir(parents=True, exist_ok=True)
            _rp.write_text(
                json.dumps({"suggested_revisions_json": _rev},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        tex_abs = str(self._abs(rel_tex))
        score = float(self.reviewer.score(tex_abs))            # TEXT-only, no compile
        node.artifacts = [tex_abs]
        node.has_real_data = True                              # verified-context grounded
        node.metrics = {
            **(node.metrics or {}),
            "_scientific_score": score,                        # frontier + best-belief key
            "_framing_key": framing,                           # diversity_bonus key (§5.2)
            "_paper_epoch_id": self.epoch_id,
            "_reviewer_prompt_hash": getattr(
                self.reviewer, "prompt_hash", ""
            ),
            "_manuscript_input_fingerprint": str(
                manuscript.get("input_fingerprint") or ""
            ),
            "_manuscript_binding_digest": str(
                manuscript.get("binding_digest") or ""
            ),
        }
        record = {
            "schema_version": PAPER_DRAFT_ARCHIVE_SCHEMA_VERSION,
            "draft_id": node.id,
            "node_id": node.id,
            "kind": node.original_direction,                   # seed | refine
            "parent_draft_id": parent_draft_id,
            "refine_pass": refine_pass,
            "tex_path": rel_tex,
            "tex_sha256": _sha256(latex),
            "writer_prompt_hash": framing,
            "reviewer_prompt_hash": getattr(
                self.reviewer, "prompt_hash", ""
            ),
            "review_score": score,
            "suggested_revisions_ref": suggested_ref,          # §6.1
            "anchors_preserved": anchors,
            "decode_seed": decode_seed,
            "epoch_id": self.epoch_id,
            "is_best_belief": False,
            "compiled": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "manuscript_bound": bool(manuscript.get("manuscript_bound", False)),
            "manuscript_mode": str(manuscript.get("mode") or "off"),
            "manuscript_attempt_id": str(manuscript.get("attempt_id") or ""),
            "manuscript_input_fingerprint": str(
                manuscript.get("input_fingerprint") or ""
            ),
            "manuscript_binding_digest": str(
                manuscript.get("binding_digest") or ""
            ),
            "manuscript_profile_digest": str(
                manuscript.get("profile_digest") or ""
            ),
            "manuscript_context_digest": str(
                manuscript.get("context_digest") or ""
            ),
            "manuscript_readiness_digest": str(
                manuscript.get("readiness_digest") or ""
            ),
            "manuscript_brief_bundle_digest": str(
                manuscript.get("brief_bundle_digest") or ""
            ),
            "manuscript_section_brief_digests": list(
                manuscript.get("section_brief_digests") or ()
            ),
            "manuscript_allowed_evidence_ids": list(
                manuscript.get("allowed_evidence_ids") or ()
            ),
            "manuscript_contextual_negative_ids": list(
                manuscript.get("contextual_negative_ids") or ()
            ),
            "manuscript_forbidden_evidence_ids": list(
                manuscript.get("forbidden_evidence_ids") or ()
            ),
            "manuscript_required_disclosures": list(
                manuscript.get("required_disclosures") or ()
            ),
            "manuscript_omission_count": int(
                manuscript.get("omission_count") or 0
            ),
        }
        self._records[node.id] = record
        write_paper_draft_record(self.ckpt, record)
        return node


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
