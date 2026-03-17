#!/bin/bash
# ARI Setup Script — installs all skills and dependencies
set -e

ARI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "=== ARI Setup ==="
echo "Root: $ARI_ROOT"

# 1. Core + all skills
echo "[1/4] Installing ARI core and skills..."
pip install -e "$ARI_ROOT/ari-core/"
for skill_dir in "$ARI_ROOT"/ari-skill-*/; do
    [ -f "$skill_dir/setup.py" ] || [ -f "$skill_dir/pyproject.toml" ] && \
        pip install -e "$skill_dir" 2>/dev/null || true
done

# 2. Python dependencies
echo "[2/4] Installing Python dependencies..."
pip install litellm mcp fastmcp pymupdf pdfminer.six networkx seaborn

# 3. PDF tools via conda (if available, no sudo needed)
echo "[3/4] Installing PDF tools..."
if command -v conda &>/dev/null; then
    conda install -c conda-forge poppler chktex -y --quiet 2>/dev/null && \
        echo "  poppler + chktex installed via conda" || \
        echo "  conda install skipped (non-fatal)"
else
    echo "  conda not found — using pymupdf/pdfminer fallback (already installed)"
fi

# 4. Verify
echo "[4/4] Verification..."
python3 -c "import mcp; print('  mcp:', mcp.__file__)"
python3 -c "import litellm; print('  litellm OK')"
python3 -c "import fitz; print('  pymupdf OK')"
which pdftotext &>/dev/null && echo "  pdftotext OK" || echo "  pdftotext: not found (using pymupdf fallback)"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next: configure your LLM in ari-core/config/workflow.yaml"
echo "  OpenAI: export ARI_LLM_MODEL=openai/gpt-5.2 && export OPENAI_API_KEY=sk-..."
echo "  Ollama: export ARI_LLM_MODEL=qwen3:32b && export LLM_API_BASE=http://127.0.0.1:11434"
echo ""
echo "Then run: ari run experiment.md --config ari-core/config/workflow.yaml"
