#!/usr/bin/env bash
# ============================================================================
# setup_env.sh — .env bootstrap
#   * Creates or updates ARI/.env with every env var the program reads.
#   * Prompts interactively for critical API keys (OPENAI/ANTHROPIC/GOOGLE/S2)
#     when they are missing. Keys already present are left untouched.
#   * All non-key variables are written with commented defaults.
# ============================================================================

ENV_FILE="$ARI_ROOT/.env"

echo ""
echo -e "${BOLD}  🐜 $(m setup_env_title)${RESET}"
echo ""

# --- helpers ----------------------------------------------------------------
# Read an existing value for KEY from $ENV_FILE (empty string if missing / unset).
_env_get() {
  local key="$1"
  [ -f "$ENV_FILE" ] || { echo ""; return; }
  local line
  line=$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" | tail -1 || true)
  [ -z "$line" ] && { echo ""; return; }
  local val="${line#*=}"
  val="${val%\"}"; val="${val#\"}"
  val="${val%\'}"; val="${val#\'}"
  echo "$val"
}

# True if $ENV_FILE already has a non-empty value for KEY.
_env_has() {
  local key="$1"
  local v
  v=$(_env_get "$key")
  [ -n "$v" ]
}

# Append "KEY=VALUE" only if KEY is not already present (commented or not).
_env_append_if_absent() {
  local line="$1"
  local key="${line%%=*}"
  key="${key# }"; key="${key#\#}"; key="${key# }"
  key="${key%%=*}"
  if ! grep -qE "^[[:space:]]*#?[[:space:]]*${key}=" "$ENV_FILE" 2>/dev/null; then
    printf '%s\n' "$line" >> "$ENV_FILE"
  fi
}

_env_section() {
  local title="$1"
  if ! grep -qF "# --- $title ---" "$ENV_FILE" 2>/dev/null; then
    printf '\n# --- %s ---\n' "$title" >> "$ENV_FILE"
  fi
}

# Prompt for a secret when stdin is a TTY; otherwise skip silently.
_prompt_secret() {
  local key="$1"; local label="$2"
  if _env_has "$key"; then
    ok "$key $(m setv_already_set)"
    return
  fi
  if [ ! -t 0 ]; then
    info "$key $(m setv_skip_noninteractive)"
    _env_append_if_absent "# ${key}="
    return
  fi
  echo ""
  printf "  🐜 %s [%s] (%s): " "$label" "$key" "$(m setv_enter_skip)"
  local val=""
  # -s hides input; fall back to plain read if -s is unsupported
  if read -rs val 2>/dev/null; then echo ""; else read -r val; fi
  if [ -n "$val" ]; then
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
    ok "$key $(m setv_saved)"
  else
    _env_append_if_absent "# ${key}="
    info "$key $(m setv_skipped)"
  fi
}

# Delete every line in $ENV_FILE that defines KEY (commented or not).
# Used by reprompts that need to overwrite a dead default such as
# LETTA_EMBEDDING_CONFIG=letta-default.
_env_delete_key() {
  local key="$1"
  [ -f "$ENV_FILE" ] || return 0
  # POSIX-portable in-place: write to a temp and replace.
  local tmp
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")" || return 1
  grep -vE "^[[:space:]]*#?[[:space:]]*${key}=" "$ENV_FILE" > "$tmp" || true
  mv "$tmp" "$ENV_FILE"
}

# Prompt for a plain (non-secret) value with a default. Locks in the value
# uncommented in $ENV_FILE so install_letta.sh / runtime can pick it up
# deterministically.
#
# Usage: _prompt_value KEY LABEL DEFAULT [HINT]
#
# Behaviour:
#   * If KEY is already set in .env to a value other than DEFAULT and not
#     in the list of known-dead values: keep it, skip the prompt.
#   * Non-interactive (no TTY or ARI_NONINTERACTIVE=1): write `# KEY=`
#     placeholder when missing; never overwrite an existing value.
#   * Interactive: show current (if any) + default, accept Enter to keep
#     the current value, or accept any string as the new value.
_prompt_value() {
  local key="$1"; local label="$2"; local default="$3"; local hint="${4:-}"
  local current
  current="$(_env_get "$key")"

  if [[ "${ARI_NONINTERACTIVE:-0}" == "1" ]] || [ ! -t 0 ]; then
    if [ -z "$current" ]; then
      info "$key $(m setv_skip_noninteractive)"
      _env_append_if_absent "# ${key}=${default}"
    else
      ok "$key $(m setv_already_set)"
    fi
    return
  fi

  echo ""
  if [ -n "$hint" ]; then
    printf "  🐜 %s\n" "$hint"
  fi
  if [ -n "$current" ]; then
    printf "  🐜 %s [%s] %s: %s\n" "$label" "$key" "$(m setv_current)" "$current"
    printf "  🐜 (%s, %s): " \
      "$(m setv_enter_keep)" "$(m setv_or_replace)"
  else
    printf "  🐜 %s [%s]\n" "$label" "$key"
    printf "  🐜 (%s: %s): " "$(m setv_default)" "$default"
  fi

  local val=""
  read -r val || val=""
  if [ -z "$val" ]; then
    val="${current:-$default}"
  fi

  _env_delete_key "$key"
  printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  ok "$key=$val $(m setv_saved)"
}

# Prompt for one of a known set of choices, with the option to type a
# custom value. The first option in OPTIONS is the default.
#
# Usage: _prompt_choice KEY LABEL HINT OPT1 OPT2 ...
#
# Behaviour mirrors _prompt_value, with two extensions:
#   * Numeric input "1".."N" picks options[N-1].
#   * Any non-numeric, non-empty input is taken as a custom value (e.g.
#     a self-hosted Ollama embedding handle the user has registered).
_prompt_choice() {
  local key="$1"; local label="$2"; local hint="$3"
  shift 3
  local opts=("$@")
  local default="${opts[0]}"
  local current
  current="$(_env_get "$key")"

  # Detect known-dead values and force a reprompt even when the key is
  # already set. The Letta-hosted free embedding endpoint started
  # returning HTTP 404 for /v1/embeddings sometime after the MemGPT →
  # Letta rebrand, so preserving these silently leaves writes broken.
  local force=0
  case "$current" in
    "letta-default"|"letta/letta-free"|"")
      force=1 ;;
  esac

  if [[ "${ARI_NONINTERACTIVE:-0}" == "1" ]] || [ ! -t 0 ]; then
    if [ -z "$current" ]; then
      info "$key $(m setv_skip_noninteractive)"
      _env_append_if_absent "# ${key}=${default}"
    elif [ "$force" -eq 1 ]; then
      warn "$key=${current} $(m setv_letta_emb_dead) — $(m setv_skip_noninteractive)"
    else
      ok "$key $(m setv_already_set)"
    fi
    return
  fi

  if [ "$force" -eq 0 ]; then
    ok "$key $(m setv_already_set) ($current)"
    return
  fi

  echo ""
  if [ -n "$hint" ]; then
    printf "  🐜 %s\n" "$hint"
  fi
  if [ -n "$current" ]; then
    printf "  🐜 %s [%s] %s: %s\n" "$label" "$key" "$(m setv_current)" "$current"
    if [ "$current" = "letta-default" ] || [ "$current" = "letta/letta-free" ]; then
      printf "  🐜 ⚠ %s\n" "$(m setv_letta_emb_dead)"
    fi
  else
    printf "  🐜 %s [%s]\n" "$label" "$key"
  fi
  local i=0
  for opt in "${opts[@]}"; do
    if [ "$i" -eq 0 ]; then
      printf "    %d) %s  (%s)\n" "$((i+1))" "$opt" "$(m setv_default)"
    else
      printf "    %d) %s\n" "$((i+1))" "$opt"
    fi
    i=$((i+1))
  done
  printf "  🐜 %s: " "$(m setv_pick_or_custom)"

  local sel=""
  read -r sel || sel=""

  local val=""
  if [ -z "$sel" ]; then
    val="$default"
  elif [[ "$sel" =~ ^[0-9]+$ ]] && [ "$sel" -ge 1 ] && [ "$sel" -le "${#opts[@]}" ]; then
    val="${opts[$((sel-1))]}"
  else
    val="$sel"
  fi

  _env_delete_key "$key"
  printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  ok "$key=$val $(m setv_saved)"
}

# --- create file if missing -------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  info "$(m setv_creating) $ENV_FILE"
  {
    echo "# ============================================================"
    echo "# ARI environment file — auto-generated by setup.sh"
    echo "# Uncomment and edit values as needed. Secrets are never echoed."
    echo "# ============================================================"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE" 2>/dev/null || true
else
  ok "$(m setv_found) $ENV_FILE"
fi

# --- 1) API keys: prompt if missing -----------------------------------------
_env_section "API keys"
_prompt_secret "OPENAI_API_KEY"          "OpenAI API key"
_prompt_secret "ANTHROPIC_API_KEY"       "Anthropic API key"
_prompt_secret "GOOGLE_API_KEY"          "Google (Gemini) API key"
_prompt_secret "S2_API_KEY"              "Semantic Scholar API key"
_env_append_if_absent "# SEMANTIC_SCHOLAR_API_KEY="

# --- 2) LLM / backend (defaults) -------------------------------------------
_env_section "LLM / backend"
_env_append_if_absent "# ARI_BACKEND=ollama"
_env_append_if_absent "# ARI_MODEL=qwen3:8b"
_env_append_if_absent "# ARI_LLM_MODEL="
_env_append_if_absent "# ARI_LLM_API_BASE="
_env_append_if_absent "# LLM_MODEL="
_env_append_if_absent "# LLM_API_BASE="
_env_append_if_absent "# OLLAMA_HOST=http://localhost:11434"
_env_append_if_absent "# OLLAMA_BASE_URL=http://localhost:11434"

# --- 2b) Per-phase LLM model overrides --------------------------------------
# These win over ARI_MODEL/ARI_LLM_MODEL within their phase. Leave blank to
# use the global model. The GUI Settings page writes these automatically.
_env_append_if_absent "# ARI_MODEL_IDEA="
_env_append_if_absent "# ARI_MODEL_CODING="
_env_append_if_absent "# ARI_MODEL_EVAL="
_env_append_if_absent "# ARI_MODEL_PAPER="
_env_append_if_absent "# ARI_MODEL_BFTS="
# v0.6.0 §4.1 split the legacy ARI_MODEL_PAPER into rubric / replicator / judge
# so the reproducibility pipeline can target a different model per stage.
_env_append_if_absent "# ARI_MODEL_RUBRIC_GEN="
_env_append_if_absent "# ARI_MODEL_RUBRIC_AUDIT="
_env_append_if_absent "# ARI_MODEL_REPLICATE="
_env_append_if_absent "# ARI_MODEL_REPLICATOR="
_env_append_if_absent "# ARI_MODEL_JUDGE="
# Rubric generator knobs (consumed by ari-skill-replicate). All three fall
# back to defaults baked into the generator when unset; the GUI wizard can
# write these per-run.
_env_append_if_absent "# ARI_RUBRIC_GEN_TARGET_LEAVES="
_env_append_if_absent "# ARI_RUBRIC_GEN_TEMPERATURE="
_env_append_if_absent "# ARI_RUBRIC_GEN_TWO_STAGE="
# v0.7.2 paper-audit knobs. _DIR overrides the search root for
# venue-conditioned PaperBench rubric templates (default: ari-core/config/
# paperbench_rubrics/). _PAPER toggles the multimodal markdown image
# expander in the LiteLLM completer (default on). _MAX_IMAGES caps the
# number of figures attached per judge message (default 20) to bound
# token spend on vision-capable models.
_env_append_if_absent "# ARI_PAPERBENCH_RUBRIC_DIR="
_env_append_if_absent "# ARI_MULTIMODAL_PAPER="
_env_append_if_absent "# ARI_MULTIMODAL_MAX_IMAGES="
# Replicator (PaperBench BasicAgent / IterativeAgent) knobs. time-limit
# defaults to 12 h to match upstream; iterative=1 disables the submit tool
# so the agent uses its full budget; max_steps=0 means unlimited.
_env_append_if_absent "# ARI_REPLICATOR_TIME_LIMIT_SEC="
_env_append_if_absent "# ARI_REPLICATOR_ITERATIVE="
_env_append_if_absent "# ARI_REPLICATOR_MAX_STEPS="
# SimpleJudge knob. n_runs defaults to 1 to match PaperBench paper §4.1
# (single-pass judging); raise for variance reduction at the cost of
# grading API spend.
_env_append_if_absent "# ARI_JUDGE_N_RUNS="
# lineage decisions (LLM judge picks continue / switch / fanout /
# terminate during BFTS) and root idea selection (LLM picks ideas[0] from
# the VirSci pool). When unset, both fall back through ARI_MODEL_EVAL →
# ARI_MODEL → ARI_LLM_MODEL → gpt-4o-mini.
_env_append_if_absent "# ARI_MODEL_LINEAGE="
_env_append_if_absent "# ARI_MODEL_ROOT_SELECT="
# lineage decisions: recursion budget surfaced to the lineage_decision judge so
# it avoids switch_to_idea / fanout when the next child would exceed
# the configured max. Set automatically by api_orchestrator at sub-
# experiment launch — users do not normally override it.
_env_append_if_absent "# ARI_RECURSION_DEPTH="

# --- 3) VLM review ----------------------------------------------------------
_env_section "VLM review"
_env_append_if_absent "# VLM_MODEL=openai/gpt-4o"
_env_append_if_absent "# VLM_REVIEW_ENABLED=true"
_env_append_if_absent "# VLM_REVIEW_THRESHOLD=0.7"
_env_append_if_absent "# VLM_REVIEW_MAX_ITER=3"

# --- 4) ARI paths -----------------------------------------------------------
_env_section "ARI paths"
_env_append_if_absent "# ARI_ROOT=${ARI_ROOT}"
_env_append_if_absent "# ARI_WORK_DIR=/tmp/ari_work"
_env_append_if_absent "# ARI_WORKSPACE="
_env_append_if_absent "# ARI_CHECKPOINT_DIR="
_env_append_if_absent "# ARI_LOG_DIR="
_env_append_if_absent "# ARI_LOG_LEVEL=INFO"
_env_append_if_absent "# ARI_SOURCE_FILE="
# v0.6.0 removed the local JSONL store.
# These legacy keys have no effect and are kept as comments so upgraders
# can delete them manually.
_env_append_if_absent "# ARI_MEMORY_PATH=  # (v0.5.x legacy — ignored under v0.6.0)"
_env_append_if_absent "# ARI_GLOBAL_MEMORY_PATH=  # (v0.5.x legacy — global memory was removed)"

# --- 4b) Memory (Letta) -----------------------------------------------------
# Letta is the sole production memory backend as of v0.6.0.
_env_section "Memory (Letta)"
_env_append_if_absent "# LETTA_BASE_URL=http://localhost:8283"
_env_append_if_absent "# LETTA_API_KEY="

# Embedding handle — the historical default `letta-default` (= `letta/letta-free`)
# now resolves to https://inference.letta.com/v1/embeddings, which has been
# silently retired (every model returns 404). Lock in a working handle here
# so archival_insert / add_memory don't fail at run time. Existing dead
# values (`letta-default`, `letta/letta-free`) are detected and reprompted.
_env_append_if_absent "# LETTA_EMBEDDING_CONFIG=openai/text-embedding-3-small"
_prompt_choice "LETTA_EMBEDDING_CONFIG" \
  "$(m setv_letta_emb_label)" \
  "$(m setv_letta_emb_hint)" \
  "openai/text-embedding-3-small" \
  "openai/text-embedding-3-large" \
  "openai/text-embedding-ada-002" \
  "letta/letta-free"

# Singularity / Apptainer SIF for the local Letta server. Read by
# scripts/letta/start_singularity.sh and start.sh — both fall back to
# `${ARI_ROOT}/scripts/letta/letta.sif` when unset, but pinning it here
# makes the chosen image explicit across resume / restart.
_prompt_value "ARI_LETTA_SIF" \
  "$(m setv_letta_sif_label)" \
  "${ARI_ROOT}/scripts/letta/letta.sif" \
  "$(m setv_letta_sif_hint)"

_env_append_if_absent "# LETTA_LLM_CONFIG=letta-default"
_env_append_if_absent "# ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA=auto  # auto|pip|docker|singularity|none"
_env_append_if_absent "# ARI_MEMORY_LETTA_TIMEOUT_S=10"
_env_append_if_absent "# ARI_MEMORY_LETTA_OVERFETCH=200"
_env_append_if_absent "# ARI_TRANSFORM_MEMORY_MAX_ENTRIES=20"
_env_append_if_absent "# ARI_TRANSFORM_MEMORY_MAX_CHARS=2000"
_env_append_if_absent "# ARI_REACT_MEMORY_SEARCH_LIMIT=10"
_env_append_if_absent "# ARI_REACT_MEMORY_MAX_ENTRY_CHARS=0"
# Internal / tests only — do not set unless you know why:
_env_append_if_absent "# ARI_MEMORY_BACKEND=letta  # letta | in_memory (test fake)"
_env_append_if_absent "# ARI_MEMORY_LETTA_DISABLE_SELF_EDIT=true"
_env_append_if_absent "# ARI_MEMORY_ACCESS_LOG=on"
_env_append_if_absent "# ARI_MEMORY_AUTO_RESTORE=true"
_env_append_if_absent "# ARI_CURRENT_NODE_ID=  # runtime-only; set per-node by ari-core"
_env_append_if_absent "# ARI_LETTA_VENV=  # override pip-mode venv path"

# --- 5) ARI limits / scheduling --------------------------------------------
_env_section "ARI limits"
_env_append_if_absent "# ARI_MAX_DEPTH=5"
_env_append_if_absent "# ARI_MAX_NODES=50"
_env_append_if_absent "# ARI_MAX_REACT=80"
_env_append_if_absent "# ARI_MAX_RECURSION_DEPTH="
_env_append_if_absent "# ARI_TIMEOUT_NODE=7200"
_env_append_if_absent "# ARI_PARALLEL=4"
_env_append_if_absent "# ARI_PARENT_RUN_ID="
_env_append_if_absent "# ARI_RETRIEVAL_BACKEND=semantic_scholar"
_env_append_if_absent "# ARI_EXECUTOR="
_env_append_if_absent "# ARI_MAX_CHILD_PROCS="

# --- 6) Container -----------------------------------------------------------
_env_section "Container"
_env_append_if_absent "# ARI_CONTAINER_IMAGE="
_env_append_if_absent "# ARI_CONTAINER_MODE=auto"
_env_append_if_absent "# ARI_CONTAINERS_DIR="
_env_append_if_absent "# APPTAINER_CACHEDIR="
_env_append_if_absent "# SINGULARITY_CACHEDIR="

# --- 6b) ari-skill-paper-re sandbox / PaperBench ---------------------------
# ARI_PHASE1_SANDBOX selects the sandbox runtime for run_reproduce
# (apptainer | docker | local). The image vars override the default
# ubuntu:24.04 / .sif used by run_reproduce.
_env_append_if_absent "# ARI_PHASE1_SANDBOX=local"
_env_append_if_absent "# ARI_PHASE1_APPTAINER_IMAGE="
_env_append_if_absent "# ARI_PHASE1_SINGULARITY_IMAGE="
_env_append_if_absent "# ARI_PHASE1_DOCKER_IMAGE=ubuntu:24.04"
# Override path to the vendored PaperBench source tree if the default
# (ari-skill-paper-re/vendor/paperbench) is unavailable.
_env_append_if_absent "# ARI_PAPERBENCH_PATH="

# --- 7) SLURM ---------------------------------------------------------------
_env_section "SLURM"
_env_append_if_absent "# SLURM_MODE=local"
_env_append_if_absent "# SLURM_SSH_HOST=localhost"
_env_append_if_absent "# SLURM_SSH_USER="
_env_append_if_absent "# SLURM_SSH_PORT=22"
_env_append_if_absent "# SLURM_SSH_KEY="
_env_append_if_absent "# SLURM_SSH_PASSWORD="
_env_append_if_absent "# SLURM_LOG_DIR="
_env_append_if_absent "# SLURM_DEFAULT_PARTITION="
_env_append_if_absent "# SLURM_VALID_PARTITIONS="
_env_append_if_absent "# SLURM_JOB_ID=   # runtime-only; set by Slurm itself"
_env_append_if_absent "# SLURM_JOB_PARTITION=   # runtime-only; set by Slurm itself"
_env_append_if_absent "# SLURM_JOB_NODELIST=    # runtime-only; set by Slurm itself"
_env_append_if_absent "# SLURM_CLUSTER_NAME=  # runtime-only; set by Slurm itself"
_env_append_if_absent "# SLURM_PARTITION=   # fallback partition probed by paper-re sandbox runner"
_env_append_if_absent "# ARI_SLURM_CPUS="
_env_append_if_absent "# ARI_SLURM_MEM_GB="
_env_append_if_absent "# ARI_SLURM_GPUS="
_env_append_if_absent "# ARI_SLURM_WALLTIME=04:00:00"
_env_append_if_absent "# ARI_SLURM_PARTITION="

# --- 8) Orchestrator / viz --------------------------------------------------
_env_section "Orchestrator"
_env_append_if_absent "# ARI_ORCHESTRATOR_PORT="
_env_append_if_absent "# ARI_ORCHESTRATOR_LOGS="
_env_append_if_absent "# ARI_ORCHESTRATOR_DRY_RUN="
_env_append_if_absent "# ARI_ORCHESTRATOR_SSE_ONESHOT="
_env_append_if_absent "# ARI_ORCHESTRATOR_SSE_TIMEOUT="

# --- 9) LaTeX ---------------------------------------------------------------
_env_section "LaTeX"
_env_append_if_absent "# PDFLATEX_PATH=pdflatex"
_env_append_if_absent "# BIBTEX_PATH=bibtex"

# --- 9a) Skill: ari-skill-paper (review rubric) ----------------------------
_env_section "ari-skill-paper"
_env_append_if_absent "# ARI_RUBRIC="
_env_append_if_absent "# ARI_RUBRIC_DIR="
_env_append_if_absent "# ARI_STRICT_DYNAMIC="
_env_append_if_absent "# ARI_NUM_REVIEWS_ENSEMBLE="
_env_append_if_absent "# ARI_NUM_REFLECTIONS="

# --- 9b) Skill: ari-skill-web ----------------------------------------------
_env_section "ari-skill-web"
_env_append_if_absent "# ARI_ALPHAXIV_ENDPOINT=https://api.alphaxiv.org/mcp/v1"

# --- 9c) Skill: PaperBench (paper-re + viz/api_paperbench, v0.7.2) --------
# PaperBench's BasicAgent reads SLURM env vars at run time to populate the
# CLUSTER SHAPE prompt block (see ari-skill-paper-re/src/_replicator_agent.py
# ::detect_cluster_shape and the MPI aggregation skeleton). These are set
# automatically by sbatch; they're listed here so setup_env.sh test +
# documentation tooling acknowledge them as recognised vars.
_env_section "ari-skill-paper-re / PaperBench"
_env_append_if_absent "# ARI_PAPER_REGISTRY_DIR=\$HOME/.ari/paper_registry  # override paper registry root (default: ~/.ari/paper_registry)"
_env_append_if_absent "# SLURM_JOB_NUM_NODES=  # auto-populated by sbatch; surfaced in agent prompt CLUSTER SHAPE"
_env_append_if_absent "# SLURM_NTASKS=         # auto-populated by sbatch; surfaced in agent prompt CLUSTER SHAPE"
_env_append_if_absent "# SLURM_PROCID=         # auto-populated by srun; read by mpi_aggregate_skel.py fallback"

# --- 10) Skill: ari-skill-idea (agentscope vendor) -------------------------
# Used by ari-skill-idea/vendor/virsci/agentscope — studio/online app,
# gradio UI, and ModelScope integration. Leave commented unless you run
# the agentscope web UI / OSS uploads.
_env_section "agentscope (ari-skill-idea vendor)"
_env_append_if_absent "# IP=127.0.0.1"
_env_append_if_absent "# PORT=7860"
_env_append_if_absent "# SESSION_TYPE=filesystem"
_env_append_if_absent "# SECRET_KEY="
_env_append_if_absent "# CLIENT_ID="
_env_append_if_absent "# CLIENT_SECRET="
_env_append_if_absent "# OWNER="
_env_append_if_absent "# REPO="
_env_append_if_absent "# COPILOT_IP="
_env_append_if_absent "# COPILOT_PORT="
_env_append_if_absent "# LOCAL_WORKSTATION=false"
_env_append_if_absent "# MODELSCOPE_ENVIRONMENT="
_env_append_if_absent "# OSS_ACCESS_KEY_ID="
_env_append_if_absent "# OSS_ACCESS_KEY_SECRET="
_env_append_if_absent "# OSS_BUCKET_NAME="
_env_append_if_absent "# OSS_ENDPOINT="

ok "$(m setv_done) ($ENV_FILE)"

# --- 11) v0.7.0: EAR publish + ari-registry + Zenodo + gh backend ----------
# All commented by default — only flip on what you actually use. Tokens
# stay env-var-only so they don't leak into shell history when you mint
# them with `ari registry token issue <user>`.
_env_section "ari-registry / publish (v0.7.0)"
_env_append_if_absent "# ARI_PUBLISH_DRYRUN=false"
_env_append_if_absent "# ARI_PUBLISH_SETTINGS=\$HOME/.ari/publish.yaml"
_env_append_if_absent "# ARI_LOCAL_TARBALL_OUT="
_env_append_if_absent "# ARI_REGISTRIES_FILE=\$HOME/.ari/registries.yaml"
_env_append_if_absent "# ARI_REGISTRY_DATA=\$HOME/.ari/registry-data"
_env_append_if_absent "# ARI_REGISTRY_URL=https://registry.example.com"
_env_append_if_absent "# ARI_REGISTRY_NAME=default"
_env_append_if_absent "# ARI_REGISTRY_TOKEN="
_env_append_if_absent "# ARI_CLONE_HTTP_TIMEOUT=60"
_env_append_if_absent "# ARI_REPRO_CLONE_LOG=         # set automatically by react_driver"
_env_append_if_absent "# ZENODO_TOKEN="
_env_append_if_absent "# ZENODO_SANDBOX=false"
_env_append_if_absent "# ARI_GH_REPO=user/repo"
_env_append_if_absent "# ARI_GH_MODE=commit          # commit | releases"
