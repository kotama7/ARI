# Refactoring Handoff Prompts

> ## ▶ AGENT: START HERE — this file is a self-contained entry point
>
> If you have been handed this file — i.e. asked to **read or follow**
> `docs/refactoring/HANDOFF_PROMPTS.md` — then **you are the autonomous
> orchestrator. Begin now; do not wait for further human instructions.**
>
> Treat the **STEP 0 → STEP 3 procedure in section Ⓐ below as your own operating
> instructions** and start at STEP 0 immediately. Everything you need is in this
> repository under `docs/refactoring/`. Work on branch `whole_refactoring` at repo
> root `/home/t-kotama/workplace/ARI`. Work autonomously, but consult the human per
> the "WHEN TO ASK vs. proceed" rules in Ⓐ — asking when genuinely unsure is
> encouraged. Your run is **resumable** via the ledger
> `docs/refactoring/reports/orchestration_status.md`, so re-reading this file in a
> fresh session continues where you left off.
>
> Nothing else needs to be pasted or set up. (A human may instead paste the Ⓐ
> block into a fresh session, or wrap it as `/loop` for unattended operation — but
> simply pointing an agent at this file is sufficient.)

Contents: **Ⓐ** the autonomous orchestrator procedure (drives all 73 subtasks in
dependency order; resumable), and **Ⓑ** nine per-subtask prompts for optional
manual dispatch.

---

## Ⓐ Autonomous Orchestrator — the procedure that runs the whole program

An agent handed this file follows the STEP 0–3 procedure below as its own
instructions, starting immediately at STEP 0. A human may also paste this block
into a fresh Claude Code session at the repo root, or wrap it with the self-paced
loop `/loop <paste the block>` (omit an interval to self-pace) for unattended runs.

```text
You are the AUTONOMOUS ORCHESTRATOR for the entire ARI refactoring program. Drive
ALL subtasks 001–073 to completion in dependency order, without breaking any
contract. Work autonomously and avoid UNNECESSARY interruptions — but ASKING A
HUMAN WHEN YOU ARE GENUINELY UNSURE IS ENCOURAGED, even preferred: a good
clarifying question beats a wrong guess. Never guess on something you cannot
determine from the planning docs + primary sources; ask instead.

WHEN TO ASK vs. proceed:
  - PROCEED without asking when the answer is determinable from the subtask doc,
    010 contracts, 007, or the repository itself (Read/Grep). Don't ask about
    things you can look up.
  - ASK the human when: the spec is ambiguous; a design/trade-off decision is not
    settled by the docs; a change might touch a public contract in a non-obvious
    way; acceptance criteria are unclear; or you're simply unsure whether an action
    is safe or intended. In all these, prefer asking over guessing.
  - Keep intervention low WITHOUT suppressing good questions: BATCH open questions
    and ask them together rather than one at a time; while a question is pending,
    keep making progress on other READY subtasks; record each question and its
    answer in the ledger so the run stays resumable.

Repo: /home/t-kotama/workplace/ARI   Branch: whole_refactoring
Planning corpus: docs/refactoring/ (already committed).

STEP 0 — Load the plan (read fully, once):
  - docs/refactoring/000_master_refactoring_plan.md
  - docs/refactoring/007_subtask_index.md  (subtask list, dependency graph,
    execution order, Document Retirement Policy)
  - docs/refactoring/010_contract_preservation_policy.md
  Each subtask's spec is docs/refactoring/subtasks/NNN_*.md.

STEP 1 — Load/So create the progress ledger (this makes the run resumable):
  - Ledger: docs/refactoring/reports/orchestration_status.md
  - If missing, create it: a table of all 73 subtasks
    (ID | title | phase | risk | status | commit) with status=TODO, plus a
    "Blocked / Human-decision notes" list. Status: TODO -> IN_PROGRESS -> DONE
    (or BLOCKED:<reason>). Trust this ledger as the source of truth for progress.

STEP 2 — Main loop (repeat until all 73 are DONE):
  a. READY set = subtasks with status TODO whose dependencies (per the 007 graph)
     are all DONE.
  b. HARD GATE: no runtime-code-changing subtask may start until ALL nine
     inventories are DONE: 001,002,020,036,045,053,059,060,067. (Inventory and
     doc/checker subtasks that add only new files are not gated by this.)
  c. Pick next: prefer the 9 inventories first; then lowest §16 Risk; then the
     critical-path item that unblocks the most successors. You MAY do several
     independent READY subtasks in one iteration when that is safe.
  d. Mark it IN_PROGRESS in the ledger.
  e. EXECUTE strictly per its subtask doc: only §3 Scope / §8 Work Items; obey
     §4 Non-Goals and §10 Files/APIs That Must Not Be Broken.
  f. VERIFY:
       - meet §13 Acceptance Criteria;
       - run §12 quality gates: python -m compileall .  |  pytest -q  |  ruff check .
         (frontend subtasks also: cd ari-core/ari/viz/frontend && npm ci &&
          npm run build && npm test)
  g. If ALL gates pass: commit on this branch with a scoped message
     ("refactor(NNN): <title>", or docs/test/chore(NNN) as appropriate), mark the
     subtask DONE in the ledger with the commit hash, and continue the loop.
  h. If a gate FAILS, or finishing would require breaking a 010 contract, or the
     spec is genuinely ambiguous in a contract-risky way: do NOT force it. Revert
     that subtask's working-tree changes (git restore), set it BLOCKED:<precise
     reason> in the ledger, then continue with other READY subtasks; if nothing
     else is READY, STOP and report the blockers.
  i. Special cases:
       - 057 (delete safe dead code): delete ONLY SAFE_DELETE_CANDIDATE items
         confirmed by 053–056, and re-verify each against primary sources before
         git rm (Document Retirement Policy). If in doubt, keep it and mark REVIEW.
       - Prompt-extraction (039–041): the rendered prompt output must stay
         byte-identical unless the subtask says otherwise; use the 042 snapshot
         tests as the gate.
       - When a subtask you complete satisfies another document's Retirement
         Condition, note it under "Blocked / Human-decision notes" — do NOT git rm
         planning docs yourself; leave that for a human per the retirement policy.

STEP 3 — Finish:
  - Run 019 (final quality report) LAST, after every other subtask is DONE.
  - Set the ledger all-DONE, print a per-subtask summary (status + commit hash),
    and DO NOT push. Report that the branch is ready for review/push.

Global rules:
  - Ground everything in primary sources (Read/Grep). If a path doesn't exist, say
    so; never invent (there is NO sonfigs/ directory).
  - Commit after each subtask so progress is durable. THIS LOOP IS RESUMABLE:
    re-running this exact prompt in a fresh session reads the ledger and continues
    — context limits never lose progress.
  - Never silently break a contract to make progress; record anything a human must
    ultimately decide under "Blocked / Human-decision notes" and keep going on the
    rest.
```

To resume after a stop/context reset: paste the same prompt again — it reads
`docs/refactoring/reports/orchestration_status.md` and continues. To push or open a
PR, tell the session explicitly (it will not push on its own).

---

## Ⓑ Manual dispatch — first-wave inventory prompts (fallback)

## How to use

- **First wave = the 9 inventory subtasks** (`001, 002, 020, 036, 045, 053, 059,
  060, 067`). They change **no** runtime code and have no cross-dependencies among
  themselves except that **`059` must finish before `060` and `067`**
  (`059 → 060`, `059 → 067` in `007_subtask_index.md`).
- Run `①–⑥` and `⑦ (059)` in parallel sessions; after `059` is DONE, dispatch
  `⑧ (060)` and `⑨ (067)`.
- **Do not start any runtime-changing subtask (Phase 2 onward) until all 9
  inventories are DONE** (master plan / `007` "Subtasks That Must Precede Any
  Runtime Code Change").
- After the first wave, follow the dependency graph in `007_subtask_index.md`
  (`001 → 025, 031`; `053 → 054 → 055 → 056 → 057 → 058`; `020 → 021…024, 030`;
  `036 → 037…044`; `045 → 046…052`; `059 → 061…066` and `068…073`;
  `004 → 005, 006`; `007 → 008…014`).

Branch: `whole_refactoring`. Planning corpus committed under `docs/refactoring/`.

---

## ① Subtask 001 — measure_complexity_and_dependencies

```text
You are a follow-on implementation session for the ARI refactoring program.
Repo: /home/t-kotama/workplace/ARI (branch: whole_refactoring; planning corpus
committed under docs/refactoring/).

Before doing anything, READ in full:
  - docs/refactoring/000_master_refactoring_plan.md
  - docs/refactoring/007_subtask_index.md
  - docs/refactoring/010_contract_preservation_policy.md
  - docs/refactoring/subtasks/001_measure_complexity_and_dependencies.md

Hard rules:
  - Do EXACTLY what the subtask's §3 Scope and §8 Concrete Work Items specify —
    nothing more. Honor §4 Non-Goals and §10 Files/APIs That Must Not Be Broken.
  - Never break the contracts in 010: CLI `ari`, ari.public.*, MCP tool
    name/args/return schemas, dashboard endpoints + response schema + fields
    services/api.ts depends on, checkpoint/output/config formats, ari-skill-* →
    ari-core interfaces, README/docs usage, scripts invoked by .github/workflows.
  - This subtask does NOT change runtime code (§16). Produce only the report/
    artifact files it specifies (under docs/refactoring/reports/). Do not run
    ruff --fix or install packages.
  - Ground every claim in primary sources (Read/Grep). If a path does not exist,
    write "does not exist" — never invent (note: there is NO sonfigs/ directory).

Your task: implement subtask 001 end to end (empirical complexity + dependency
baseline census).

When done:
  - Satisfy §13 Acceptance Criteria.
  - Run §12 quality gates and report honestly:
      python -m compileall .   |   pytest -q   |   ruff check .
  - Do NOT commit or push unless explicitly asked. Summarize what you produced.
```

---

## ② Subtask 002 — inventory_legacy_obsolete_and_duplicate_code

```text
You are a follow-on implementation session for the ARI refactoring program.
Repo: /home/t-kotama/workplace/ARI (branch: whole_refactoring; planning corpus
committed under docs/refactoring/).

Before doing anything, READ in full:
  - docs/refactoring/000_master_refactoring_plan.md
  - docs/refactoring/007_subtask_index.md
  - docs/refactoring/010_contract_preservation_policy.md
  - docs/refactoring/subtasks/002_inventory_legacy_obsolete_and_duplicate_code.md

Hard rules:
  - Do EXACTLY what the subtask's §3 Scope and §8 Concrete Work Items specify —
    nothing more. Honor §4 Non-Goals and §10 Files/APIs That Must Not Be Broken.
  - Never break the contracts in 010: CLI `ari`, ari.public.*, MCP tool
    name/args/return schemas, dashboard endpoints + response schema + fields
    services/api.ts depends on, checkpoint/output/config formats, ari-skill-* →
    ari-core interfaces, README/docs usage, scripts invoked by .github/workflows.
  - This subtask does NOT change or delete runtime code (§16). It only INVENTORIES
    legacy/obsolete/duplicate candidates and classifies them (KEEP / ADAPT / MERGE
    / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED). Deletion happens later
    in subtask 057 only. Produce report artifacts only.
  - Ground every claim in primary sources (Read/Grep). If a path does not exist,
    write "does not exist" — never invent (note: there is NO sonfigs/ directory).

Your task: implement subtask 002 end to end (legacy/obsolete/duplicate inventory).

When done:
  - Satisfy §13 Acceptance Criteria.
  - Run §12 quality gates and report honestly:
      python -m compileall .   |   pytest -q   |   ruff check .
  - Do NOT commit or push unless explicitly asked. Summarize what you produced.
```

---

## ③ Subtask 020 — inventory_viz_dashboard_api_contracts

```text
You are a follow-on implementation session for the ARI refactoring program.
Repo: /home/t-kotama/workplace/ARI (branch: whole_refactoring; planning corpus
committed under docs/refactoring/).

Before doing anything, READ in full:
  - docs/refactoring/000_master_refactoring_plan.md
  - docs/refactoring/007_subtask_index.md
  - docs/refactoring/010_contract_preservation_policy.md
  - docs/refactoring/008_viz_dashboard_refactoring_plan.md
  - docs/refactoring/subtasks/020_inventory_viz_dashboard_api_contracts.md

Hard rules:
  - Do EXACTLY what the subtask's §3 Scope and §8 Concrete Work Items specify —
    nothing more. Honor §4 Non-Goals and §10 Files/APIs That Must Not Be Broken.
  - Never break the contracts in 010: dashboard endpoints + response schema + the
    exact fields ari-core/ari/viz/frontend/src/services/api.ts depends on, plus
    CLI `ari`, ari.public.*, MCP schemas, checkpoint/config formats.
  - This subtask does NOT change runtime code (§16). It only INVENTORIES the viz/
    dashboard API surface (routes.py + api_*.py + websocket.py) and its request/
    response contracts. Produce report artifacts only.
  - Ground every claim in primary sources (Read/Grep). If a path does not exist,
    write "does not exist" — never invent (note: there is NO sonfigs/ directory).

Your task: implement subtask 020 end to end (viz/dashboard API contract inventory).

When done:
  - Satisfy §13 Acceptance Criteria.
  - Run §12 quality gates and report honestly:
      python -m compileall .   |   pytest -q   |   ruff check .
  - Do NOT commit or push unless explicitly asked. Summarize what you produced.
```

---

## ④ Subtask 036 — inventory_hardcoded_prompts

```text
You are a follow-on implementation session for the ARI refactoring program.
Repo: /home/t-kotama/workplace/ARI (branch: whole_refactoring; planning corpus
committed under docs/refactoring/).

Before doing anything, READ in full:
  - docs/refactoring/000_master_refactoring_plan.md
  - docs/refactoring/007_subtask_index.md
  - docs/refactoring/010_contract_preservation_policy.md
  - docs/refactoring/011_prompt_management_plan.md
  - docs/refactoring/subtasks/036_inventory_hardcoded_prompts.md

Hard rules:
  - Do EXACTLY what the subtask's §3 Scope and §8 Concrete Work Items specify —
    nothing more. Honor §4 Non-Goals and §10 Files/APIs That Must Not Be Broken.
  - Never break the contracts in 010 (CLI, ari.public.*, MCP schemas, dashboard
    API, checkpoint/config formats, ari-skill-* → ari-core interfaces).
  - This subtask does NOT externalize or edit any prompt and does NOT change
    runtime code (§16). It only INVENTORIES hardcoded/inline prompts and classifies
    them (KEEP_INLINE / EXTRACT_TEMPLATE / MERGE_DUPLICATE /
    MOVE_TO_CONFIGURABLE_PROMPT / REVIEW_REQUIRED). Extraction happens in later
    subtasks (039–041). Note ARI already has ari-core/ari/prompts/ + _loader.py
    with .md templates — describe existing state accurately. Produce report only.
  - Ground every claim in primary sources (Read/Grep). If a path does not exist,
    write "does not exist" — never invent (note: there is NO sonfigs/ directory).

Your task: implement subtask 036 end to end (hardcoded-prompt inventory).

When done:
  - Satisfy §13 Acceptance Criteria.
  - Run §12 quality gates and report honestly:
      python -m compileall .   |   pytest -q   |   ruff check .
  - Do NOT commit or push unless explicitly asked. Summarize what you produced.
```

---

## ⑤ Subtask 045 — inventory_github_workflows

```text
You are a follow-on implementation session for the ARI refactoring program.
Repo: /home/t-kotama/workplace/ARI (branch: whole_refactoring; planning corpus
committed under docs/refactoring/).

Before doing anything, READ in full:
  - docs/refactoring/000_master_refactoring_plan.md
  - docs/refactoring/007_subtask_index.md
  - docs/refactoring/010_contract_preservation_policy.md
  - docs/refactoring/012_github_workflow_integration_plan.md
  - docs/refactoring/subtasks/045_inventory_github_workflows.md

Hard rules:
  - Do EXACTLY what the subtask's §3 Scope and §8 Concrete Work Items specify —
    nothing more. Honor §4 Non-Goals and §10 Files/APIs That Must Not Be Broken.
  - Do NOT modify any .github/workflows/*.yml or add/replace workflows. This is an
    INVENTORY only (§16 = no runtime change): read the 5 existing workflows
    (docs-change-coupling, docs-sync, pages, readme-sync, refactor-guards),
    document triggers/jobs/scripts each runs, and confirm the ABSENCE of
    ISSUE_TEMPLATE/, PULL_REQUEST_TEMPLATE.md, dependabot.yml, CODEOWNERS.
    Produce report artifacts only.
  - Ground every claim in primary sources (Read/Grep). If a path does not exist,
    write "does not exist" — never invent (note: there is NO sonfigs/ directory).

Your task: implement subtask 045 end to end (GitHub workflow inventory).

When done:
  - Satisfy §13 Acceptance Criteria.
  - Run §12 quality gates and report honestly:
      python -m compileall .   |   pytest -q   |   ruff check .
  - Do NOT commit or push unless explicitly asked. Summarize what you produced.
```

---

## ⑥ Subtask 053 — inventory_reference_roots

```text
You are a follow-on implementation session for the ARI refactoring program.
Repo: /home/t-kotama/workplace/ARI (branch: whole_refactoring; planning corpus
committed under docs/refactoring/).

Before doing anything, READ in full:
  - docs/refactoring/000_master_refactoring_plan.md
  - docs/refactoring/007_subtask_index.md
  - docs/refactoring/010_contract_preservation_policy.md
  - docs/refactoring/013_reference_graph_and_dead_code_plan.md
  - docs/refactoring/subtasks/053_inventory_reference_roots.md

Hard rules:
  - Do EXACTLY what the subtask's §3 Scope and §8 Concrete Work Items specify —
    nothing more. Honor §4 Non-Goals and §10 Files/APIs That Must Not Be Broken.
  - This subtask does NOT change runtime code and deletes NOTHING (§16). It only
    enumerates the reference ROOTS (pyproject console_scripts ari=ari.cli:app,
    CLI main, MCP skill registrations, dashboard routes, ari.public.* exports,
    ari-skill entrypoints, tests, examples, workflow-invoked scripts, documented
    commands, frontend-called endpoints) and dynamic-reference sources (registry/
    factory string keys). This feeds 054→058. Produce report artifacts only.
  - Ground every claim in primary sources (Read/Grep). If a path does not exist,
    write "does not exist" — never invent (note: there is NO sonfigs/ directory).

Your task: implement subtask 053 end to end (reference-root inventory).

When done:
  - Satisfy §13 Acceptance Criteria.
  - Run §12 quality gates and report honestly:
      python -m compileall .   |   pytest -q   |   ruff check .
  - Do NOT commit or push unless explicitly asked. Summarize what you produced.
```

---

## ⑦ Subtask 059 — inventory_dashboard_frontend_backend_structure  (run before 060 & 067)

```text
You are a follow-on implementation session for the ARI refactoring program.
Repo: /home/t-kotama/workplace/ARI (branch: whole_refactoring; planning corpus
committed under docs/refactoring/).

Before doing anything, READ in full:
  - docs/refactoring/000_master_refactoring_plan.md
  - docs/refactoring/007_subtask_index.md
  - docs/refactoring/010_contract_preservation_policy.md
  - docs/refactoring/014_dashboard_ux_refactoring_plan.md
  - docs/refactoring/subtasks/059_inventory_dashboard_frontend_backend_structure.md

Hard rules:
  - Do EXACTLY what the subtask's §3 Scope and §8 Concrete Work Items specify —
    nothing more. Honor §4 Non-Goals and §10 Files/APIs That Must Not Be Broken.
  - This subtask does NOT change runtime code (§16). It INVENTORIES the dashboard
    frontend + backend structure under ari-core/ari/viz/ (backend api_*.py/routes/
    websocket) and frontend/src (App, pages, components, services/api.ts, i18n,
    state), including the committed node_modules hygiene issue. Produce report
    artifacts only. NOTE: subtasks 060 and 067 depend on this one — finish 059
    before dispatching them.
  - Ground every claim in primary sources (Read/Grep). If a path does not exist,
    write "does not exist" — never invent (note: there is NO sonfigs/ directory).

Your task: implement subtask 059 end to end (dashboard FE/BE structure inventory).

When done:
  - Satisfy §13 Acceptance Criteria.
  - Run §12 quality gates and report honestly:
      python -m compileall .   |   pytest -q   |   ruff check .
    (frontend: cd ari-core/ari/viz/frontend && npm run build  — only if §12 asks)
  - Do NOT commit or push unless explicitly asked. Summarize what you produced.
```

---

## ⑧ Subtask 060 — inventory_dashboard_api_contracts  (after 059)

```text
You are a follow-on implementation session for the ARI refactoring program.
Repo: /home/t-kotama/workplace/ARI (branch: whole_refactoring; planning corpus
committed under docs/refactoring/).
PRECONDITION: subtask 059 must already be DONE (this subtask consumes its output).

Before doing anything, READ in full:
  - docs/refactoring/000_master_refactoring_plan.md
  - docs/refactoring/007_subtask_index.md
  - docs/refactoring/010_contract_preservation_policy.md
  - docs/refactoring/subtasks/059_inventory_dashboard_frontend_backend_structure.md (context)
  - docs/refactoring/subtasks/060_inventory_dashboard_api_contracts.md

Hard rules:
  - Do EXACTLY what the subtask's §3 Scope and §8 Concrete Work Items specify —
    nothing more. Honor §4 Non-Goals and §10 Files/APIs That Must Not Be Broken.
  - Never break the contracts in 010, especially the exact dashboard endpoints,
    response schema, and the fields services/api.ts consumes.
  - This subtask does NOT change runtime code (§16). It INVENTORIES the dashboard
    API contracts (backend endpoint <-> frontend consumer field mapping). Produce
    report artifacts only.
  - Ground every claim in primary sources (Read/Grep). If a path does not exist,
    write "does not exist" — never invent (note: there is NO sonfigs/ directory).

Your task: implement subtask 060 end to end (dashboard API contract inventory).

When done:
  - Satisfy §13 Acceptance Criteria.
  - Run §12 quality gates and report honestly:
      python -m compileall .   |   pytest -q   |   ruff check .
  - Do NOT commit or push unless explicitly asked. Summarize what you produced.
```

---

## ⑨ Subtask 067 — inventory_dashboard_visible_settings  (after 059)

```text
You are a follow-on implementation session for the ARI refactoring program.
Repo: /home/t-kotama/workplace/ARI (branch: whole_refactoring; planning corpus
committed under docs/refactoring/).
PRECONDITION: subtask 059 must already be DONE (this subtask consumes its output).

Before doing anything, READ in full:
  - docs/refactoring/000_master_refactoring_plan.md
  - docs/refactoring/007_subtask_index.md
  - docs/refactoring/010_contract_preservation_policy.md
  - docs/refactoring/014_dashboard_ux_refactoring_plan.md
  - docs/refactoring/subtasks/067_inventory_dashboard_visible_settings.md

Hard rules:
  - Do EXACTLY what the subtask's §3 Scope and §8 Concrete Work Items specify —
    nothing more. Honor §4 Non-Goals and §10 Files/APIs That Must Not Be Broken.
  - This subtask does NOT change the UI or runtime code (§16). It INVENTORIES
    every user-visible setting (from Settings/SettingsPage.tsx + settingsConstants.ts
    and elsewhere) and classifies each by frequency/danger/audience (Primary /
    Secondary / Advanced / Developer / Dangerous). Do NOT delete or move settings —
    that is later UX work (068–072). Produce report artifacts only.
  - Ground every claim in primary sources (Read/Grep). If a path does not exist,
    write "does not exist" — never invent (note: there is NO sonfigs/ directory).

Your task: implement subtask 067 end to end (visible-settings inventory).

When done:
  - Satisfy §13 Acceptance Criteria.
  - Run §12 quality gates and report honestly:
      python -m compileall .   |   pytest -q   |   ruff check .
  - Do NOT commit or push unless explicitly asked. Summarize what you produced.
```

---

## Retirement Condition

This is a program-level handoff document. It may be archived or deleted (`git rm`)
only after **all** of the following are verified against primary sources:

1. Every subtask referenced here has been executed and marked **DONE** in
   `docs/refactoring/007_subtask_index.md`, **or** this file has been explicitly
   superseded by a named replacement.
2. No follow-on session still needs these handoff prompts.

Before any `git rm`, re-read this document's own conditions and check each one
against the current repository. See the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
