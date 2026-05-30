# Testing & Smoke-Guard Matrix (baseline)

Produced by requirement `13_testing_smoke_guards.md` (now deleted).
Task-control baseline note. Captured on branch `refactoring` (2026-05-30),
host `login1.cloud.r-ccs.riken.jp` (a **login node** — SLURM/GPU/real-LLM checks
are environment-gated, not run here).

## 1. How tests run today

- `pytest.ini`: `--import-mode=importlib`, `asyncio_mode=auto`, `testpaths =
  ari-core/tests` (the in-process-safe set). Importlib mode lets the many
  same-basename test modules coexist.
- `scripts/run_all_tests.sh`: runs **each skill's tests in its own pytest
  process** to avoid the cross-skill `src.server` `sys.modules` collision (each
  skill ships its own `src/server.py`; one process would poison
  `unittest.mock.patch("src.server.X")` across skills). Paths run: `ari-core/tests`
  + 12 skill suites (paper, paper-re, web, hpc, idea, evaluator, memory, coding,
  replicate, vlm, transform, benchmark). `orchestrator` and `plot` skills have **no
  `tests/`** and are not listed.
- Frontend (`ari-core/ari/viz/frontend`): `npm run typecheck` (`tsc --noEmit`),
  `npm run build` (`vite build` → `../static/dist`, gitignored), `npm test`
  (`vitest run`, jsdom). vitest includes `src/**/__tests__/**/*.test.tsx` and
  `src/**/*.test.tsx`.

## 2. Baseline run (recorded 2026-05-30)

| Check | Result |
|-------|--------|
| `pytest ari-core/tests -q` | **2210 passed, 16 skipped, 0 failed** (~126s). Clean. 16 skips are env-gated (no GPU / no live Letta / no remote SLURM). |
| `scripts/run_all_tests.sh` | **329 passed, 19 failed, 8 skipped** (see §2a). Every failure/error is a missing optional dependency or test-env import isolation on this login node — **no product-code regression**. |
| `npm run typecheck` | **FAILS (pre-existing)** — only in `__tests__` files: `toBeInTheDocument`/`toBeDisabled` missing (no `@testing-library/jest-dom` type augmentation in tsconfig) and `global` undefined in `PaperBenchWizard.test.tsx`. No production `src` type errors. |
| `npm run build` | **passes** (~3s). Largest chunks: `index` 198kB, `WorkflowPage` 128kB, `ResultsPage` 61kB. |
| `npm test -- --run` | **4 passed, 2 failed (pre-existing)**. Both failures are brittle `getByDisplayValue('')`/`getByDisplayValue('0')` queries matching multiple inputs (`PaperImportDialog.test.tsx:118`, `PaperBenchWizard.test.tsx:64`). NOT regressions — present on clean checkout. |

**Suspected-wrong pinned behavior (do NOT treat as spec):**
- The 2 failing frontend tests are brittle DOM queries, not real product
  contracts. Do not "preserve" them; if `03` touches PaperBench they should be
  rewritten to query by role/label.
- `npm run typecheck` failing on test files is a tooling gap (missing jest-dom
  types), not a source defect. A follow-up may add the type reference; out of
  scope for refactors that don't touch the frontend toolchain.

### 2a. Skill suite results (`run_all_tests.sh`, 2026-05-30)

Aggregate **329 passed / 19 failed / 8 skipped**. Per-suite:

| Suite | Result | Failure cause (all env/import, none are code regressions) |
|-------|--------|-----------------------------------------------------------|
| paper | 60 passed | — |
| paper-re | 38 passed | — |
| hpc | 6 failed, 24 passed | `test_slurm_remote.py` × 6 → `No module named 'paramiko'` (SSH lib absent) + remote SLURM env-gated |
| web | 1 error (collection) | `No module named 'semanticscholar'` / `chz` (optional deps absent) |
| idea | 6 passed | — |
| memory | 1 failed, 37 passed, 7 skipped | `test_global_tools_removed.py` → `from src import server` `No module named 'src'` (per-skill `src` path not set in this subprocess) |
| coding | 1 failed, 23 passed | `test_run_bash_uses_container_when_env_set` → `from ari.public import container` `No module named 'ari'` (ari-core not importable in that subprocess's env) |
| replicate | 101 passed | — |
| vlm | 11 failed, 19 passed | all → `No module named 'PIL'` (Pillow absent) |
| transform | 21 passed | — |
| benchmark | 1 error (collection) | `No module named 'numpy'` |
| evaluator | passed | — |

Missing optional deps observed: `PIL`(11), `paramiko`(6), `chz`(4), `numpy`(1),
`semanticscholar`(1), `structlog`(1). Install these on a compute node to clear
the env-gated failures; none indicate a defect in product code. `ari-core` (the
in-process-safe set, 2210 passed) is the trustworthy green baseline.

## 3. Environment-gated checks (cannot run on login node — not "skipped-and-forgotten")

`./start.sh`, `./start.sh gui`, `./start.sh status`, `./shutdown.sh`, `ari viz`
(need the service stack / browser), plus skill tests needing real SLURM
(`ari-skill-hpc/test_slurm_remote.py`), live Letta
(`ari-skill-memory/test_letta_live_integration.py`,
`test_letta_restart_live.py`), GPU (`test_ollama_gpu.py`), or real LLM. Run these
on a compute node before merging any requirement that touches those surfaces.

## 4. Test-command matrix per requirement

| Req | Area | Minimal required checks |
|-----|------|-------------------------|
| `02` frontend api client | frontend services | `npm run typecheck` (no NEW errors vs baseline), `npm test -- --run` (no NEW failures), `npm run build` |
| `03` component decomposition | frontend pages | same 3 frontend checks; add render smoke test for any extracted component |
| `04` state/hooks/types | frontend | same 3 frontend checks |
| `05` viz routes service extraction | viz backend | `pytest ari-core/tests -q` (esp. `test_server.py`, `test_api_*`, `test_file_explorer.py`); **add endpoint-shape guard before extracting** |
| `06` viz api schema contract | viz REST/WS | `pytest ari-core/tests/test_server.py ari-core/tests/test_api_*`; **WebSocket has zero tests — add a message-shape guard first** |
| `07` checkpoint/run artifact model | checkpoint | `pytest ari-core/tests/test_*checkpoint* test_ear.py test_paths.py test_orchestrator.py`; **add a checkpoint load/parse characterization test first** |
| `08` config/settings/workflow | config | `pytest ari-core/tests/test_config.py test_settings_*.py test_launch_config.py test_workflow_*.py` (good existing coverage) |
| `09` core/skill public contract | boundary | `pytest ari-core/tests/test_public_api_boundary.py`; `run_all_tests.sh` (skill suites); re-run dep grep from `01` note |
| `10` pipeline/workflow phase | pipeline | `pytest ari-core/tests/test_pipeline_e2e.py test_bfts*.py test_workflow_contract.py test_data_flow.py` |
| `11` llm backend boundary | llm | `pytest ari-core/tests/test_llm*.py`; **add error/fallback guard — current llm tests are happy-path/mocked** |
| `12` hpc/container subprocess | container/hpc | `pytest ari-core/tests/test_container.py`; `ari-skill-hpc/tests` (slurm_local OK; slurm_remote env-gated) |
| `14` migration & deletion | meta | re-run full matrix; confirm `requirements/` empty |

## 5. Coverage gaps (high-risk surfaces with weak/no guards)

- **WebSocket messages — ZERO tests.** `ari-core/ari/viz/websocket.py` emits
  `{"type":"update","data":<tree>,"timestamp":<iso>}`; no test pins this shape or
  connection lifecycle. **Highest-priority gap for `06`.**
- **Checkpoint load/parse** — delete + enumerate are tested; no test for
  parsing valid/corrupt/malformed checkpoint files or version migration. Add
  before `07`.
- **LLM backend** — only happy-path/mocked (`test_llm.py`, `test_llm_routing.py`);
  no error/timeout/fallback/response-validation tests. Add before `11`.
- **Dashboard REST shapes** — PaperBench + lineage endpoints tested; `api_settings`,
  `api_wizard`, `api_workflow`, `api_experiment` REST contracts not shape-tested.
  Add targeted guards before `05`/`06`.
- Config precedence and pipeline phases are **well covered** already.

## 6. Guard tests added by this requirement

None added in this pass: `ari-core` baseline is green and the existing matrix
already covers `08`/`10` well. The three priority gaps (WebSocket shape,
checkpoint parse, LLM error/fallback) are deliberately deferred to the
requirement that first touches each surface (`06`, `07`, `11`) so the guard pins
behavior immediately before it is refactored — recorded here so they are not
forgotten. This is a documented scope decision, not silent truncation.

## 7. Follow-up candidates

- Add `@testing-library/jest-dom` type reference so `npm run typecheck` passes on
  test files (frontend tooling task, outside refactor reqs).
- Rewrite the 2 brittle PaperBench frontend tests to role/label queries (fold into `03`).
- Boundary-enforcement lint (import-linter / eslint no-raw-fetch) from `01`/`09`/`11`.
- CI wiring for this matrix (separate task, outside `refactoring/`).
