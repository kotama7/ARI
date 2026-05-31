# Checkpoint / Run / Artifact Model (requirement 07)

Task-control note from `07_checkpoint_run_artifact_model.md`. Captured
2026-05-30 from a 3-agent mapping of the filesystem-touching modules vs the
canonical `PathManager`. This is primarily an **assessment + documentation**
requirement (§5: introduce helpers "only if justified"; §11: refactoring the
active-checkpoint global is high-risk → a dedicated requirement).

## 1. Concept glossary → on-disk (also folded into `docs/reference/glossary.md`)

| Concept | On-disk thing | Authority |
|---------|---------------|-----------|
| **workspace (root)** | dir holding `checkpoints/`, `experiments/`, `staging/`, `paper_registry/` | `PathManager.root` (pinned via `ARI_CHECKPOINT_DIR`) |
| **run** | a `run_id` = `YYYYMMDDHHMMSS_<slug>`; spans the checkpoint + experiments bucket | `PathManager` (keys both trees by run_id) |
| **project** | *no global project dir* — per-run scope; `{checkpoint}/settings.json`, `memory.json` | `PathManager.project_settings_path/_memory_path` |
| **checkpoint** | `{workspace}/checkpoints/{run_id}/` (run state: tree.json, results.json, idea.json, cost_*, settings.json, .ari_pid, uploads/) | `PathManager.checkpoint_dir` |
| **node** | a BFTS tree node: an entry in `tree.json`'s `nodes[]` **and** a work_dir | `orchestrator/node.py` + `PathManager.node_work_dir` |
| **node work_dir** | `{workspace}/experiments/{run_id}/{node_id}/` (under `experiments/`, not the checkpoint) | `PathManager.node_work_dir` |
| **artifact** | a non-meta file inside a node work_dir (negative of `is_meta_file`) | `PathManager.is_meta_file` / `META_FILES` |
| **log** | no separate tree: `log_dir(run_id) == checkpoint_dir`; main = `{ckpt}/ari.log`; any `*.log` is meta | `PathManager.log_file` |
| **file** | surfaceable = not meta; `uploads/` (user inputs), `staging/{ts}/` (pre-launch) | `PathManager.uploads_dir` / `new_staging_dir` |
| **result(s)** | `{checkpoint}/results.json` (one of tree.json / nodes_tree.json / results.json) | `checkpoint.py:save_results_json` |

`checkpoint.py` owns tree/nodes_tree/results JSON I/O (relative to a passed-in
`checkpoint_dir`; it does not itself use `PathManager`). `pidfile.py` owns
`.ari_pid` at the checkpoint root (`.ari_pid` is in `META_FILES`).
`node_report.json` is written into each node work_dir by
`orchestrator/node_report/builder.py`; the v0.5→v0.7 backfill lives in
`migrations/v05_to_v07/node_reports.py` (re-exported via
`orchestrator/node_report/legacy_reconstruct.py`) and **must keep working**
(driven by `ari migrate node-reports`).

## 2. Ad-hoc path assumptions across viz modules

| Module | Uses PathManager? | Encodes |
|--------|-------------------|---------|
| `checkpoint_finder.py` | no | 7 legacy search bases (`workspace/checkpoints`, `./checkpoints`, `ari-core/checkpoints`, cwd variants); pid probe via `ari.pidfile` |
| `checkpoint_api.py` | no | `^[0-9]{8,14}_` ckpt regex; tree.json/nodes_tree.json precedence; review/repro/ors_*/science_data/figures/vlm filenames; `full_paper.tex` + `paper/` |
| `checkpoint_lifecycle.py` | **yes** (`experiments_root`) | `checkpoints/` delete guard; `ari_run_*.log`, `launch_config.json`, `node_{name}_*` legacy glob |
| `file_api.py` | no | `paper/` (`PAPER_DIR_NAME`), `full_paper.{tex,pdf,bbl}`, `refs.bib`, `fig_*` globs, text-ext set |
| `node_work_api.py` | **yes** (`experiments_root`, `is_meta_file`) | `^[0-9]{8,14}_(.+)$` run_id→slug regex; legacy `experiments/*/{node_id}` scan |

## 3. Divergences (real bug risk) vs consistent repeats

**REAL DIVERGENCE #1 (fixed in this PR).** Three resolvers of "the active node
tree" disagreed: `ari.checkpoint.load_nodes_tree` (canonical) and
`state_sync._load_nodes_tree` (live WebSocket, delegates to it) honor the
precedence `tree.json → nodes_tree.json → newest non-empty node_*/tree.json`
(legacy). But `checkpoint_api._api_checkpoints` and `_api_checkpoint_summary`
used inline `tree.json`/`nodes_tree.json`-only probes that **omitted the legacy
`node_*/tree.json` fallback**. Consequence: a legacy checkpoint rendered
`node_count=0` / no status in the list+summary cards while the live tree showed
it correctly — exactly the legacy-variant trap §11 warns about.

→ **Fix (purely additive in both functions):** each function keeps its original
inline flat-file probe **verbatim** — `tree.json`/`nodes_tree.json` with the
`st_size>0` guard and `errors="replace"` — so every corrupt-file corner case
(0-byte `tree.json` beside a valid `nodes_tree.json`; invalid-UTF8 inside
`tree.json`) stays byte-identical. The canonical
`ari.checkpoint.load_nodes_tree` (via a thin monkeypatch-friendly wrapper
`checkpoint_api._load_nodes_tree`) is consulted **only when neither flat file
exists**, adding the legacy `node_*/tree.json` fallback. So the common and
edge/corrupt cases are unchanged; only the legacy `node_*/`-only case changes —
from wrong (`node_count=0`) to correct. Both call sites are symmetric. The
summary path additionally retains its direct-read `{_parse_error}` envelope.
Pinned by `tests/test_checkpoint_legacy_tree.py` (3 tests). An adversarial
2-lens review confirmed `behaviorPreserved=true` + `legacyFixedCorrectly=true`
(the symmetric rewrite closed the two corrupt-file nits a wholesale replacement
would have introduced).

**DIVERGENCE #2 (left as-is, lower risk).** Within `checkpoint_api`,
`_api_checkpoints` starts from `nodes_tree.json` (override to tree.json) while
`_api_checkpoint_summary` starts from tree.json (fallback to nodes_tree.json).
Both net out to "prefer tree.json when both are valid+non-empty" and differ only
in empty-file tie handling. The req-07 fix kept both inline probes verbatim
(adding only the legacy fallback), so this minor pre-existing inconsistency is
**unchanged** — deliberately not "fixed", to keep the change purely additive.

**Not divergences (consistent literals — deliberately NOT touched):** the
`^[0-9]{8,14}_` regex repeated in `checkpoint_api` vs `node_work_api`; the
`full_paper.tex` + `paper/` probing in `file_api` vs `checkpoint_api`; the
legacy experiments-bucket scans in `checkpoint_lifecycle` vs `node_work_api`.
Same results, repeated code.

## 4. Helper decision (conservative)

Exactly **one** consolidation was justified + low-risk for req 07: route the two
`checkpoint_api` tree reads through the existing canonical resolver (above) — it
reuses the authority the requirement already names (`ari.checkpoint` /
`PathManager`), is additive, and changes no on-disk format. Everything else was
**deferred** because each touches a legacy variant the duplicated code still
happens to handle:

- A generic checkpoint/run/artifact path facade over `checkpoint_finder`'s 7
  search bases — `PathManager` assumes a single `workspace_root`; collapsing the
  search list risks dropping a legacy discovery path.
- A `paper/` path helper (file_api `PAPER_DIR_NAME` + `full_paper.*` + `fig_*`)
  — viz-only convention, would touch the Overleaf-like editor + PDF copy-back.
- De-duping the run_id/slug regex + experiments legacy-bucket scans
  (`node_work_api` + `checkpoint_lifecycle`) — touches the **destructive** delete
  path; higher risk.
- Reducing the `ari.viz.state` active-checkpoint global coupling — §11 flags this
  as high-risk; belongs in a dedicated requirement.

These are recorded as follow-up candidates (req 07 §12).

## 5. Frontend type alignment

No breaking renames warranted: the frontend uses `Checkpoint`/`CheckpointSummary`
consistent with the glossary (checkpoint == run; no "project"). The only safe
additive opportunity is doc-comments on `TreeNode` (it is the wire shape of an
orchestrator `Node` via `to_dict()`, with extra UI-only fields `node_type`/
`score`/`hypothesis`/`description`). **Deferred** to keep this PR's frontend
surface zero (the req-04/06 doc-comment precedent can absorb it later) — recorded
as a follow-up.

## 6. Checks

`pytest ari-core/tests` — green (full suite; +3 legacy-tree guards, +earlier req
guards). No on-disk format change; existing + legacy checkpoints load unchanged.
Real-environment dashboard smoke (`ari viz` opening an existing checkpoint) is
environment-gated (compute node) — the legacy-tree guard test stands in for the
behavior on the login node.

## 7. Follow-up candidates (→ §12)

- Checkpoint-discovery facade over the 7 search bases (low value, legacy risk).
- `paper/` artifact-path helper (viz-only).
- De-dupe run_id/slug regex + experiments-bucket scans (touches delete path).
- Reduce `ari.viz.state` active-checkpoint global coupling (dedicated requirement).
- Additive `TreeNode` doc-comments tying it to `orchestrator/node.py::to_dict()`.
- A dedicated, separately-planned checkpoint migration if the format ever changes.
