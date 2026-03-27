#!/bin/bash
# run_ollama_gpu.sh — Generic SLURM script to start Ollama on a GPU node
#
# Usage:
#   sbatch --partition=<PARTITION> --gres=gpu:<TYPE>:1 run_ollama_gpu.sh
#
# Environment variables (override defaults):
#   OLLAMA_BIN_PATH   — path to ollama binary  (default: searches PATH + ~/local/ollama/bin)
#   OLLAMA_PORT       — port to listen on        (default: 11435)
#   ARI_LOG_DIR       — directory for node info  (default: <script_dir>/../logs)
#
#SBATCH --job-name=ollama-gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --time=24:00:00
#SBATCH --output=%x_%j.log
#SBATCH --error=%x_%j.err

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARI_LOG_DIR="${ARI_LOG_DIR:-${SCRIPT_DIR}/../logs}"
mkdir -p "${ARI_LOG_DIR}"

if [[ -n "${OLLAMA_BIN_PATH:-}" ]]; then
    OLLAMA_BIN="${OLLAMA_BIN_PATH}"
elif command -v ollama &>/dev/null; then
    OLLAMA_BIN="$(command -v ollama)"
elif [[ -x "${HOME}/local/ollama/bin/ollama" ]]; then
    OLLAMA_BIN="${HOME}/local/ollama/bin/ollama"
else
    echo "[$(date)] ERROR: ollama not found. Set OLLAMA_BIN_PATH." >&2; exit 1
fi

OLLAMA_PORT="${OLLAMA_PORT:-11435}"

echo "[$(date)] Starting Ollama on GPU node: $(hostname)"
export OLLAMA_HOST="0.0.0.0:${OLLAMA_PORT}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

"${OLLAMA_BIN}" serve &
OLLAMA_PID=$!
sleep 8

if ! kill -0 "${OLLAMA_PID}" 2>/dev/null; then
    echo "[$(date)] ERROR: Ollama failed to start" >&2; exit 1
fi

echo "[$(date)] Ollama running (PID=${OLLAMA_PID})"
echo "$(hostname):${OLLAMA_PORT}" > "${ARI_LOG_DIR}/ollama_gpu_node.txt"
echo "[$(date)] Node info: $(hostname):${OLLAMA_PORT}"
wait "${OLLAMA_PID}"
echo "[$(date)] Ollama exited."
