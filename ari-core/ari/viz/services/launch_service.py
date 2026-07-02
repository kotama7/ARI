"""ARI viz service: experiment-launch env/subprocess helpers (subtask 021).

Owns the ``.env`` discovery/parse that was duplicated inside
``api_experiment._api_run_stage`` and ``api_experiment._api_launch``. The full
``ARI_*`` environment mapping and the ``subprocess.Popen`` construction stay in
``api_experiment.py``: they are pinned there by the frozen source-inspection
contract tests (``test_launch_config.py`` asserts ``_st._last_proc =
subprocess.Popen(`` / ``ensure_checkpoint`` / ``_pre_ckpt`` etc. live inside
``_api_launch``; ``test_gui_env_propagation.py`` asserts every ``ARI_*`` write
is written by ``api_experiment.py``). Moving those would break the wire/CI
contract, so they are left for the larger Phase-5 follow-on (subtask 062).
REVIEW_REQUIRED: consolidate the ``ARI_*`` mapping + ``Popen`` here in 062.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable


def load_dotenv_files(
    proc_env: dict,
    candidates: "Iterable[Path]",
    *,
    strip_quotes: bool,
    swallow_errors: bool,
) -> None:
    """Merge ``KEY=VALUE`` lines from existing *candidates* into *proc_env*.

    Existing non-empty ``proc_env`` values always win — env-file values only
    fill blanks. Two historical parse variants are preserved **verbatim** so the
    launch behaviour is byte-identical:

    - ``strip_quotes=True``  — the ``_api_run_stage`` variant: ``line.strip()``,
      ``str.partition('=')``, surrounding quote stripping, and a non-empty key
      **and** value requirement.
    - ``strip_quotes=False`` — the ``_api_launch`` variant: ``str.split('=', 1)``
      with no line/quote stripping, key-only requirement.

    ``swallow_errors`` mirrors the call sites: ``_api_run_stage`` wrapped each
    file read in ``try/except: pass``; ``_api_launch`` let read errors propagate
    to its own outer handler.
    """
    for env_path in candidates:
        if not env_path.exists():
            continue
        try:
            _text = env_path.read_text()
        except Exception:
            if swallow_errors:
                continue
            raise
        if strip_quotes:
            for line in _text.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and v and (k not in proc_env or not proc_env[k]):
                        proc_env[k] = v
        else:
            for line in _text.splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k = k.strip(); v = v.strip()
                    if k not in proc_env or not proc_env[k]:
                        proc_env[k] = v
