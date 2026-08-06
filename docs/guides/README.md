# docs/guides

Task-oriented how-to guides for operating, configuring, extending, and
troubleshooting ARI.

## Contents

- `README.md` — this file.
- `configuration_studio.md` — Configuration Studio Guide: inspecting effective configuration, editing project/template/draft documents, secrets, and the launch flow.
- `cookbook.md` — Cookbook: copy-paste recipes for the configuration knobs you reach for most.
- `dashboard.md` — Dashboard Guide: starting the viz server, the v2 workspace map, run-explicit deep links, live updates, and the log explorer.
- `execution_modes.md` — Execution Modes: the `simple_bfts` / `ari_rqgm` mode switch and its activation keys.
- `experiment_file.md` — Writing Experiment Files: how `experiment.md` describes what ARI should do.
- `extension_guide.md` — Extension Guide: extending ARI for new use cases, domains, and capabilities.
- `gui_cutover_runbook.md` — GUI Cutover Runbook: promoting the v2 dashboard to the default, the rollback levers, and the legacy-removal order.
- `hpc_setup.md` — HPC Setup Guide: running ARI on a SLURM cluster.
- `manuscript_complete_migration.md` — Manuscript Complete: additive migration and rollback for legacy checkpoints.
- `manuscript_complete_operations.md` — Manuscript Complete: activation, inspection, repair, resume, and publication operations.
- `migration.md` — Migration Guide: moving between ARI's checkpoint-format releases, plus the GUI refresh behaviour changes.
- `remote_access.md` — Remote Access and Operations Guide: bind policy, token auth, CORS/CSP, confirmation challenges, tunnels, and the health/diagnostics endpoints.
- `rqgm_evaluation.md` — RQGM Evaluation and Ablation: measuring whether each governance layer earns its cost.
- `rqgm_gui.md` — RQGM Governance Workspace Guide: reading the governance tabs, raw vs validated attacks, policy-hash facets, and degraded chains.
- `rqgm_migration.md` — Adopting `ari_rqgm` on an Existing Project: switching modes within one project, and back.
- `testing.md` — How to Test ARI Code: testing conventions for `ari-core` and beyond.
- `troubleshooting.md` — Troubleshooting: common runtime failures and their fixes.
- `virsci_integration.md` — VirSci Integration: the two independent surfaces VirSci reaches ARI through.
- `paperbench/` — PaperBench reproducibility workflow guides.
  - `README.md` — paperbench index.
  - `compute_node_safety.md` — Compute-node safety conventions (L1–L7): rules for `reproduce.sh` running on a fresh compute node.
  - `multi_node_setup.md` — Multi-node setup for PaperBench: going beyond the default single-node sandbox dispatch.
  - `paper_import.md` — Importing external papers: the paper registry and bringing in external papers.
  - `paperbench_gui.md` — PaperBench GUI guide: the dashboard's PaperBench sidebar entry.
  - `paperbench_quickstart.md` — PaperBench quickstart: a 5-minute walkthrough from import to viewing results.
  - `paperbench_troubleshooting.md` — PaperBench troubleshooting: common failure modes in the audit run pipeline and their fixes.
