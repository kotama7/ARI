---
sources:
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: ari-core/ari/config/resolver.py
    role: implementation
  - path: ari-core/ari/viz/v1/config_api.py
    role: implementation
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/viz/v1/secrets.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/v1/catalogs.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigBrowser/ConfigBrowserPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/ConfigStudioPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/LaunchPanel.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/ExecutionSection.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/modeIntents.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/SecretField.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/StudioPickers.tsx
    role: implementation
  - path: ari-core/tests/test_gui_config_resolver.py
    role: test
  - path: ari-core/tests/test_gui_v1_launch.py
    role: test
  - path: ari-core/tests/test_gui_v1_mode_selection.py
    role: test
  - path: ari-core/tests/test_gui_secret_readiness.py
    role: test
last_verified: 2026-08-16
---

# Configuration Studio Guide

Two screens share one canonical field registry:

- **Config** (`#/config?run=`) — read-only. *What configuration did this
  run actually use, and where did each value come from?*
- **Studio** (`#/studio`) — the editing extension. *What should the next
  run use?* Project defaults, run templates, run drafts, and the launch
  flow.

Both are v2 workspaces, so they need the `gui_v2` capability (see the
[Dashboard guide](dashboard.md)). Neither of them can edit a run that is
already running: a checkpoint's configuration is explained post-hoc, never
rewritten.

## The field registry

Everything on both screens is generated from one machine-readable
inventory of the declared `ARIConfig` leaves merged with a hand-authored
metadata overlay. Today that is **205 leaves with 100 % metadata
coverage** — the registry build raises rather than shipping a field with
no metadata, so a new config field cannot silently appear without a
category, level, scope, sensitivity and mutability.

Current categories: Governance (104), Models (32), Search (BFTS) (24),
Proposal routing (14), Manuscript completeness (10), Scientific assurance
(6), Infrastructure (5), Evaluation (4), Execution mode (4), Skills (2).

The registry is served by `GET /api/v1/config/schema`. It carries
**metadata only** — never an effective value — and `secret_reference`
fields carry no default at all.

## Inspecting effective configuration (`#/config?run=`)

Open the page **with** a run and you get the resolved manifest for that
checkpoint; open it **without** `?run=` and it degrades honestly to a
schema browser showing default values ("No run selected — showing the
configuration schema with default values").

Each row shows the dotted path, the effective value, a **provenance
source** badge, a **mutability** badge, the low-confidence marker when
applicable, and any `applies_when` note. A search box filters by path or
category, so every one of the 205 fields stays discoverable. Resolver
warnings are listed verbatim in their own panel — nothing is silently
dropped.

![The Config browser for one run: a resolver-warnings panel, a filter box next to the field counter, and the per-category tables listing each dotted path with its effective value, a provenance source badge and a mutability badge; the llm.api_key row reads "secret (reference only)"](../assets/images/en/dashboard_config.png)

The counter next to the filter box can read higher than 205. Any leaf the
resolved manifest carries that the registry does not know is still shown,
grouped under **Other** — a manifest path is never dropped just because it
has no registry metadata.

The manifest itself comes from `GET /api/v1/runs/{run_id}/resolved-config`
and is produced by the `legacy-compatible-1` resolver, which reconstructs
what the imperative CLI chain would have produced, without running it.

### Provenance badges (existing checkpoint)

The resolver replays these layers in order; the badge names the layer that
won:

| Badge | Layer | Confidence |
|---|---|---|
| `default` | pydantic model defaults | high |
| `workflow` | `{checkpoint}/workflow.yaml` | high |
| `launch_config` | `{checkpoint}/launch_config.json` | high |
| `env` | the **current** process environment, documented `ARI_*` vars only | **low** |
| `checkpoint_state` | `{checkpoint}/rqgm_state.json` persisted mode | high |

`env` is marked **low confidence** on purpose: it reflects the environment
*now*, not necessarily the environment the run was launched in. A
low-confidence marker means "this attribution is reconstructed, treat it
as a hypothesis".

The new-run preview (used by the Studio launch flow) uses a different,
longer stack with its own badges: `default` → `workflow` (bundled) →
`profile` → `project` → `template` → `draft` → `env`.

### Mutability badges

| Badge | Meaning |
|---|---|
| `draft` | freely editable while the run is still a draft |
| `new_run_only` | fixed once a run starts; change it for the *next* run |
| `resume_mutable` | may be changed when resuming an existing run |
| `read_only` | never accepted from the config API, at any scope |

Before launch, the new-run preview reports every non-`read_only` field as
mutable — `new_run_only` only bites after the run exists.

### Secrets in the browser

A `secret_reference` row renders the literal text
**`secret (reference only)`**. There is no value to reveal and no toggle
to reveal one: the backend excludes secret leaves from `values`,
`provenance` and the manifest digest entirely, and surfaces them only as
configured/not-configured flags. The digest is `sha256:` over the redacted
canonical values, so it is stable and leak-free.

`resolved_at` is derived from source-file mtimes, never `now()`, so
repeated GETs of the same unchanged checkpoint are byte-stable.

## Editing in the Studio (`#/studio`)

The Studio is the same registry rendered as a form. Controls are derived
from metadata, not hand-written per field: `enum` → select, `bool` →
switch, `int`/`float` → number input, `str` → text input,
`secret_reference` → the write-only secret control, composite types
(lists, dicts, nested models) → an explicitly **disabled** input with the
reason shown ("Composite field — edit via workflow.yaml (custom editor
pending)."). Unavailable controls always say why; they are never silently
hidden.

![The Studio: the scope tab strip across the top, the template and draft creation controls, the category list on the left, and the generated form on the right — a select, plain text inputs, and the write-only secret control with its name picker, "configured (repo_env)" badge and password field; the footer carries Save changes, Discard edits, the unsaved-edit state and the document revision](../assets/images/en/dashboard_studio.png)

Model/provider suggestions come from the server catalog
(`GET /api/v1/config/catalogs/models`) — there are no model constants in
the frontend.

Each field row also carries a status badge: `edited` (unsaved local
change), `saved` (present in the stored document), or `default` (nothing
stored — the field falls through to the layer below).

### How a control is chosen

The page reads the registry entry and stops at the first match:

1. `sensitivity` is `secret_reference` → the write-only secret control;
2. a non-empty `enum` → a select;
3. otherwise the `value_type` string is split on `|` and `None` is
   dropped. If exactly **one** member is left: `bool` → switch,
   `int`/`float` → number input, `str` → text input;
4. anything else → composite — more than one member left after the split,
   or a `list[…]` / `dict[…]` / nested-model annotation.

So `sensitivity` outranks `enum`, and `enum` outranks the type. An
enum-valued secret would still get the secret control, and an
integer-valued enum would still get a select rather than a number input.

**Known gap: there is no `field path/pattern → custom editor` registry.**
The GUI plan for this workspace called for one, so that a domain-specific
field could claim a richer control by declaring itself instead of by
changing the page. That registry was never built. The two renderings that
are *not* derived from `value_type` are structural special cases compiled
into the page, not entries a field can register for:

- `sensitivity: secret_reference` selects the secret control. This one is
  keyed on metadata, so a future secret leaf would inherit it
  automatically — today `llm.api_key` is the registry's only secret leaf.
- A field whose `category` is `Execution mode`, or whose path starts with
  `rqgm.`, is routed into the Execution section (below, *Execution mode:
  selectable; governance tuning: still file-only*) before the generic
  table is built at all.

Inside the control renderer exactly one literal path is special-cased:
`llm.model` is the field that gets the model-catalog datalist. Every other
field renders from the rules above.

The consequence for anyone adding a config field: you get a generated
control for free, and there is nowhere to register a better one. The
schema entry carries no per-field editor hint — its keys are `path`,
`value_type`, `default`, `enum`, `required`, `category`, `level`, `scope`,
`sensitivity`, `mutability`, `applies_when`, `notes`, `source` and
`env_override` — so giving one path a bespoke editor today means editing
the Studio page component itself. That is why every composite leaf —
`skills`, `resources`, `evaluator.axis_weights`, `evaluator.custom_axes` —
is rendered as a disabled input naming the reason rather than as an
editor. The value is still displayed and is never hidden; it is simply not
editable from this screen.

### Three scopes

The scope bar switches the document you are editing; the hash records it:

| Scope | Hash | Document | Endpoint |
|---|---|---|---|
| Project defaults | `#/studio` | the single `default` project config | `GET/PATCH /api/v1/projects/default/config` |
| Run template | `#/studio?template=<id>` | a reusable named template | `GET/POST /api/v1/run-templates`, `GET/PATCH/DELETE .../{id}` |
| Run draft | `#/studio?draft=<id>` | one pending run | `POST /api/v1/run-drafts`, `GET/PATCH .../{id}` |

Create a template by supplying a lowercase `template-id` and a display
name; create a draft optionally *from* a template, optionally with a
**goal** (free text). The goal is a document field, not a config path —
it never rides `values`, and the launch materializes it as
`{checkpoint}/experiment.md`.

Switching documents drops the unsaved edit buffer and clears result
banners, so edits from one document can never leak into another.

### Where the documents live

All three kinds are stored server-side under
`{workspace_root}/gui_store/` — a sibling of `checkpoints/`:

```text
{workspace_root}/gui_store/
├── project_config.json
├── run_templates/{template_id}.json
├── run_drafts/{draft_id}.json
└── launches/{idempotency_key}.json
```

This is a **GUI-only convenience layer**. There is no `~/.ari` global
directory, templates survive checkpoint deletion, and the CLI /
`simple_bfts` path never reads any of it — a launch materializes every
effective value into the checkpoint exactly as it always did. Writes are
atomic (same-dir temp file + `fsync` + `os.replace`) with owner-only
permissions (`0600` files, `0700` dirs).

### If-Match conflicts

Every document carries an integer `revision`, and every mutation must
echo it:

```http
PATCH /api/v1/projects/default/config
If-Match: "3"
Content-Type: application/json

{"values": {"bfts.max_total_nodes": 40}}
```

- **No `If-Match`** → `400 invalid_request`
  (*mutations require the `If-Match: "<revision>"` header*).
- **Stale `If-Match`** → `409 revision_conflict`.
- `If-Match: "0"` means "this document must not exist yet" (create).

In the UI a 409 raises the **Revision conflict** panel:

> This document changed on the server since it was loaded. Reload to get
> the latest revision — your unsaved edits are kept locally.  [Reload]

**What to do:** click Reload. It refetches the document at its current
revision; your pending edits stay in the local buffer, so nothing is
silently discarded and nothing is silently overwritten. Re-apply the edits
you still want and save again. This is the deliberate replacement for the
old blind-overwrite autosave — the server refuses to let a stale write
win.

### Per-path validation errors

A PATCH body's `values` map is a flat `{"dotted.path": value}` partial update
validated against the registry before anything is written. Rejections come back as
`400` with the offending paths in `details.errors`, which the UI renders
as the **Validation errors** list. The `reason` vocabulary is closed:

| `reason` | Meaning |
|---|---|
| `unknown_path` | not a registry path |
| `invalid_type` | wrong type (`expected` carries the registry `value_type`) |
| `invalid_enum` | not an allowed value (`expected` carries the allowed set) |
| `read_only` | rejected at every scope |
| `secret_reference` | secrets never travel through the config API |
| `not_project_scope` | a `new_run_only` field whose scope is not `project`, patched into the project config |
| `mode_interlock_mismatch` | the cross-path pair check below — one half of a mode intent without its agreeing twin |

`new_run_only` fields *are* accepted in templates and drafts — they
configure future runs.

## How secrets work

Secrets are **write-only through the GUI, always**.

- **Readiness, never values.** `GET /api/v1/secrets/status` answers, for a
  fixed allowlist of names, `configured` (bool), `source_class`
  (`project_env` = the active checkpoint's `.env`, `repo_env` = `ARI/.env`
  or `ari-core/.env`, `user_env` = `~/.env`, `process_env` = the process
  environment fallback), and `last_updated` (the source file's mtime). The
  response DTO has no value field, so echoing a secret back is
  structurally impossible.
- **The allowlist** is enumerated from code, not invented:
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`,
  `GEMINI_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`, `LETTA_API_KEY`,
  `ZENODO_TOKEN`, `ARI_REGISTRY_TOKEN`. A name outside it is a 404.
- **Writing.** `PUT /api/v1/secrets/{secret_id}` takes the value and
  delegates to the hardened `.env` writer: atomic same-directory temp file
  + `fsync` + `os.replace`, `0600` permissions, plus a live `os.environ`
  export. The response is the post-write **readiness row**, never the
  value.
- **In the form,** the secret control shows a name picker (defaulting to
  the active provider's env key from the model catalog), a `configured` /
  `not configured` badge, a password input, and the standing note:
  *"Write-only: the value is sent to the server and can never be read back
  here."* The input is cleared the moment the PUT resolves.

**Where the value actually goes.** Two places, and it is worth being
precise:

1. **The repo-root `.env`** (`{ARI}/.env`). That is a *fixed* write
   target — the writer replaces the matching `NAME=` line in place
   and appends if absent. It does **not** follow the readiness chain and
   it does not write into the active checkpoint.
2. **The running server's `os.environ`**, exported live.

The value is never written into `project_config.json`, a run template, a
run draft, a resolved manifest, or any log.

Because a GUI launch starts from `os.environ` and only lets `.env` files
fill blanks, a secret you just set takes effect immediately for the next
run launched from the GUI.

The one asymmetry to know about: **readiness reads a chain, the write
targets one file.** The chain is active checkpoint `.env` (`project_env`)
→ repo `.env` (`repo_env`) → `~/.env` (`user_env`) → process environment
(`process_env`). So if a checkpoint-local `.env` already defines the same
name, readiness keeps reporting `project_env` as the winning source even
after you write a new value. The `source_class` badge tells you where the
winning *on-disk* definition lives — not where your last write landed.
Edit or remove the checkpoint-local definition if that is not what you
want, especially before running the CLI outside the GUI process.

## The launch flow

The launch panel appears in **draft scope** only (`#/studio?draft=<id>`).
Its stepper is Goal → Review → Launch.

### 1. Resolve and validate

**[Resolve & validate]** issues both calls for the draft (with the
optional execution profile `laptop` / `hpc` / `cloud`):

- `POST /api/v1/run-drafts/{draft_id}/resolve-config` — the new-run
  preview manifest;
- `POST /api/v1/run-drafts/{draft_id}/validate` — `{valid, errors, warnings}`.

The panel then renders: **Changed vs defaults** (every leaf whose
provenance is not the bundled default layer, with the same badge maps as
the Config browser so the two surfaces cannot drift), the
draft-attributable validation errors, the resolver warnings verbatim,
secret readiness rows, and the read-only-governance note.

A rejected override is never silently dropped. When a layer supplies a
value pydantic refuses, the resolver reverts to the last valid layer,
annotates the leaf's provenance with a `rejected_override` explanation,
and emits a warning of the form *"`<layer>` override rejected for
`<path>`: … — keeping the `<layer>` value"*.

An `ari.mode` / `rqgm.enabled` (or `paper.mode` /
`rqgm.paper.enabled`) interlock mismatch takes the same route through the
*resolver* — warn and fall back, with the manifest showing the
**effective** mode — but it does not stay a warning. `/validate` turns that
residual warning into an `interlock_mismatch` error, and the launch refuses
rather than quietly starting the fallback run. This is what catches a pair
the Studio cannot break itself: e.g. a draft asking for `ari_rqgm` while the
server's environment carries `ARI_RQGM_ENABLED=0`.

### 2. Immutable review

The review block is a read-only summary — display name, run id intent
(*server-issued at accept, never guessed from checkpoints*), profile, the
**resolved** execution and paper mode, changed-field count, config digest —
behind an explicit checkbox:

> I reviewed this immutable summary — launch exactly this configuration.

Checking the box mints **exactly one idempotency key** (a
`crypto.randomUUID()`), which is the unit of "this approval". Anything
that invalidates the review — editing and saving the draft (revision
bump), switching drafts, changing the profile or display name — clears
both the approval and the key. A fresh approval is a fresh intent.

The mode rows in that summary are the **resolved** values from the preview
manifest, never the raw selection. When a requested mode was not honoured,
a separate *"Requested mode was not applied"* panel names the requested
value, the resolved value, and the resolver's warning verbatim — so a run
can never be launched under the impression that it is governed when it is
not.

**[Launch run]** is enabled only when the draft validated clean **and**
the draft has a goal **and** the review is confirmed.

### 3. Launch, and what it guarantees

`POST /api/v1/runs` with `{draft_id, display_name?, profile?,
idempotency_key?}` runs strictly in this order:

1. **Idempotent replay check.** A key already on disk short-circuits to
   the recorded `run_id` with `idempotent_replay: true` — nothing is
   spawned.
2. **Validation-first.** Resolver preview + shared draft validation + two
   launch-only checks. Failure returns `400` with per-path
   `details.errors` — **and performs zero filesystem mutation.** No
   checkpoint directory, no `experiment.md`, no partial run to clean up. A
   validation failure is genuinely a no-op.
3. **Server-minted identity.** `run_id = <UTC YYYYMMDDHHMMSS>_<slug>-<6 hex>`.
   The slug is display-only and deterministic — no LLM call and no
   scheduler probe happens before the response.
4. **Idempotency claim.** The create-only `gui_store/launches/{key}.json`
   write happens **before any directory exists**, so two racing POSTs with
   the same key still spawn exactly one subprocess.
5. **Materialize, then spawn.** `experiment.md` (from the goal),
   `workflow.yaml` (copy-on-write seed of the bundled file — plus the
   minimal `ari:` / `rqgm:` / `paper:` blocks when a non-default mode was
   selected), `launch_config.json`, `resolved_config.json` (the resolved
   manifest becomes real at launch), and `launch_events.jsonl`
   (`draft → validating → accepted → spawned`; a spawn failure records
   `failed` and releases the claim). Then the same
   `python3 -m ari.cli run …` subprocess the legacy launch uses, with
   `ARI_CHECKPOINT_DIR` pinned (and the four `ARI_*` mode variables only
   when a non-default mode was selected).
6. **Response, then redirect.** `{run_id, status_url, checkpoint_path,
   accepted, idempotent_replay}` — the response never waits on the
   subprocess. The UI navigates to the canonical
   `#/overview?run=<run_id>`; it uses the server-issued id and never
   guesses the newest checkpoint by mtime.

The global active checkpoint is deliberately **not** switched by a launch.

**Double-click safety.** The button disables in flight and an in-frame ref
guard blocks a second send; a retry after a failed launch reuses the
**same** key, so a retry can only ever replay — never spawn a second run.

The legacy `POST /api/launch` is unchanged and still runs in parallel; the
legacy wizard (`#/new`) still uses it.

## Execution mode: selectable; governance tuning: still file-only

Since **ADR-09** the Studio's *Execution* section is no longer one disabled
group. It offers exactly **two** controls — one per orthogonal intent —
and keeps everything else read-only:

| Control | Config keys it writes | Values |
|---|---|---|
| **Execution mode** | `ari.mode` **and** `rqgm.enabled` | `simple_bfts` (default) / `ari_rqgm` |
| **Paper mode** | `paper.mode` **and** `rqgm.paper.enabled` | `linear` (default) / `rqgm_archive` |

**Each control writes both keys of its pair.** A mode and its interlock are
one intent, so one selection produces one PATCH carrying both keys — the
GUI cannot construct the half-set document the runtime would silently
degrade. If a document ends up with one half and not the other (a hand-made
API call, or a draft that overrides only one key of a template's pair), the
server rejects it with a typed 400 `mode_interlock_mismatch` at template
create/PATCH, draft create/PATCH **and** launch. The check runs on the
*merged* document values, so a two-step edit that ends consistent is fine.

**New runs only.** Both leaves are `mutability: new_run_only` — the choice
applies to the run you are about to launch. Resume is untouched: a resumed
run takes the mode recorded in `{checkpoint}/rqgm_state.json`, which wins
over config and env (downgrade-only). Nothing in the Studio can retarget a
run that already exists.

**Project scope still refuses them.** The four leaves are `scope: run`, so
the project-defaults document rejects them with `not_project_scope`; in that
scope the two selects are disabled and say why. Pick a mode on a run
template or a run draft.

**The remaining 104 governance leaves stay read-only.** Every other path in
the `Execution mode` category and the `rqgm.*` tree (epoch, kernel,
governance, adversarial, budgets, paper-archive tuning) is rendered in a
collapsed, read-only group — **with its effective value**, so you can see
exactly what will apply — under this note:

> **RQGM governance parameters (read-only)** — Effective values shown for
> reference. Governance tuning parameters come from configuration files in
> this release — they are not editable from the GUI; edit `workflow.yaml` to
> change them. Selecting a mode above is not a governance mutation.

That lock is end-to-end, not cosmetic: the launch endpoint recomputes the
locked set from the registry (the `Execution mode` category ∪ `rqgm.*`
**minus** the four selectable leaves — 104 paths today) and rejects a draft
whose own `values` carry one of them with reason `mode_locked`. The
launch's `ARI_*` environment translation structurally excludes every locked
path too, so a value inherited from a run template cannot reach the
subprocess either.

**What a non-default selection does to the checkpoint.** The launch writes
minimal `ari:` / `rqgm:` / `paper:` blocks into the run's own
`workflow.yaml` copy (never the bundled file) *and* exports `ARI_MODE`,
`ARI_RQGM_ENABLED`, `ARI_PAPER_MODE`, `ARI_RQGM_PAPER_ENABLED` to the
subprocess, so the checkpoint describes itself and every later phase agrees
with the environment. Leaving the defaults writes and exports **nothing**:
a `simple_bfts` + `linear` launch is byte-identical to a pre-ADR-09 one,
including when you explicitly re-pick the default values.

You can still do it the CLI way, and that remains the canonical description:

```yaml
# workflow.yaml
ari:
  mode: ari_rqgm      # master switch
rqgm:
  enabled: true       # redundant interlock — both keys must agree
```

or `ARI_MODE=ari_rqgm` / `ARI_RQGM_ENABLED=1` in the environment. Full
semantics — the interlock table, `mode_source`, resume reconciliation, and
the independent `paper.mode` axis — are in
[Execution modes](execution_modes.md).

## See also

- [Dashboard guide](dashboard.md) — starting the server, the workspace map, deep links.
- [Execution modes](execution_modes.md) — enabling `ari_rqgm` and paper mode.
- [RQGM governance workspace](rqgm_gui.md) — reading a governed run.
- [Configuration reference](../reference/configuration.md) — the config file surface.
- [Environment variables](../reference/environment_variables.md).
- [Remote access](remote_access.md) — auth for the config/secret endpoints beyond localhost.
