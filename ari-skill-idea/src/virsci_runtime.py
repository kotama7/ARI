"""ari-skill-idea — Vendor-wrap runtime for VirSci's real discussion mechanism.

Runs VirSci's *actual* deliberation code (``Platform.select_coauthors`` +
``Team.generate_idea`` from ``vendor/virsci/sci_platform``) on a Semantic-
Scholar-derived live snapshot (see ``snapshot.py``), instead of re-implementing
the loop in ``server.py``. Gated behind ``ARI_IDEA_VIRSCI_REAL`` (see server.py).

Three responsibilities (PLAN §2 ②):

  1. Import barrier — VirSci's vendored agentscope eagerly imports ~25 optional
     backends (grpc, llama_index, zhipuai, gradio, dashscope, …) across its
     ``__init__`` cascade. A single meta-path *auto-stubber* fabricates inert
     stand-ins for ONLY the missing backends, so the real ``Platform`` / ``Team``
     / ``SciAgent`` import with **vendor unedited**. Installed packages (openai,
     litellm, numpy, faiss, torch, transformers) are never stubbed.
  2. LLM routing — an in-memory agentscope ``model_configs`` pointing at ARI's
     OpenAI-compatible CLI shim (:8900 /v1), reusing server.py's _model/_api_base.
  3. ``LivePlatform(Platform)`` — overrides ``__init__`` (no faiss.read_index /
     hard-coded corpus / knowledge bank) and ``reference_paper`` (SPECTER2 NN
     over the snapshot corpus).

The driver ``run_virsci_live`` runs the real ``select_coauthors`` (freshness)
then ``generate_idea`` (deliberation) and extracts ideas. All vendor stdout /
loguru output is redirected to a log file so the MCP stdio channel stays clean.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import re
import sys
import types
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np

from snapshot import Snapshot

_VENDOR = Path(__file__).resolve().parent.parent / "vendor" / "virsci"
_SCI_PLATFORM = _VENDOR / "sci_platform"
_AGENTSCOPE_SRC = _VENDOR / "agentscope-main" / "src"

# ── meta-path auto-stubber ────────────────────────────────────────────────────
# Top-level backends referenced by the vendored agentscope that are NOT part of
# this skill's runtime and are never exercised on the idea path. (torch /
# transformers / faiss / openai / numpy are real installs — deliberately absent.)
_MISSING_BACKENDS = {
    "dashscope", "expiringdict", "feedparser", "flask_babel", "flask_cors",
    "flask_socketio", "flask_sqlalchemy", "gradio", "grpc", "inputimeout",
    "llama_index", "modelscope_studio", "nbclient", "nbformat", "ollama",
    "oss2", "pymongo", "pymysql", "sentence_transformers", "socketio",
    "zhipuai",
}
# agentscope's own server-only subpackages (flask studio / gradio web / the
# heavy service toolkit) — replaced wholesale; the idea path needs none of them.
_STUB_SUBPACKAGES = {"agentscope.studio", "agentscope.web", "agentscope.service"}


class _Dummy(types.ModuleType):
    """A permissive stub module: any attribute access fabricates a child type."""

    __path__: list[str] = []  # marks it as a package so submodule import proceeds

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        val = types.new_class(name, (), {})
        setattr(self, name, val)
        return val


class _AutoStubLoader:
    def create_module(self, spec):
        return _Dummy(spec.name)

    def exec_module(self, module):  # noqa: D401 — inert
        return None


def _is_importable(name: str) -> bool:
    """True iff ``name`` resolves to a real, installed top-level module."""
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


class _AutoStubFinder:
    def __init__(self, roots: set[str], subpackages: set[str]) -> None:
        self.roots = roots
        self.subpackages = subpackages

    def _is_target(self, fullname: str) -> bool:
        if fullname.split(".")[0] in self.roots:
            return True
        return fullname in self.subpackages or any(
            fullname.startswith(s + ".") for s in self.subpackages
        )

    def find_spec(self, fullname, path=None, target=None):
        if not self._is_target(fullname):
            return None
        return importlib.util.spec_from_loader(fullname, _AutoStubLoader())


_IMPORTED: tuple | None = None


def _ensure_vendor_on_path() -> None:
    for p in (str(_SCI_PLATFORM), str(_AGENTSCOPE_SRC)):
        if p not in sys.path:
            sys.path.insert(0, p)


def import_virsci():
    """Install the auto-stubber, import vendored VirSci, return key classes.

    Returns ``(agentscope, Platform, Team, SciAgent, Msg)``. Cached after the
    first call. Raises on ImportError so server.py can degrade to the re-impl.
    """
    global _IMPORTED
    if _IMPORTED is not None:
        return _IMPORTED

    _ensure_vendor_on_path()
    if not any(isinstance(f, _AutoStubFinder) for f in sys.meta_path):
        # Only stub backends that are GENUINELY absent — never shadow a package
        # that is actually installed. This finder sits at meta_path[0] for the
        # whole long-lived MCP-server process, so stubbing a real name (e.g.
        # grpc / feedparser / nbformat, which exist in richer envs and are
        # imported lazily by opentelemetry / google-cloud / litellm callbacks)
        # would silently break unrelated code after a live run. The deliberate
        # agentscope subpackage replacements (_STUB_SUBPACKAGES) are always
        # stubbed regardless — we replace them even though they are importable.
        roots = {n for n in _MISSING_BACKENDS if not _is_importable(n)}
        sys.meta_path.insert(0, _AutoStubFinder(roots, _STUB_SUBPACKAGES))

    import agentscope  # runs the vendored package __init__
    _patch_agentscope_logging()
    from agentscope.agents import SciAgent
    from agentscope.message import Msg
    from sci_platform import Platform  # the module file (no __init__.py package)
    from sci_team.SciTeam import Team

    _IMPORTED = (agentscope, Platform, Team, SciAgent, Msg)
    return _IMPORTED


def _patch_agentscope_logging() -> None:
    """Replace the studio/gradio globals ``agentscope.logging`` uses at runtime.

    ``logging.py`` does ``from .studio._client import _studio_client`` and
    ``from .web.gradio.utils import (...)`` — both auto-stubbed. ``Msg.__init__``
    funnels through ``logger.chat`` → ``log_msg`` which reads
    ``_studio_client.active`` and ``thread_local_data.uid``. The auto-stubber's
    fabricated classes lack these, so we bind inert, correctly-shaped stand-ins
    onto the already-imported logging module globals (precise; no effect on the
    import-time stub behaviour).
    """
    try:
        import agentscope.logging as _aslog
    except Exception:
        return

    class _InertStudioClient:
        active = False

        def push_message(self, *a, **k):
            return None

    class _InertThreadLocal:  # no ``uid`` attr → log_gradio short-circuits
        pass

    _aslog._studio_client = _InertStudioClient()
    _aslog.thread_local_data = _InertThreadLocal()
    _aslog.generate_image_from_name = lambda *a, **k: None
    _aslog.send_msg = lambda *a, **k: None
    _aslog.get_reset_msg = lambda *a, **k: None


# ── ARI shim model_configs ────────────────────────────────────────────────────

def build_model_configs(model: str, api_base: str | None, config_name: str = "ari_virsci_shim") -> dict:
    """An agentscope ``litellm_chat`` config — engine LLM calls flow through the
    SAME litellm path as server._llm, so they route to the ARI shim AND are
    captured by ARI's cost_tracker (which wraps ``litellm.completion`` —
    closing risk #5: cost attribution for the real-engine calls).

    ``model`` is the litellm-format model id (e.g. ``openai/claude-cli``, kept
    verbatim — litellm needs the provider prefix), and ``api_base`` is forwarded
    via ``generate_args`` exactly as server._llm passes it to litellm. litellm
    reads the API key from ``OPENAI_API_KEY`` (set by the launcher / shim), so
    no key is embedded in the config.
    """
    cfg: dict[str, Any] = {
        "config_name": config_name,
        "model_type": "litellm_chat",
        "model_name": model,
    }
    gen: dict[str, Any] = {}
    if api_base:
        gen["api_base"] = api_base
    if gen:
        cfg["generate_args"] = gen
    return cfg


# ── SPECTER2 query embedder (local, CPU) ──────────────────────────────────────

class _Specter2Embedder:
    """Lazy local SPECTER2 embedder for discussion-time queries (CLS pooling)."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._tok = None
        self._model = None

    def _ensure(self) -> bool:
        if self._model is not None:
            return True
        try:
            import torch  # noqa: F401
            from transformers import AutoModel, AutoTokenizer

            self._tok = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModel.from_pretrained(self.model_name)
            self._model.eval()
            return True
        except Exception:
            return False

    def embed(self, text: str) -> np.ndarray | None:
        if not text or not self._ensure():
            return None
        try:
            import torch

            inputs = self._tok(
                text, padding=True, truncation=True, max_length=512, return_tensors="pt",
            )
            with torch.no_grad():
                out = self._model(**inputs)
            vec = out.last_hidden_state[:, 0, :].squeeze(0).numpy().astype("float32")
            n = np.linalg.norm(vec)
            return vec / n if n else vec
        except Exception:
            return None


# ── LivePlatform ──────────────────────────────────────────────────────────────

def make_live_platform_cls():
    """Build the ``LivePlatform`` subclass after the vendor is importable."""
    agentscope, Platform, Team, SciAgent, Msg = import_virsci()

    class LivePlatform(Platform):
        """``Platform`` grounded on an S2 snapshot — no FAISS files / corpus paths."""

        def __init__(
            self,
            snapshot: Snapshot,
            model_configs: dict | list,
            *,
            group_max_discuss_iteration: int = 7,
            max_teammember: int = 3,
            cite_number: int = 8,
            agent_num: int | None = None,
            team_limit: int = 2,
            over_state: int = 8,
            log_dir: str = "virsci_logs",
            info_dir: str = "virsci_team_info",
            specter2_model: str = "allenai/specter2_base",
            ancestor_block: str = "",
        ) -> None:
            self.snapshot = snapshot
            self.log_dir = log_dir
            self.info_dir = info_dir
            self._ancestor_block = ancestor_block or ""
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            Path(info_dir).mkdir(parents=True, exist_ok=True)

            # freshness source: integer co-author adjacency from the snapshot
            self.adjacency_matrix = np.loadtxt(str(snapshot.adjacency_path), dtype=int)
            if self.adjacency_matrix.ndim == 0:  # 1×1 degenerate
                self.adjacency_matrix = self.adjacency_matrix.reshape(1, 1)
            n_total = len(self.adjacency_matrix)
            # select_coauthors samples co-authors via arr/sum(arr); a 1-author
            # snapshot has an all-zero row → NaN probabilities. The snapshot
            # builder already floors authors at 2, but guard here so a malformed
            # snapshot degrades cleanly (caller catches → re-impl) instead of
            # raising an opaque ValueError deep inside the vendor.
            if n_total < 2:
                raise ValueError(
                    f"VirSci-live needs >=2 authors in the snapshot, got {n_total}",
                )
            self.agent_num = min(agent_num, n_total) if agent_num else n_total

            # vendor knobs
            self.group_max_discuss_iteration = group_max_discuss_iteration
            self.recent_n_team_mem_for_retrieve = 1
            self.team_limit = team_limit
            self.max_teammember = min(max_teammember, max(1, n_total - 1))
            self.cite_number = cite_number
            self.over_state = over_state
            self.begin_state = 1
            self.reviewer_num = 0
            self.default_mark = 4
            self.skip_check = True  # we stop after generate_idea (state→5)
            self.think_times = self.max_teammember + 1
            self.degree_int2word = ["one", "two", "three", "four", "five"]

            # LLM routing → ARI shim (registers configs in the ModelManager)
            agentscope.init(model_configs=model_configs, disable_saving=True)
            self._model_config_name = (
                model_configs[0]["config_name"]
                if isinstance(model_configs, list)
                else model_configs["config_name"]
            )

            # silence loguru's stdout sink so the MCP stdio channel stays clean
            try:
                from loguru import logger as _lg

                _lg.remove()
                _lg.add(str(Path(log_dir) / "virsci_loguru.log"), level="WARNING")
            except Exception:
                pass

            self.knowledge_bank = None
            self.HostMsg = partial(Msg, name="user", role="user", echo=True)

            # diversity source: one SciAgent per author, sys_prompt = profile text
            self.agent_pool = [
                self._init_live_agent(i) for i in range(n_total)
            ]
            self.reviewer_pool = []
            self.id2agent = {agent.name: agent for agent in self.agent_pool}

            # singleton team per agent (mirrors Platform.__init__)
            self.team_pool = []
            for aid, agent in enumerate(self.agent_pool, start=1):
                team_dic = Team(
                    team_name=f"{aid},1", log_dir=self.log_dir, info_dir=self.info_dir,
                )
                team_dic.teammate = [agent.name]
                self.team_pool.append([team_dic])

            # SPECTER2 retrieval over the snapshot corpus
            self._faiss_index = snapshot.build_faiss_index()
            self._corpus = snapshot.corpus
            self.paper_dicts = snapshot.paper_dicts
            self._embedder = _Specter2Embedder(specter2_model)

            self._Team = Team

        def _init_live_agent(self, agent_id: int):
            book = self.snapshot.books_dir / f"author_{agent_id}.txt"
            try:
                sys_prompt = book.read_text()
            except Exception:
                sys_prompt = f"You are Scientist{agent_id}, a researcher."
            # Inject lineage/ancestor context (Phase-2) so the real path's agents
            # stay aware of prior research directions, mirroring the re-impl loop.
            # vendor is untouched — this is a wrapper-layer sys_prompt append only.
            if self._ancestor_block:
                sys_prompt = f"{sys_prompt}\n\n{self._ancestor_block}"
            return SciAgent(
                name=f"Scientist{agent_id}",
                model_config_name=self._model_config_name,
                sys_prompt=sys_prompt,
                knowledge_list=[],            # no knowledge bank → RAG is a no-op
                knowledge_id_list=[],
                similarity_top_k=2,
                log_retrieval=False,
                recent_n_mem_for_retrieve=2,
            )

        # ── overridden retrieval: SPECTER2 NN over the snapshot corpus ──────────
        def reference_paper(self, key_string, cite_number):
            idxs: list[int] = []
            if self._faiss_index is not None and len(self._corpus) > 0:
                qv = self._embedder.embed(key_string)
                if qv is not None:
                    q = qv.reshape(1, -1).astype("float32")
                    k = min(cite_number, len(self._corpus))
                    _, indices = self._faiss_index.search(q, k)
                    idxs = [int(i) for i in indices[0] if 0 <= int(i) < len(self._corpus)]
            if not idxs:
                idxs = self._keyword_fallback(key_string, cite_number)

            ref = ""
            for rank, i in enumerate(idxs):
                rec = self._corpus[i] if i < len(self._corpus) else self.paper_dicts[i]
                ref += f"Paper {rank + 1}:\n"
                ref += f"Title: {rec.get('title', '')}\n"
                ref += f"Abstract: {rec.get('abstract', '')}}}\n"
            return ref, np.array(idxs)

        def _keyword_fallback(self, key_string: str, cite_number: int) -> list[int]:
            pool = self._corpus or self.paper_dicts
            if not pool:
                return []
            terms = {t for t in re.findall(r"[a-zA-Z]{4,}", (key_string or "").lower())}
            scored = []
            for i, rec in enumerate(pool):
                blob = f"{rec.get('title','')} {rec.get('abstract','')}".lower()
                scored.append((sum(1 for t in terms if t in blob), i))
            scored.sort(reverse=True)
            return [i for _, i in scored[: min(cite_number, len(pool))]]

    return LivePlatform


# ── idea parsing ──────────────────────────────────────────────────────────────

def _parse_idea(raw: str) -> dict | None:
    """Parse one VirSci idea string → normalised idea dict (scores 0-1)."""
    if not raw:
        return None
    body = raw
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    data: dict = {}
    if m:
        try:
            data = json.loads(m.group(0))
        except Exception:
            data = {}

    def _num(key: str, default: float = 5.0) -> float:
        if key in data:
            try:
                return float(data[key])
            except Exception:
                pass
        mm = re.search(rf"{key}[^0-9]*([0-9]+(?:\.[0-9]+)?)", body, re.IGNORECASE)
        return float(mm.group(1)) if mm else default

    title = data.get("Title") or data.get("title")
    if not title:
        tm = re.search(r"Title[\"'\s:]+([^\n\"']+)", body, re.IGNORECASE)
        title = tm.group(1).strip() if tm else "Research Idea"
    description = data.get("Idea") or data.get("idea") or data.get("Description") or body[:600]
    experiment = data.get("Experiment") or data.get("experiment") or ""

    nov = min(_num("Novelty"), 10) / 10
    feas = min(_num("Feasibility"), 10) / 10
    clar = min(_num("Clarity"), 10) / 10
    return {
        "title": str(title).strip()[:300],
        "description": str(description).strip(),
        "experiment_plan": str(experiment).strip(),
        "novelty_score": nov,
        "feasibility_score": feas,
        "clarity_score": clar,
        "_raw": raw,
    }


def _collect_team_ideas(team) -> list[str]:
    idea = getattr(team, "idea", None)
    if idea is None:
        return []
    if isinstance(idea, str):
        return [idea]
    if isinstance(idea, list):
        return [s for s in idea if isinstance(s, str)]
    return []


# ── driver ────────────────────────────────────────────────────────────────────

def run_virsci_live(
    topic: str,
    snapshot: Snapshot,
    *,
    model: str,
    api_base: str | None,
    n_ideas: int = 3,
    k: int = 7,
    team_size: int = 3,
    n_authors: int = 16,
    cite_number: int = 8,
    max_teams: int | None = None,
    ancestor_block: str = "",
    log_dir: str = "virsci_logs",
    specter2_model: str = "allenai/specter2_base",
) -> dict:
    """Run VirSci's real select_coauthors + generate_idea on the snapshot.

    ``model`` / ``api_base`` are the resolved ARI LLM config (server.py's
    ``_model()`` / ``_api_base()``), passed in by the caller so this module
    never re-imports ``server`` (which is ``__main__`` in the running skill).
    ``ancestor_block`` is the lineage context (server.py Phase-2 ancestor pool);
    it is appended to every agent's sys_prompt so the real path stays aware of
    prior research directions, matching the re-impl loop.

    Returns ``{"ideas": [...], "n_agents": int, "discussion_rounds": int,
    "teams_run": int, "papers_indexed": int}``. All vendor stdout / prints are
    redirected to ``<log_dir>/virsci_stdout.log`` to protect the MCP channel.
    """
    model_configs = build_model_configs(model, api_base)
    LivePlatform = make_live_platform_cls()

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    stdout_log = open(Path(log_dir) / "virsci_stdout.log", "a")  # noqa: SIM115

    ideas_raw: list[str] = []
    team_sizes: list[int] = []
    teams_run = 0
    try:
        with contextlib.redirect_stdout(stdout_log), contextlib.redirect_stderr(stdout_log):
            platform = LivePlatform(
                snapshot,
                model_configs,
                group_max_discuss_iteration=k,
                max_teammember=team_size,
                cite_number=cite_number,
                agent_num=n_authors,
                log_dir=log_dir,
                info_dir=str(Path(log_dir) / "team_info"),
                specter2_model=specter2_model,
                ancestor_block=ancestor_block,
            )
            # freshness: real team formation over the co-author graph
            team_pool = platform.select_coauthors()

            # gather formed teams, prefer multi-member (the deliberation teams)
            teams: list = []
            for agent_teams in team_pool:
                for team in agent_teams:
                    if getattr(team, "state", 0) != platform.over_state and team.teammate:
                        teams.append(team)
            teams.sort(key=lambda t: len(t.teammate), reverse=True)
            budget = max_teams if max_teams else max(n_ideas, 2)
            teams = teams[:budget]

            for team in teams:
                team.topic = f"Selected Topics: {topic}"
                try:
                    team.generate_idea(platform)
                except Exception:
                    continue
                got = _collect_team_ideas(team)
                if got:
                    ideas_raw.extend(got)
                    team_sizes.append(len(team.teammate))
                    teams_run += 1
    finally:
        with contextlib.suppress(Exception):
            stdout_log.close()

    parsed = [p for p in (_parse_idea(r) for r in ideas_raw) if p]
    # score = Novelty*2 + Feasibility + Clarity (VirSci), descending
    parsed.sort(
        key=lambda x: x["novelty_score"] * 2 + x["feasibility_score"] + x["clarity_score"],
        reverse=True,
    )
    # dedup by normalised title
    seen: set[str] = set()
    deduped: list[dict] = []
    for p in parsed:
        key = " ".join(p["title"].lower().split())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)

    n_agents = max(team_sizes) if team_sizes else team_size
    return {
        "ideas": deduped[:n_ideas],
        "n_agents": n_agents,
        "discussion_rounds": k,
        "teams_run": teams_run,
        "papers_indexed": len(snapshot.corpus),
    }


if __name__ == "__main__":  # Phase 0 de-risk spike entry point
    import traceback

    try:
        ag, Platform, Team, SciAgent, Msg = import_virsci()
        print("IMPORT OK:", Platform.__name__, Team.__name__, SciAgent.__name__, Msg.__name__)
    except Exception:
        print("IMPORT FAILED:")
        traceback.print_exc()
        sys.exit(1)
