# frontend/scripts

Node tooling that runs *outside* the bundle. These scripts are never imported
by application code, so they live here rather than under `src/`.

## Contents

- `README.md` — this file.
- `capture_screenshots.mjs` — drives a headless Chromium over a running
  `ari.viz.server` and writes the documentation screenshots into
  `docs/assets/images/<locale>/`, one PNG per (locale, route). Run via
  `npm run capture:screenshots -- --base-url … --out … --run-id …`.

## Regenerating the documentation screenshots

The docs embed these images, so a UI change that alters the shell — the sidebar
gained five entries when the v2 workspaces landed — invalidates every one of
them at once. Regenerate all locales together; a half-updated set is worse than
a uniformly stale one because the reader cannot tell which page is current.

```bash
# 1. a server with real data to photograph
cd ari-core && python -m ari.viz.server --port 8765 &

# 2. capture (from ari-core/ari/viz/frontend)
npm run capture:screenshots -- \
  --base-url http://127.0.0.1:8765 \
  --out ../../../../docs/assets/images \
  --run-id  <a completed checkpoint dir name> \
  --rqgm-run-id <an ari_rqgm checkpoint dir name>
```

`--rqgm-run-id` is what makes the Governance workspace show anything: on a
`simple_bfts` run that route deliberately renders a capability-state screen
instead. A schema-valid RQGM checkpoint can be generated without running a real
governed experiment:

```python
from tests.fixtures.gui_refresh.rqgm_fixture_factory import make_rqgm_checkpoint
make_rqgm_checkpoint(Path("workspace/checkpoints/<ts>_rqgm_demo"),
                     nodes=12, epochs=2, seed=7, with_paper=True)
```

Delete that fixture checkpoint afterwards — it is a photographic prop, not a
run.

### Headless prerequisites

Chromium needs system libraries and fonts that a bare compute node usually
lacks. Without them the capture still "succeeds" and silently produces wrong
images: missing fonts render as tofu boxes rather than failing.

- `npx playwright install chromium` for the browser binary.
- `libatk-1.0`, `libgbm`, `libXdamage` … — on a host without root, point
  `LD_LIBRARY_PATH` at a prefix that provides them (a conda env works).
  `ldd <chrome-headless-shell> | grep "not found"` tells you what is missing.
- Fonts, installed to `~/.local/share/fonts` + `fc-cache -f`:
  **Noto Sans CJK** (without it the `ja`/`zh` captures are entirely tofu) and
  **Noto Color Emoji** (the sidebar icons are emoji). Verify with
  `fc-match "sans:lang=ja"` before trusting a capture — then open one `ja`
  image and look at it.
