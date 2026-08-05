#!/usr/bin/env bash
# Submit the registered handoff matrix as independent A64FX Slurm allocations.
# One array element runs exactly one task x arm x seed BFTS run. A dependent
# collector validates the complete grid before merging manifests and analyzing.
#
# Usage:
#   bash workspace/submit_handoff_ablation_array.sh --smoke
#   bash workspace/submit_handoff_ablation_array.sh --full
#
# Optional scheduling/output environment:
#   ARI_ARRAY_CONCURRENCY=9
#   ARI_MATRIX_ROOT=/absolute/output/path
#   ARI_WORKER_TIME=06:00:00

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

MODE=smoke
RESUME_ROOT=""
if [[ $# -eq 2 && "$1" == "--resume" ]]; then
  RESUME_ROOT="$2"
elif [[ $# -gt 1 ]]; then
  echo "Usage: bash workspace/submit_handoff_ablation_array.sh [--smoke|--preflight|--full|--resume ROOT]" >&2
  exit 2
elif [[ $# -eq 1 ]]; then
  case "$1" in
    --smoke) MODE=smoke ;;
    --preflight) MODE=preflight ;;
    --full) MODE=full ;;
    *)
      echo "Unknown mode: $1 (expected --smoke, --preflight, --full or --resume ROOT)" >&2
      exit 2
      ;;
  esac
fi

if [[ -n "${SLURM_JOB_ID:-}" ]]; then
  echo "Run this launcher on the login node; it submits independent sbatch jobs." >&2
  exit 2
fi
command -v sbatch >/dev/null || {
  echo "sbatch is not available" >&2
  exit 2
}

# REMEASURE_REPS is read from the environment here as well as in the worker.
# It was not, and line 132 then exported the mode default over whatever the
# caller set -- so `ARI_REMEASURE_REPS=15 ... --smoke` silently ran at 5 AND
# recorded 5 in launch_contract.json, leaving no way to tell the two apart.
# The design values are HARDCODED PER MODE, never read from the environment:
# an ambient ARI_SEEDS or ARI_REMEASURE_REPS left over in a shell must not be
# able to turn a --full submission into a different experiment. That immunity is
# asserted by ari-core/tests/test_handoff_driver.py and is deliberate.
#
# --preflight exists because the combination the pre-flight needs -- the
# CONFIRMATORY configuration at one seed -- had no expression. --smoke is the
# only one-seed mode and it also swaps in reduced problem sizes (128^3, nt=10),
# so a pre-flight could exercise the pipeline or the scored configuration but
# never both; three campaign-breaking defects were found by a smoke pre-flight
# that could not, by construction, have found a fourth in the scored path.
# Making it a mode rather than an override keeps the design auditable: whatever
# ran is in launch_contract.json and came from exactly one branch below.
if [[ "$MODE" == "smoke" ]]; then
  SEEDS=1
  SEED_BASE=0
  MAX_NODES=10
  REMEASURE_REPS=5
  MATRIX_SMOKE=1
  WORKER_TIME="${ARI_WORKER_TIME:-03:00:00}"
elif [[ "$MODE" == "preflight" ]]; then
  SEEDS=1
  SEED_BASE=0
  MAX_NODES=10
  REMEASURE_REPS=15
  MATRIX_SMOKE=0
  WORKER_TIME="${ARI_WORKER_TIME:-06:00:00}"
else
  SEEDS=30
  SEED_BASE=0
  MAX_NODES=10
  REMEASURE_REPS=15
  MATRIX_SMOKE=0
  WORKER_TIME="${ARI_WORKER_TIME:-06:00:00}"
fi

# Concurrency was pinned at 9 -- one element per task x arm cell -- so 270
# elements ran in 30 waves regardless of how much of the partition was free.
#
# Slurm's `%C` throttle is not a wave barrier: as each element finishes the next
# starts, so nodes do not idle waiting for a batch to drain. What C does is CAP
# how much of the partition the campaign can use, and it is evaluated once, here.
# Default it to what is actually idle, rounded DOWN to a multiple of 9 so every
# concurrent set still holds each condition an equal number of times (the
# property the arm rotation exists to preserve).
#
# The upper bound is NOT about nodes. C concurrent elements means C concurrent
# BFTS runs all calling the same LLM endpoint, and a rate limit that outlives the
# per-call retries costs one of the run's MAX_NODES attempts with no node-level
# retry behind it. So the ceiling is an API-concurrency judgement; it is named as
# one and is overridable.
# NOT derived from the idle node count. Slurm's `%C` caps how many array tasks
# run AT ONCE; it does not require C nodes to be free at submit time -- the rest
# queue and start as capacity appears. Sizing C from whatever happened to be idle
# at submit therefore buys nothing and costs a lot: measured at one moment the
# partition had 10 idle, which would have pinned a 114 node-hour campaign to
# C=9 and ~13 h instead of ~5 h, permanently, even after the partition drained.
# The only real ceiling is how many concurrent BFTS runs the LLM endpoint will
# take, so that is what C is. Kept a multiple of 9 so every concurrent set holds
# each condition equally (see workspace/harnesses/tests/test_campaign_matrix.py).
ARI_MAX_CONCURRENCY="${ARI_MAX_CONCURRENCY:-27}"
_default_concurrency() {
  local c=$(( (ARI_MAX_CONCURRENCY / 9) * 9 ))
  (( c < 9 )) && c=9
  echo "$c"
}
PARTITION="${ARI_PARTITION:?set ARI_PARTITION to your A64FX partition}"
CONCURRENCY="${ARI_ARRAY_CONCURRENCY:-$(_default_concurrency)}"
MODEL="cerebras/gpt-oss-120b"

for value_name in SEEDS CONCURRENCY MAX_NODES REMEASURE_REPS; do
  value="${!value_name}"
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "$value_name must be a positive integer (got $value)" >&2
    exit 2
  fi
done
if [[ ! "$SEED_BASE" =~ ^[0-9]+$ ]]; then
  echo "SEED_BASE must be a non-negative integer (got $SEED_BASE)" >&2
  exit 2
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
ROOT="${ARI_MATRIX_ROOT:-$REPO/workspace/checkpoints/${STAMP}_handoff_array_${MODE}}"

# A resume adopts the ORIGINAL root and, with it, the original design. Reading
# the frozen contract is stricter than any mode branch: the resubmitted cells
# cannot silently differ from the ones they replace, whatever the defaults have
# since become.
if [[ -n "$RESUME_ROOT" ]]; then
  [[ -f "$RESUME_ROOT/launch_contract.json" ]] || {
    echo "not a campaign root (no launch_contract.json): $RESUME_ROOT" >&2; exit 2; }
  ROOT="$(cd "$RESUME_ROOT" && pwd)"
  while IFS='=' read -r k v; do
    case "$k" in
      mode) MODE="$v" ;;
      seeds) SEEDS="$v" ;;
      seed_base) SEED_BASE="$v" ;;
      max_nodes) MAX_NODES="$v" ;;
      remeasure_reps) REMEASURE_REPS="$v" ;;
      model) MODEL="$v" ;;
    esac
  done < <(python3 -c '
import json, sys
c = json.load(open(sys.argv[1] + "/launch_contract.json"))
for k in ("mode", "seeds", "seed_base", "max_nodes", "remeasure_reps", "model"):
    print(f"{k}={c[k]}")
' "$ROOT")
  case "$MODE" in
    smoke) MATRIX_SMOKE=1 ;;
    *)     MATRIX_SMOKE=0 ;;
  esac
  RESUMED_FINGERPRINT="$(python3 -c '
import json, sys
print(json.load(open(sys.argv[1] + "/launch_contract.json"))["study_source_fingerprint"])
' "$ROOT")"
  cp -p "$ROOT/launch_contract.json" "$ROOT/launch_contract.json.resume_backup"
  echo "resuming $ROOT (mode=$MODE seeds=$SEEDS reps=$REMEASURE_REPS)"
fi

if [[ "$ROOT" != /* ]]; then
  ROOT="$REPO/$ROOT"
fi
mkdir -p "$ROOT/logs"

TOTAL=$((SEEDS * 9))
LAST=$((TOTAL - 1))
ARRAY_SPEC="0-${LAST}%${CONCURRENCY}"
WORKER="$REPO/workspace/submit_handoff_ablation_sbatch.sh"
ANALYZER="$REPO/workspace/analyze_handoff_ablation.py"

if [[ -x "$REPO/workspace/.venv_aarch64/bin/python" ]]; then
  PYTHON="$REPO/workspace/.venv_aarch64/bin/python"
else
  PYTHON=python3
fi

# --resume re-runs ONLY the cells that did not complete, into the SAME root, with
# the design read back from that root's launch_contract.json rather than from a
# mode branch. The collector refuses to analyse a partial grid, and nothing below
# it retries a cell (orchestrator/bfts.py: "ARI does not retry failed nodes"), so
# until now the recovery path for one terminal API error in 270 was to find the
# cell by hand -- which is what happened twice in the preliminary campaign.
RESUME_INDICES=""
if [[ -n "$RESUME_ROOT" ]]; then
  RESUME_INDICES="$("$PYTHON" "$REPO/workspace/tools/find_incomplete_cells.py" \
                    "$ROOT" --indices)" || exit 2
  if [[ -z "$RESUME_INDICES" ]]; then
    echo "nothing to resume: every cell under $ROOT is complete"
    exit 0
  fi
  N_RESUME=$(awk -F, '{print NF}' <<<"$RESUME_INDICES")
  echo "resuming $N_RESUME incomplete cell(s) of $TOTAL: $RESUME_INDICES"
  ARRAY_SPEC="${RESUME_INDICES}%${CONCURRENCY}"
fi

# REFUSE A CAMPAIGN THAT CANNOT FIT. The harness caches a generated problem and a
# reference solution per repetition, keyed by an input seed derived from the RUN
# seed, so the cache grows linearly in the seed count -- measured 26.7 GB per
# seed, i.e. ~800 GB for 30 against ~694 GB of quota. A one-seed pre-flight
# cannot show this. Hitting the quota mid-campaign is the worst shape of failure
# available: writes start failing, oracles get recomputed instead of read, and
# the runs late in the campaign time out, so the damage lands on some seeds and
# not others. Set ARI_SKIP_CAPACITY_CHECK=1 to proceed anyway once the storage
# question has actually been decided.
if [[ "${ARI_SKIP_CAPACITY_CHECK:-0}" != "1" ]]; then
  if ! "$PYTHON" "$REPO/workspace/tools/check_cache_capacity.py" \
        --seeds "$SEEDS" --quiet; then
    echo "refusing to submit: the projected oracle cache does not fit" >&2
    echo "  see: $PYTHON workspace/tools/check_cache_capacity.py --seeds $SEEDS" >&2
    echo "  override with ARI_SKIP_CAPACITY_CHECK=1 once storage is decided" >&2
    exit 4
  fi
fi

# Freeze the exact experiment-defining bytes before any array element starts.
# Workers recompute this digest both before and after their run; the collector
# requires the same value from every shard.
STUDY_FINGERPRINT="$(
  "$PYTHON" -c '
import hashlib
import json
import sys
from pathlib import Path
from workspace.run_handoff_ablation import study_source_manifest

manifest = study_source_manifest()
payload = json.dumps(
    manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
).encode()
fingerprint = hashlib.sha256(payload).hexdigest()
contract = {
    "schema_version": 1,
    "study_source_fingerprint": fingerprint,
    "files": manifest,
    "mode": sys.argv[2],
    "seeds": int(sys.argv[3]),
    "seed_base": int(sys.argv[4]),
    "max_nodes": int(sys.argv[5]),
    "remeasure_reps": int(sys.argv[6]),
    "model": sys.argv[7],
}
path = Path(sys.argv[1])
tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
tmp.replace(path)
print(fingerprint)
' "$ROOT/launch_contract.json" "$MODE" "$SEEDS" "$SEED_BASE" \
    "$MAX_NODES" "$REMEASURE_REPS" "$MODEL"
)"

# A resume must reproduce the ORIGINAL experiment, so the source tree has to be
# byte-identical to what the frozen contract recorded. If it is not, the resumed
# cells would carry a different fingerprint from their 269 siblings and the
# collector would reject the whole campaign -- after the resubmission had already
# spent its compute. Refuse here instead, and put the untouched contract back:
# computing the fingerprint rewrites it as a side effect.
if [[ -n "$RESUME_ROOT" && "$STUDY_FINGERPRINT" != "$RESUMED_FINGERPRINT" ]]; then
  mv -f "$ROOT/launch_contract.json.resume_backup" "$ROOT/launch_contract.json"
  echo "refusing to resume: the source tree changed since this campaign was launched" >&2
  echo "  contract : $RESUMED_FINGERPRINT" >&2
  echo "  current  : $STUDY_FINGERPRINT" >&2
  echo "Check out the recorded sources, or start a new campaign." >&2
  exit 3
fi
[[ -n "$RESUME_ROOT" ]] && rm -f "$ROOT/launch_contract.json.resume_backup"

# The worker must find the repository without an absolute path baked into it.
ARRAY_EXPORT="ALL,ARI_REPO=$REPO,ARI_MATRIX_ROOT=$ROOT,ARI_MATRIX_SEEDS=$SEEDS,ARI_MATRIX_SEED_BASE=$SEED_BASE"
ARRAY_EXPORT+=",ARI_MATRIX_SMOKE=$MATRIX_SMOKE,ARI_MAX_NODES=$MAX_NODES"
ARRAY_EXPORT+=",ARI_REMEASURE_REPS=$REMEASURE_REPS,ARI_LARGE_MODEL=$MODEL"
ARRAY_EXPORT+=",ARI_STUDY_SOURCE_FINGERPRINT=$STUDY_FINGERPRINT"
# The oracle cache was never wired into the campaign: ARI_HARNESS_CACHE was unset
# in every worker, _problem_cache_dir() returned None, and each run recomputed the
# numpy reference from scratch. At reps=15 the stencil oracle alone is 240 sweeps
# over 256^3, fifteen times, for three shapes.
ARRAY_EXPORT+=",ARI_HARNESS_CACHE=${ARI_HARNESS_CACHE:-$REPO/workspace/checkpoints/harness_cache}"
# A terminal RateLimitError consumes one of the run's MAX_NODES attempts and is
# never retried at the node level (orchestrator/bfts.py: "ARI does not retry
# failed nodes"). The only lever is the per-call retry budget, so raise it.
ARRAY_EXPORT+=",ARI_LLM_NUM_RETRIES=${ARI_LLM_NUM_RETRIES:-8}"

ARRAY_JOB_RAW="$(
  sbatch --parsable \
    --chdir="$REPO" \
    --array="$ARRAY_SPEC" \
    --time="$WORKER_TIME" \
    --job-name=ari-handoff-run \
    --output="$ROOT/logs/run-%A_%a.out" \
    --error="$ROOT/logs/run-%A_%a.err" \
    --export="$ARRAY_EXPORT" \
    "$WORKER"
)"
ARRAY_JOB="${ARRAY_JOB_RAW%%;*}"

# Accumulate every array job this launcher submitted FOR THIS ROOT. The collector
# validates each shard's Slurm array job against this set; a resume adds one id
# and must not invalidate the shards that ran under the first.
# A resume ADDS to the set; any other launch STARTS it. Appending
# unconditionally would let a root reused via ARI_MATRIX_ROOT inherit the ids of
# a previous, unrelated campaign — which is precisely the contamination the
# collector's check exists to prevent.
if [[ -n "$RESUME_ROOT" ]]; then
  echo "$ARRAY_JOB" >> "$ROOT/array_job_ids.txt"
else
  echo "$ARRAY_JOB" > "$ROOT/array_job_ids.txt"
fi
ARRAY_JOB_SET="$(paste -sd, "$ROOT/array_job_ids.txt")"

COLLECT_ARGS=(
  "$PYTHON"
  "$ANALYZER"
  "$ROOT"
  --aggregate-shards
  --tasks gemm,spmm,stencil
  --arms code_only,evidence_only,evidence_plus_reflection
  --seed-base "$SEED_BASE"
  --seeds "$SEEDS"
  --expected-array-job-id "$ARRAY_JOB_SET"
  --expected-study-fingerprint "$STUDY_FINGERPRINT"
  --expected-max-nodes "$MAX_NODES"
  --expected-remeasure-reps "$REMEASURE_REPS"
  --expected-model "$MODEL"
)
# --preflight is one seed, so its inferential output is degenerate: every
# contrast prints p=1 with a zero-width CI. Left as a confirmatory analysis it
# both LOOKS like a result and is recorded as one in shard_audit.json, which is
# how a pre-flight root gets mistaken for the campaign later.
if [[ "$MODE" == "smoke" || "$MODE" == "preflight" ]]; then
  COLLECT_ARGS+=(--descriptive-only)
fi
SOURCE_CHECK_CODE='
import hashlib
import json
import os
import sys
from pathlib import Path

contract = json.loads(Path(sys.argv[1]).read_text())
repo = Path(sys.argv[2])
current = {}
for relative in sorted(contract["files"]):
    path = repo / relative
    if path.is_symlink():
        payload = ("symlink:" + os.readlink(path)).encode()
        current[relative] = hashlib.sha256(payload).hexdigest()
    elif path.is_file():
        current[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        current[relative] = "missing"
payload = json.dumps(
    current, sort_keys=True, separators=(",", ":"), ensure_ascii=True
).encode()
got = hashlib.sha256(payload).hexdigest()
if got != sys.argv[3]:
    raise SystemExit(
        f"study source fingerprint changed before/after collection: {got}"
    )
'
SOURCE_CHECK_ARGS=(
  "$PYTHON" -c "$SOURCE_CHECK_CODE"
  "$ROOT/launch_contract.json" "$REPO" "$STUDY_FINGERPRINT"
)
printf -v COLLECT_COMMAND '%q ' "${COLLECT_ARGS[@]}"
printf -v SOURCE_CHECK_COMMAND '%q ' "${SOURCE_CHECK_ARGS[@]}"
COLLECT_WRAP="set +e; $SOURCE_CHECK_COMMAND; pre=\$?; "
COLLECT_WRAP+="if [ \"\$pre\" -ne 0 ]; then exit 86; fi; "
COLLECT_WRAP+="$COLLECT_COMMAND; rc=\$?; "
COLLECT_WRAP+="$SOURCE_CHECK_COMMAND; post=\$?; "
COLLECT_WRAP+="if [ \"\$post\" -ne 0 ]; then exit 86; fi; exit \$rc"

# afterany is intentional: the collector still runs after a failed array
# element, writes shard_audit.json, and exits non-zero instead of leaving a
# forever-pending dependency or silently analyzing a partial matrix.
COLLECT_JOB_RAW="$(
  sbatch --parsable \
    --dependency="afterany:$ARRAY_JOB" \
    --partition="$PARTITION" \
    --nodes=1 \
    --ntasks=1 \
    --cpus-per-task=1 \
    --time=00:30:00 \
    --chdir="$REPO" \
    --job-name=ari-handoff-collect \
    --output="$ROOT/logs/collect-%j.out" \
    --error="$ROOT/logs/collect-%j.err" \
    --export="ALL,ARI_WORKSPACE=$REPO/workspace,OPENBLAS_NUM_THREADS=1" \
    --wrap="$COLLECT_WRAP"
)"
COLLECT_JOB="${COLLECT_JOB_RAW%%;*}"

echo "MODE=$MODE"
echo "ROOT=$ROOT"
echo "RUN_ARRAY_JOB=$ARRAY_JOB"
echo "RUN_ARRAY_SPEC=$ARRAY_SPEC"
echo "COLLECT_JOB=$COLLECT_JOB"
echo "STUDY_SOURCE_FINGERPRINT=$STUDY_FINGERPRINT"
echo "The collector validates $TOTAL task x arm x seed shards before analysis."
