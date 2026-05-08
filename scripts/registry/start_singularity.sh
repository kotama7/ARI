#!/usr/bin/env bash
# scripts/registry/start_singularity.sh — HPC fallback (Apptainer/Singularity).
# Builds and runs the registry inside an Apptainer SIF; useful for clusters
# that ban docker/podman.
set -euo pipefail

ARI_REGISTRY_DATA="${ARI_REGISTRY_DATA:-$HOME/.ari/registry-data}"
ARI_REGISTRY_PORT="${ARI_REGISTRY_PORT:-8290}"
SIF="${ARI_REGISTRY_SIF:-$HOME/.ari/ari-registry.sif}"

if ! command -v apptainer >/dev/null 2>&1 && ! command -v singularity >/dev/null 2>&1; then
  echo "neither apptainer nor singularity is on PATH" >&2
  exit 1
fi
APPTAINER="$(command -v apptainer || command -v singularity)"

mkdir -p "$ARI_REGISTRY_DATA"

if [ ! -f "$SIF" ]; then
  echo "building $SIF (one-time)..."
  cat > /tmp/ari-registry.def <<EOF
Bootstrap: docker
From: python:3.12-slim
%post
  pip install fastapi uvicorn[standard] python-multipart pyyaml
EOF
  "$APPTAINER" build --fakeroot "$SIF" /tmp/ari-registry.def
  rm -f /tmp/ari-registry.def
fi

echo "starting ari-registry on :$ARI_REGISTRY_PORT (data=$ARI_REGISTRY_DATA)"
exec "$APPTAINER" exec \
  --bind "$ARI_REGISTRY_DATA:/data" \
  --bind "$(pwd):/opt/ari" \
  "$SIF" \
  bash -c "cd /opt/ari && pip install -e ari-core/ >/dev/null && \
    ari registry serve --host 0.0.0.0 --port $ARI_REGISTRY_PORT --data-dir /data"
