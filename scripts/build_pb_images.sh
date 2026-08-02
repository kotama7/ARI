#!/usr/bin/env bash
# Build the vendor PaperBench Docker images (pb-env + pb-reproducer)
# that the bridge rollout / reproduction paths can consume by immutable
# image identity or after conversion to a local SIF. Mirrors:
#   ari-skill-paper-re/vendor/paperbench/project/paperbench/paperbench/scripts/build-docker-images.sh
# but runs from the ARI repo root so the relative paths resolve.
#
# Preconditions:
#   - docker daemon running and reachable to $USER
#   - vendor submodule initialised
#     (scripts/setup/install_paperbench.sh covers this when setup.sh ran)
#
# Outputs (local docker image tags):
#   pb-env:latest         — Stage 1 agent rollout image (Ubuntu 24.04 + conda)
#   pb-reproducer:latest  — Stage 2 reproduce.sh execution image (GPU-ready)
#
# Usage:
#   bash scripts/build_pb_images.sh
#
# Stage 2 Docker accepts the full ``sha256:<image-id>`` printed below. Mutable
# local tags are build handles only and are not accepted by reproduction.
#
# Apptainer / Singularity hosts:
#   apptainer pull pb-env.sif docker-daemon://pb-env:latest
#   apptainer pull pb-reproducer.sif docker-daemon://pb-reproducer:latest
#   bridge.rollout_submission(container_image="/path/to/pb-env.sif",
#                             sandbox_kind="apptainer", ...)

set -euo pipefail

ARI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
PB_PROJECT="${ARI_ROOT}/ari-skill-paper-re/vendor/paperbench/project/paperbench"

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker not on PATH; cannot build pb-env / pb-reproducer images." >&2
  echo "       Install docker first, then re-run this script." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "error: docker daemon not reachable; cannot build images." >&2
  echo "       Start the docker daemon (or fix DOCKER_HOST), then re-run." >&2
  exit 1
fi

if [ ! -f "${PB_PROJECT}/paperbench/Dockerfile.base" ]; then
  echo "error: vendor PaperBench Dockerfile.base missing at" >&2
  echo "       ${PB_PROJECT}/paperbench/Dockerfile.base" >&2
  echo "       Run scripts/setup/install_paperbench.sh first." >&2
  exit 1
fi

cd "${PB_PROJECT}"

echo "[pb-images] building pb-env (Stage 1 agent rollout image) ..."
docker build --platform=linux/amd64 -t pb-env -f paperbench/Dockerfile.base .

echo "[pb-images] building pb-reproducer (Stage 2 reproduce.sh image) ..."
docker build --platform=linux/amd64 -f paperbench/reproducer.Dockerfile -t pb-reproducer .

PB_ENV_ID="$(docker image inspect --format '{{.Id}}' pb-env:latest)"
PB_REPRODUCER_ID="$(docker image inspect --format '{{.Id}}' pb-reproducer:latest)"

echo ""
echo "[pb-images] ok. Mutable build tags:"
docker image ls --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}' \
  | grep -E '^(pb-env|pb-reproducer):' || true
echo ""
echo "[pb-images] Immutable image IDs:"
echo "  pb-env:        ${PB_ENV_ID}"
echo "  pb-reproducer: ${PB_REPRODUCER_ID}"
echo ""
echo "[pb-images] Stage 2 Docker example:"
echo "  python scripts/sc_paper_dogfood.py ... \\"
echo "    --with-reproduction --reproduce-sandbox docker \\"
echo "    --reproduce-container-image ${PB_REPRODUCER_ID}"
echo "[pb-images] For Stage 1 Apptainer, convert pb-env:latest to a local SIF."
