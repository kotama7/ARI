"""Legacy node_report reconstruction shim (Phase 3E + Phase 5).

The body of ``reconstruct_report_from_legacy`` lives in
:mod:`ari.migrations.v05_to_v07.node_reports`.  This module exists so
existing ``from ari.orchestrator.node_report.legacy_reconstruct
import ...`` paths keep working through v1.0; the deletion plan
(REFACTORING.md §8 + DEPRECATION_REMOVAL.md DR5) drops this shim and
the migrations module together.
"""

from ari.migrations.v05_to_v07.node_reports import (  # noqa: F401
    reconstruct_report_from_legacy,
)

__all__ = ["reconstruct_report_from_legacy"]
