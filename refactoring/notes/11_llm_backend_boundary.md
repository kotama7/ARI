# LLM Backend Boundary (requirement 11)

Task-control note from `11_llm_backend_boundary.md`. Captured 2026-05-30 from a
repo-wide audit of LLM/provider usage. **Audit/documentation only** — the audit
found the boundary is already sound, so no production code changed and no new
guard test was added (see §5 for why a naive guard would be wrong).

## 1. The actual boundary: litellm + the cost_tracker injector + resolve_litellm_model

ARI's LLM boundary is **not** "everything must call `ari.public.llm.LLMClient`".
It is a three-part pattern, and direct `litellm.{completion,acompletion}` calls
are the **sanctioned** shape:

1. **`litellm`** is the provider-abstraction layer. Modules call
   `litellm.completion` / `litellm.acompletion` directly with a model id.
2. **`ari.llm.routing.resolve_litellm_model(model, backend)`** is the single
   model-normalisation helper — it applies the provider prefix (incl. the
   CLI-shim `openai/claude-cli` rule) so a bare model name routes correctly.
3. **`ari.cost_tracker._install_litellm_metadata_injector()`** monkey-patches
   `litellm.completion`/`acompletion` **process-wide** to (a) merge default
   cost metadata (skill/phase/node) and (b) call `_apply_ari_routing`
   (`resolve_litellm_model` + cli-shim `api_base` fill-in) on every call. So
   once installed, *every* direct litellm call — from any module or skill —
   gets ARI routing + cost capture transparently, at one point.

`ari.llm.client.LLMClient` is a **convenience wrapper** over `litellm.completion`
(it calls `resolve_litellm_model` itself, client.py:68) used by the ReAct agent
loop — it is NOT a mandatory chokepoint, and the codebase deliberately does not
funnel everything through it.

The injector is installed by `cost_tracker.set_default_metadata` /
`init_from_env`, reached via `bootstrap_skill("<name>")` at the top of every
skill `server.py` (the block migrated to public-first in req 09).

## 2. Usage classification

| Site | Calls | Verdict |
|------|-------|---------|
| `ari/llm/client.py` (`LLMClient`) | litellm + `resolve_litellm_model` | **boundary** (the canonical wrapper; ReAct path) |
| `ari/llm/cli_server.py` | OpenAI-compatible shim server (`:8900`) | **infra** — sanctioned (§3 out-of-scope to change) |
| `ari/viz/api_ollama.py` | Ollama proxy / resource probe | **infra** — sanctioned |
| `ari/cost_tracker.py` | patches litellm; `import litellm` | **boundary infra** (the injector) |
| `ari/evaluator/llm_evaluator.py:585` | `litellm.acompletion` + own `api_base` | acceptable (judge; routed via injector when installed) |
| `ari/orchestrator/lineage_decision.py:321`, `root_idea_selector.py:169` | `litellm.acompletion` + own `api_base` | acceptable (LLM judges) |
| `ari/pipeline/context_builder.py:136` | `litellm.completion` (own model/backend + OLLAMA_HOST `api_base`) | acceptable-but-noted: the one pipeline-package direct call; does its own env resolution rather than `resolve_litellm_model`. Low-value seam (req 10 §7.4). |
| `ari/viz/api_tools.py:89` | `litellm.completion` (wizard chat/config-gen) | acceptable (viz helper) |
| skills: paper, plot, idea, evaluator, replicate, paper-re, vlm(via paper) | `litellm.acompletion` (+ `bootstrap_skill` injector) | **acceptable** — the sanctioned pattern; routing+cost via the injector each installs at import |
| `ari-skill-paper-re/src/_litellm_completer.py`, `_paperbench_bridge.py` | `litellm` + `openai` types; `AsyncOpenAI` | acceptable — vendored PaperBench bridge (TurnCompleter); intentional, do not touch |

No provider call was found that *circumvents* routing in a way that would change
which provider/model/key is used — the injector + per-caller `api_base` cover it.

## 3. The one real fragility (documented, not "fixed")

The CLI-shim routing and cost capture depend on the **injector being installed
before the first litellm call** in that process. Skills guarantee this via
`bootstrap_skill` at import. Core CLI/pipeline modules
(`lineage_decision`/`root_idea_selector`/`evaluator`/`context_builder`) call
litellm directly and **pass `api_base`/model themselves**, so they route
correctly even if the global injector is not installed — but they would miss the
cost-metadata merge if `init_from_env` had not run in that process. This is a
latent ordering dependency, not a correctness bug for routing. (Ties to the
req-13 "LLM error/fallback" coverage gap.)

## 4. Compatibility check

No model selection, routing, prompt, or provider-response behavior changed.
`api_ollama.py`, settings-driven model/provider, and the `:8900` CLI shim are
untouched. No code changed at all — this requirement is an audit.

## 5. Why NO new guard test (and why the §12 idea would be wrong)

Req-11 §12 floats "a guard test asserting domain modules import only
`ari.public.llm` / `ari.llm`." **That guard would be incorrect here**: it would
flag the entire sanctioned `litellm.acompletion`-direct pattern across ~7 skills
and ~5 core modules as violations, when that pattern *is* the architecture (the
boundary is enforced by the runtime injector + `resolve_litellm_model`, not by
import discipline). Adding it would create pressure to do exactly the
out-of-scope `LLMClient` rewrite §3/§11 forbid.

The real boundary contract is **already comprehensively guard-tested** by
`ari-core/tests/test_llm_routing.py`: `resolve_litellm_model` prefix rules +
idempotency + env-backend fallback + empty-model; `_apply_ari_routing` cli-shim
prefix/api_base fill, no-overwrite, real-openai-unchanged, anthropic-no-api_base;
and the injector normalising a skill litellm call. No gap to fill.

## 6. Follow-up candidates (→ §12)

- **PROPOSE-ONLY** (a dedicated, separately-justified requirement, not this one):
  route `context_builder._extract_keywords_from_nodes` through `LLMClient` (or at
  least `resolve_litellm_model`) so the one pipeline direct call shares the
  canonical resolution. Behavior-neutral only if the model/backend/api_base
  resolution is proven identical first (req 11 §11 warns routing is subtle).
- A broader "should everything use `LLMClient`?" question is explicitly **not**
  pursued — the litellm-direct + injector pattern is the working design; changing
  it is a large behavior-risking rewrite outside this requirement's scope.
- If the injector ordering dependency (§3) ever bites, add an explicit
  `init_from_env()` at the core CLI entrypoint — a behavior change needing its own
  justification + test.
