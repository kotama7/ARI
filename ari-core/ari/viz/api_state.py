from __future__ import annotations
import re
"""ARI viz: api_state — checkpoint discovery, tree loading, broadcasting."""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import state as _st

import logging
log = logging.getLogger(__name__)



# Phase 3B (viz/REFACTORING.md §2 Step 2): the per-cluster bodies live
# in sibling modules.  This file remains a thin facade so downstream
# callers (and the route table inside ``server.py``) keep their
# ``from .api_state import ...`` paths intact.

from .checkpoint_finder import (  # noqa: F401
    _checkpoint_search_bases,
    _check_pid_alive,
    _resolve_checkpoint_dir,
)

from .tree_view import build_tree_view  # noqa: F401,E402

from .state_sync import (  # noqa: F401
    _load_nodes_tree,
    _broadcast,
    _do_broadcast,
    _watcher_thread,
)

from .checkpoint_api import (  # noqa: F401
    _api_models,
    _api_checkpoints,
    _api_checkpoint_summary,
    _api_lineage_decisions,
)

from .ear import (  # noqa: F401
    _api_ear,
    _api_node_report,
    _api_ear_clone_verify,
    _api_ear_curate,
    _api_ear_publish_yaml_get,
    _api_ear_publish_yaml_set,
    _synth_repro_report_from_ors,
)

from .file_api import (  # noqa: F401
    _ensure_paper_dir,
    _api_checkpoint_files,
    _api_checkpoint_file_read,
    _resolve_paper_file,
    _api_checkpoint_file_save,
    _api_checkpoint_file_upload,
    _api_checkpoint_file_delete,
    _api_checkpoint_compile,
)

from .checkpoint_lifecycle import (  # noqa: F401
    _api_delete_checkpoint,
    _api_switch_checkpoint,
)

from .node_work_api import (  # noqa: F401
    _resolve_node_work_dir,
    _api_checkpoint_filetree,
    _api_checkpoint_filecontent,
    _api_checkpoint_memory,
)

