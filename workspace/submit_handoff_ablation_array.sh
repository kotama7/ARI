#!/usr/bin/env bash
# Submit the registered handoff matrix as independent fx700 Slurm allocations.
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
if [[ $# -gt 1 ]]; then
  echo "Usage: bash workspace/submit_handoff_ablation_array.sh [--smoke|--full]" >&2
  exit 2
elif [[ $# -eq 1 ]]; then
  case "$1" in
    --smoke) MODE=smoke ;;
    --full) MODE=full ;;
    *)
      echo "Unknown mode: $1 (expected --smoke or --full)" >&2
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

if [[ "$MODE" == "smoke" ]]; then
  SEEDS=1
  SEED_BASE=0
  MAX_NODES=10
  REMEASURE_REPS=5
  MATRIX_SMOKE=1
  WORKER_TIME="${ARI_WORKER_TIME:-03:00:00}"
else
  SEEDS=30
  SEED_BASE=0
  MAX_NODES=10
  REMEASURE_REPS=15
  MATRIX_SMOKE=0
  WORKER_TIME="${ARI_WORKER_TIME:-06:00:00}"
fi

CONCURRENCY="${ARI_ARRAY_CONCURRENCY:-9}"
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
ROOT="${ARI_MATRIX_ROOT:-$REPO/workspace/checkpoints/${STAMP}_fx700_handoff_array_${MODE}}"
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

ARRAY_EXPORT="ALL,ARI_MATRIX_ROOT=$ROOT,ARI_MATRIX_SEEDS=$SEEDS,ARI_MATRIX_SEED_BASE=$SEED_BASE"
ARRAY_EXPORT+=",ARI_MATRIX_SMOKE=$MATRIX_SMOKE,ARI_MAX_NODES=$MAX_NODES"
ARRAY_EXPORT+=",ARI_REMEASURE_REPS=$REMEASURE_REPS,ARI_LARGE_MODEL=$MODEL"
ARRAY_EXPORT+=",ARI_STUDY_SOURCE_FINGERPRINT=$STUDY_FINGERPRINT"

ARRAY_JOB_RAW="$(
  sbatch --parsable \
    --array="$ARRAY_SPEC" \
    --time="$WORKER_TIME" \
    --job-name=ari-handoff-run \
    --output="$ROOT/logs/run-%A_%a.out" \
    --error="$ROOT/logs/run-%A_%a.err" \
    --export="$ARRAY_EXPORT" \
    "$WORKER"
)"
ARRAY_JOB="${ARRAY_JOB_RAW%%;*}"

COLLECT_ARGS=(
  "$PYTHON"
  "$ANALYZER"
  "$ROOT"
  --aggregate-shards
  --tasks gemm,spmm,stencil
  --arms code_only,evidence_only,evidence_plus_reflection
  --seed-base "$SEED_BASE"
  --seeds "$SEEDS"
  --expected-array-job-id "$ARRAY_JOB"
  --expected-study-fingerprint "$STUDY_FINGERPRINT"
  --expected-max-nodes "$MAX_NODES"
  --expected-remeasure-reps "$REMEASURE_REPS"
  --expected-model "$MODEL"
)
if [[ "$MODE" == "smoke" ]]; then
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
    --partition=fx700 \
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
