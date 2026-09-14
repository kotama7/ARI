---
sources:
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-skill-paper-re/src/_paperbench_bridge.py
    role: implementation
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/src/sandbox.py
    role: implementation
  - path: ari-skill-paper-re/src/_compute/computer.py
    role: implementation
last_verified: 2026-08-16
---

# PaperBench API reference

All endpoints are served by the ARI viz server (`ari viz` /
`python -m ari.viz.server`) on the same host as the dashboard. JSON
bodies use `Content-Type: application/json`. DELETE-equivalent
operations go through POST `.../delete` to match the existing routing
conventions (see `ari-core/ari/viz/routes.py`).

## Papers

### `GET /api/paperbench/papers`

List every paper in the registry.

```json
{
  "papers": [
    {
      "paper_id": "2404.14193",
      "title": "LLAMP: assessing latency tolerance",
      "license": "cc by 4.0",
      "license_assessment": {"usable": true, "note": "permissive — usable"},
      "source_type": "arxiv",
      "source": "2404.14193",
      "imported_at": "2026-05-13T...",
      "registry_dir": "<registry_root>/papers/2404.14193"
    }
  ]
}
```

### `GET /api/paperbench/arxiv/<id>`

Fetch one paper's metadata from the public arXiv Atom API (6 s timeout)
so the import form can be pre-filled — the import dialog's "fetch
metadata" button is the in-tree caller.

```json
{
  "arxiv_id": "2404.14193",
  "title": "LLAMP: assessing latency tolerance",
  "authors": ["Alice", "Bob"],
  "year": 2024,
  "license": "arXiv non-exclusive",
  "license_assessment": {"usable": true, "note": "..."},
  "summary": "...",
  "pdf_url": "https://arxiv.org/pdf/2404.14193v1.pdf",
  "abs_url": "https://arxiv.org/abs/2404.14193"
}
```

Both new-style (`2404.14193`, `2404.14193v2`) and legacy
(`cs.LG/0102030`) identifiers are accepted, as is a leading `arxiv:`
scheme; the version suffix is stripped before the query and the
canonical form comes back as `arxiv_id`. `year` is the year of the
entry's `published` date and is `null` when that cannot be parsed;
`summary` is truncated to 1000 characters. `license` is *not* read from
the response — every arXiv entry is reported as `"arXiv non-exclusive"`
and run through the same classifier `POST .../papers/import` uses.

Failures answer HTTP 200 with an `error` key: an id the pattern rejects
(`not a valid arXiv id: '<id>'` — a DOI lands here), a non-200 or
unreachable API (`arXiv API returned HTTP <code>`, `arXiv fetch failed:
...`), a response that is not valid XML, or an id the API has no entry
for (`no arXiv entry for id <id>`).

### `POST /api/paperbench/papers/import`

Register a new paper. Body fields:

| Field | Required | Notes |
|---|---|---|
| `source_type` | yes | `arxiv` \| `doi` \| `upload` \| `local` |
| `source` | yes | identifier or path |
| `title` | yes | free-form |
| `license` | recommended | classified server-side; missing ⇒ `license: ""` with `usable: false` and the note "license unknown — manual review required" |
| `authors` | no | list of strings |
| `venue` / `year` / `artifact_url` | no | optional metadata |
| `paper_id` | no | defaults to sanitized `source`; sanitized to `[A-Za-z0-9._-]{1,64}` |
| `pdf_path` | no | absolute path to a local PDF; copied to `papers/<paper_id>/paper.pdf` |
| `ad_pdf_path` / `ae_pdf_path` | no | optional artefact appendices |
| `overwrite` | no | `true` ⇒ replace duplicate |

Returns the manifest entry on success, `{error: "..."}` on collision
(without `overwrite`) or validation failure.

### `POST /api/paperbench/papers/<paper_id>/delete`

Remove the manifest line + the on-disk paper directory. Idempotent.

```json
{"deleted": true, "paper_id": "2404.14193"}
```

An unknown id is not an error: the call still answers HTTP 200 with
`{"deleted": false, "reason": "not found", "paper_id": "<id>"}`.

### `POST /api/paperbench/papers/<paper_id>/metadata`

Patch the manifest entry. Pass any subset of writable fields
(`paper_id` itself is immutable). Re-classifies the license if the
`license` field is in the patch body.

### `GET /api/paperbench/papers/<paper_id>/license`

Returns the structured license assessment for a single paper:

```json
{
  "license": "cc by 4.0",
  "permissive": true,
  "modifiable": true,
  "redistributable": true,
  "usable": true,
  "note": "permissive license — ari may use freely"
}
```

## Runs

### `POST /api/paperbench/run`

Enqueue PaperBench runs.

```json
{
  "paper_ids": ["2404.14193"],
  "rubric_config":    {"model": "gemini/gemini-2.5-pro"},
  "reproduce_config": {
    "model": "gpt-5-mini",
    "time_limit_sec": 43200,
    "iterative_agent": false,
    "sandbox_kind": "slurm",
    "partition": "large",
    "nodes": 4,
    "ntasks": 32,
    "ntasks_per_node": 8,
    "exclusive": true,
    "gpus_per_task": 1,
    "gpu_type": "v100",
    "memory_gb_per_node": 256,
    "constraint": "skylake"
  },
  "judge_config":     {"model": "gpt-5-mini", "n_runs": 1, "code_only": false},
  "dry_run": false
}
```

`rubric_config` is the only block that is validated: an unrecognised key
fails the whole request with
`{"error": "unknown rubric_config fields: ..."}`. The accepted keys are
`model`, `target_leaf_count`, `temperature`, `seed`,
`paperbench_rubric_id`, `max_model_calls`, `subtree_concurrency`,
`provider`, `model_revision`.

`reproduce_config` and `judge_config` are *not* validated, and the viz
worker forwards only the keys it knows. For `reproduce_config` those are
`model`, `time_limit_sec`, `iterative_agent`, `sandbox_kind`,
`container_image`, `max_steps` (Stage 1) plus `partition`, `nodes`,
`ntasks`, `ntasks_per_node`, `exclusive`, `gpus_per_task`, `gpu_type`,
`memory_gb_per_node`, `constraint`, `cpu_bind`, `mem_bind`, `hint`,
`nodelist`, `extra_sbatch_args` (Stage 2). Anything else — `account`,
`qos`, `reservation`, `walltime`, `gpus_per_node` — is accepted by the
endpoint and then silently dropped on the way to the skill, even though
`run_reproduce` itself takes those arguments; supply them through the
rubric's `execution_profile` instead. `judge_config` forwards `model`
(renamed to `judge_model`), `n_runs`, `skip_negative_control` and
`code_only`.

Do not put `cpu_bind` or `mem_bind` in `reproduce_config`: the worker
forwards them, and the SLURM path then refuses the run with "cpu_bind and
mem_bind are srun job-step settings; place them explicitly in
reproduce.sh".

A `paper_id` that is not in the registry aborts the whole launch with
`{"error": "paper not in registry: <paper_id>"}` — jobs already created
for earlier ids in the same request are left running.

Response (real launch):

```json
{
  "dry_run": false,
  "job_ids": ["abc123..."],
  "estimated_cost": {
    "wall_time_sec": 43560,
    "llm_cost_usd": 2.55,
    "breakdown": { ... }
  }
}
```

When `dry_run: true`, no job is created; only the cost estimate is
returned alongside `papers` (count) and totals.

### `GET /api/paperbench/run/<job_id>`

Status snapshot. Fields: `status`, `current_stage`, `progress`,
`created_at`, `paper_id`, `results`, `error`, `logs`, plus the original
`configs`. An unknown id answers `{"error": "job not found", "job_id":
"<id>"}`.

`status` is one of `queued`, `running`, `completed`, `failed` — or
`interrupted`. Every job mutation is mirrored to
`{registry_root}/jobs/{job_id}.json`, so jobs survive a viz-server
restart; a persisted record still reading `queued`/`running` after the
restart means its worker thread died with the process, and the disk
reader reports it as `interrupted` with an explanatory `error`. Workers
are never respawned.

### `GET /api/paperbench/run/<job_id>/results`

Returns the grader output when the job's status is `completed`;
`{error: "results not available", status: "<state>"}` otherwise.

### `GET /api/paperbench/run/<job_id>/logs` (SSE)

A Server-Sent Events stream of the job's log buffer, served as
`Content-Type: text/event-stream` with `Cache-Control: no-cache` and
`Connection: close`. It is the only PaperBench GET route whose *handler*
answers a non-200 status: an unknown `job_id` is a real HTTP 404 with
`{"error": "job not found"}`, not the 200-plus-`error`-key body the
other GETs use. That is a statement about the handlers only — every
route, this one included, can still answer 401, because `_auth_gate()`
runs at the top of `do_GET` before any dispatch.

Each buffered line is one `log` event whose `id` is its index in the
buffer; the stream ends with a `done` event carrying the terminal
status.

```
id: 0
event: log
data: {"ts": "2026-05-13T05:57:00.512Z", "level": "info", "msg": "rubric starting"}

id: 1
event: log
data: {"ts": "2026-05-13T05:57:01.024Z", "level": "success", "msg": "pipeline complete"}

: heartbeat

event: done
data: {"status": "completed"}
```

Resume after a disconnect with `?since=<index>` or the `Last-Event-ID`
header; when both are present the larger index wins. The handler polls
once a second and writes a `: heartbeat` SSE comment on every poll that
does not end the stream, so a proxy does not drop the idle connection.
One stream lives at most five minutes — at the cap it writes
`: stream-timeout — reconnect` and closes, and `EventSource` reconnects
by itself. `completed`, `failed` and `interrupted` are all terminal: each
sends `done` and closes. On a token-protected bind the token rides in a
`token=` query parameter (see CORS / authentication below).

The buffer is in-memory, capped at the most recent 2000 entries per job,
and is *not* re-read from `{registry_root}/jobs/{job_id}.json`. A job
that survives only on disk therefore streams no `log` events and gets a
`done` immediately — `{"status": "interrupted"}` for a record the
restart left reading `queued`/`running`.

### `GET /api/paperbench/run/<job_id>/report`

Render (or re-render) the audit report for a completed job. All query
parameters are optional:

| Parameter | Default | Notes |
|---|---|---|
| `languages` | `en` | comma-separated on the query string: `languages=en,ja,zh` |
| `formats` | `pdf,html,md` | comma-separated: `formats=pdf,html` |
| `output_root` | `{registry_root}/reports/<job_id>` | destination directory |

Rendering is done by `report/scripts/paperbench_report.py`, imported
lazily from the repository tree so a viz server without a `report/`
directory still starts. Do not expect
`{"error": "report/scripts/paperbench_report.py not found"}` from a
missing file: that body is guarded on
`importlib.util.spec_from_file_location` returning no spec or no loader,
which it does not do for an absent `.py` path — the load then raises an
uncaught `FileNotFoundError` out of the request handler instead. The
renderer's own result — `{status, languages, paths, harvest}`, where
`harvest` carries `ors_score`, `leaves_total`, `leaves_passed` — is
returned verbatim when its `status` is not `ok`; otherwise the endpoint
adds `job_id` and a `download_urls` map from `<lang>/<fmt>` to an
on-disk path: `pdf` → `<output_root>/<lang>/build/main.pdf`, and
`html` / `md` / `tex` → `<output_root>/<lang>/main.<ext>`. Only files
that exist are listed, so `tex` shows up whenever the renderer left a
`main.tex` behind even though nothing requested that format.

Refusals are HTTP 200 bodies with an `error` key: `job not found` for an
unknown id, and `report not available until job completes` (with the
current `status`) for a job in any other state. A completed job whose
record carries no top-level `checkpoint_dir` or `repo_dir` answers `job
snapshot lacks checkpoint_dir; cannot render report` — the bundled
worker records the reproduction directory as `results.repo_dir`, not at
the top level, so a job launched through `POST /api/paperbench/run` gets
this unless something else filled the field in.

### `POST /api/paperbench/run/<job_id>/report`

The same handler for callers that would rather send a body than a query
string; the dashboard's results view uses it for the EN / JA / ZH report
buttons.

```json
{"languages": ["en"], "formats": ["pdf", "html", "md"]}
```

Here `languages` and `formats` are real JSON arrays — the
comma-splitting is a property of the GET query string only.
`output_root` is read the same way, and a well-formed body returns
exactly what the GET form returns.

## Cost estimate

### `POST /api/paperbench/cost-estimate`

Same body shape as `/api/paperbench/run` minus `paper_ids` and
`dry_run`. Returns wall-time + cost projections for one paper.

```json
{
  "wall_time_sec": 43560,
  "llm_cost_usd": 2.55,
  "breakdown": {
    "rubric":    {"wall_time_sec": 300, "cost_usd": 0.45},
    "reproduce": {"wall_time_sec": 43200, "cost_usd": 2.0},
    "judge":     {"wall_time_sec": 60, "cost_usd": 0.10}
  }
}
```

## CORS / authentication

The viz server is **same-origin only**: the request `Origin` is echoed
back in `Access-Control-Allow-Origin` only when it matches the server's
own origin (the `Host` header, or a loopback form on the server port).
A cross-origin request gets no ACAO header at all, so the browser
refuses the response. `ARI_GUI_CORS_ANY=1` restores the historical
unconditional `*` for tunnel/portal topologies where the page origin
cannot match the API origin.

Authentication depends on the bind. A loopback bind (the default)
resolves to no token and behaves as before. When `ARI_GUI_BIND` names a
non-loopback host, a single gate ahead of every `do_GET` / `do_POST` /
`do_PUT` / `do_PATCH` / `do_DELETE` requires
`Authorization: Bearer <ARI_GUI_TOKEN>` and answers 401 with a typed
JSON body otherwise; `/health*` is exempt, and the SSE job-log stream
accepts the same token as a `token=` query parameter because
`EventSource` cannot set headers. A remote bind with `ARI_GUI_TOKEN`
unset generates and prints a token rather than starting
unauthenticated; `ARI_GUI_AUTH=0` disables the gate. Do **not** expose
the server on a public interface without an upstream reverse proxy.

## Bridge contract (in-process Python surface)

For callers running in-process (orchestrators, dogfood scripts, custom
pipelines), `ari-skill-paper-re/src/_paperbench_bridge.py` exposes three
keyword-only async callables matching PaperBench's 3-stage protocol
(arXiv:2504.01848 §3). All three share the same
`(paper_md, work_dir-or-submission_dir, model, …)` vocabulary so they
can be chained:

| Stage | Function | Wraps |
|---|---|---|
| 1 — Agent rollout | `rollout_submission(paper_md, work_dir, agent_model, sandbox_kind, container_image, iterative_agent, env, agent_env_path, forbid_host_filesystem, blacklist_urls, time_limit_sec, …)` | `_replicator_agent.run_replicator_agent` (vendor BasicAgent / IterativeAgent) |
| 2 — Reproduction | `reproduce_submission(submission_dir, sandbox_kind, container_image, time_limit_sec, network_policy, network_isolation_attested, partition, gpus_per_task, gpu_type, memory_gb_per_node, exclusive, extra_sbatch_args, capture_tarball, tarball_dir)` | `server.run_reproduce` (typed HPC handle or host sandbox dispatch; the deprecated `extra_sbatch_args` reader now accepts only `--account=`, `--qos=`, `--reservation=` and `--hint=` and raises on anything else) |
| 3 — Grading | `judge_submission(paper_md, rubric, submission_dir, reproduce_log, judge_model, paper_audit_mode, code_only, …)` | vendor `SimpleJudge` direct |

Vendor-fidelity behaviour built into the bridge:

- **submission-root resolution (v0.8.0)** — `reproduce_submission` and
  `judge_submission` descend into a nested `submission/` when the agent
  built its self-contained repo there (the workspace presents the
  vendor's `/home/submission` as a workspace-relative `submission/`, so an
  agent following the prompt nests one level). Reproduction/grading then
  run where `reproduce.sh` is co-located with its sources, matching the
  vendor reproducer's cd-into-submission semantics; an orphaned top-level
  `reproduce.sh` copy is ignored. This is what stops the
  `src/…: No such file or directory` build failure that otherwise zeros
  every Code Execution / Result Analysis leaf.
- **apply_patch command parity (v0.8.0)** — the host-side `LocalComputer`
  exposes the vendor's own `apply_patch.py` on PATH (as both `apply_patch`
  and `applypatch`), mirroring the vendor Docker image's
  `/bin/apply_patch`. gpt-5 / codex agents reflexively edit files via
  `apply_patch <<'PATCH' … PATCH`; without this they fail `command not
  found` and waste tool-call budget. Apptainer SIFs already carry the
  command, so the shim is host-sandbox-only.
- **immutable container identity** — local non-symlink SIF files are hashed;
  Docker accepts a full `sha256:<image-id>` or `name@sha256:<digest>`;
  remote Apptainer references require `@sha256:<digest>`. Mutable tags and
  the former `pb-env` / `pb-reproducer` aliases fail closed.
- **agent.env auto-load** — when `agent_env_path` unset, auto-discovers
  `$ARI_AGENT_ENV_PATH` then `~/.ari/agent.env`. `HF_TOKEN` from the
  calling process env is automatically forwarded to the agent.
- **forbid_host_filesystem** — refuses `sandbox_kind=local/slurm`
  combinations (host-FS leak surface). Default False preserves
  development workflows.
- **blacklist_urls** — prepends a `FORBIDDEN URLS` block to the
  agent's instruction prompt AND exports `ARI_BLACKLIST_URLS` env var
  so downstream tool wrappers can refuse.
- **no source-mutating salvage** — the vendor's
  `reproduce_on_computer_with_salvaging` retry (which rewrites the
  submission's environment before re-running) has no bridge equivalent;
  `salvage_retries` / `retry_threshold_sec` are not parameters of
  `reproduce_submission`, and
  `test_reproduce_submission_signature_includes_tarball_not_unsafe_salvage`
  asserts `salvage_retries`'s absence. A failed reproduction is retried by calling
  `reproduce_submission` again with the same plan, which appends an
  immutable linked attempt rather than mutating `reproduce.sh`.
- **capture_tarball** (default True) — writes a timestamped
  `submission_executed_<UTC>.tar.gz` beside the *executed* submission
  inside the private attempt tree (not beside the caller's
  `submission_dir`) unless `tarball_dir` overrides the destination, and
  returns `executed_tarball`, `executed_tarball_digest` and
  `executed_tarball_size_bytes`. A capture failure is non-fatal: it is
  logged and appended to the result's `warnings` list.
- **code_only** — when True, prunes the *rubric tree* to `Code
  Development` leaves via the vendor `TaskNode.code_only` reduction
  (vendor `paperbench/grade.py:109-112`). It is for the case where Stage 2
  was deliberately skipped, so Code Execution / Result Analysis leaves are
  not graded against an empty submission. It does not substitute for a
  reproduction record: `grade_with_simplejudge` still requires a verified
  `ReproductionRunV1` with `status == "succeeded"` and otherwise returns a
  report with `status: "failed"` and `ors_score: null`.
- **paper_audit_mode** — patches vendor `TASK_CATEGORY_QUESTIONS` to
  paper-audit phrasing. Mutually exclusive with `code_only`.

Fail-loud preconditions (there is no host-local downgrade). None of
these reach the caller as an exception: `run_reproduce` catches the
failure, records it as an immutable failed attempt, and returns a dict
carrying `executed: false`, `error` and a `failure_kind`
(`sandbox-unavailable`, `scheduler-failure`, `network-policy`) — or, when
the plan is rejected before an attempt exists,
`{"executed": false, "error": "reproduction plan rejected: ..."}`.

| Condition | Remedy |
|---|---|
| `sandbox_kind=docker/apptainer/singularity` but the runtime binary is not on `PATH` (checked with `which` at launch — the daemon itself is never probed for an explicit `docker` request) | install the runtime or select another reviewed sandbox |
| `sandbox_kind=docker/apptainer/singularity` with no `container_image` and no `ARI_PHASE1_DOCKER_IMAGE` / `ARI_PHASE1_APPTAINER_IMAGE` | supply an immutable image; the plan is rejected with "requires an immutable container image" |
| Container image that is not immutably pinned (mutable Docker tag, remote Apptainer ref without `@sha256:`, symlinked SIF) | pin it; see "immutable container identity" above |
| `sandbox_kind=slurm` but `sbatch` missing or no partition resolved | configure the scheduler/partition |
| `sandbox_kind=local`/`slurm` under the default `network_policy="deny"` | a non-container substrate cannot prove network denial: pass `network_policy="inherit"` explicitly, supply `network_isolation_attested=True`, or run in a container |
| `cpu_bind` / `mem_bind` passed to a SLURM reproduction | put the binding in `reproduce.sh`; the scheduler path refuses these as srun job-step settings |
| GPU request unsupported by the selected partition | fix GRES/select a compatible partition; no silent downgrade |

## See also

- [PaperBench GUI guide](../guides/paperbench/paperbench_gui.md)
- [PaperBench quickstart](../guides/paperbench/paperbench_quickstart.md)
- [Environment variables](environment_variables.md)
- [MCP tool reference](mcp_tools.md)
- [Execution profile reference](execution_profile.md)
- Source:
  `ari-core/ari/viz/api_paperbench.py`
  /
  `ari-skill-paper-re/src/_paperbench_bridge.py`
  /
  `ari-skill-paper-re/src/server.py`
