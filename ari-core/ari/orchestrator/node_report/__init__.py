"""Per-node ``node_report.json`` package (Phase 3E + Phase 5 split).

Two files live here:

- :mod:`ari.orchestrator.node_report.builder` — the v0.7+ report
  builder (``build_node_report``, ``read_decision_log``, helpers for
  files-changed aggregation, build/run command extraction, etc.).
- :mod:`ari.orchestrator.node_report.legacy_reconstruct` — thin shim
  re-exporting the legacy v0.5 → v0.7 reconstruction logic that lives
  under :mod:`ari.migrations.v05_to_v07.node_reports`.

Public symbols (``build_node_report``, ``reconstruct_report_from_legacy``,
the file-walk helpers used by the migrations package, etc.) are
re-exported here so callers can keep ``from ari.orchestrator.node_report
import ...`` regardless of which sub-module owns the implementation.
"""

from ari.orchestrator.node_report.builder import (  # noqa: F401
    SCHEMA_VERSION,
    NodeReportInputs,
    _artifact_to_record,
    _is_blocklisted,
    _looks_like_build_line,
    _looks_like_shebang_or_directive,
    _read_text_safe,
    _sha256_file,
    _trace_log_summary,
    _utc_now_iso,
    _walk_files,
    build_node_report,
    classify_artifact_role,
    compute_files_changed,
    derive_self_assessment_from_evaluator,
    extract_build_run_commands,
    write_node_report,
)
from ari.orchestrator.node_report.legacy_reconstruct import (  # noqa: F401
    reconstruct_report_from_legacy,
)

__all__ = [
    "SCHEMA_VERSION",
    "NodeReportInputs",
    "build_node_report",
    "classify_artifact_role",
    "compute_files_changed",
    "derive_self_assessment_from_evaluator",
    "extract_build_run_commands",
    "reconstruct_report_from_legacy",
    "write_node_report",
]
