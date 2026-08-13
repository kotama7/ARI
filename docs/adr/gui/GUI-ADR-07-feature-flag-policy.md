---
sources:
  - path: ari-core/ari/viz/api_capabilities.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/v1/challenges.py
    role: implementation
  - path: ari-core/ari/viz/api_ollama.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/services/api/capabilities.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/App.tsx
    role: implementation
  - path: scripts/setup/setup_env.sh
    role: config
  - path: ari-core/tests/test_gui_capabilities.py
    role: test
  - path: ari-core/tests/test_setup_env.py
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/routeRenderBaseline.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/routeNavParity.test.tsx
    role: test
  - path: docs/guides/gui_cutover_runbook.md
    role: doc
  - path: docs/concepts/gui_architecture.md
    role: doc
  - path: docs/reference/environment_variables.md
    role: doc
last_verified: 2026-08-13
---

# GUI-ADR-07: feature flag, rollback, and legacy removal policy

Status: accepted (2026-07-23), decided at gate G2.

Context: the GUI refresh charter listed "feature flag, rollback, legacy
removal policy" among the decisions that had to be recorded as an ADR, and
paired it with two standing program risks. The first was long-lived dual
implementation — a feature flag becoming permanent — whose control was that
every flag carry an owner, a removal gate, and a deadline, closing at G6. The
second was breaking existing user workflows, whose control was opt-in rollout
with rollback available for at least one minor release. The migration and
release plan made it a non-goal to leave feature flags standing as a permanent
dual architecture, and required that flags be scoped to a route or vertical
slice, that old and new read the same canonical storage so a rollback never
demands a data downgrade, that emergency rollback reach the old shell without a
deploy, and that the supported flag-combination matrix be fixed rather than
left to grow. Wave 1 had already shipped the first flag (`ARI_GUI_V2`) and the
server capability endpoint, so the policy had to be fixed before any second
flag landed.

Decision: five rules. **Distribution** — a flag the frontend must see is
published by the server through `GET /api/capabilities`; the frontend keeps no
independent source of truth for it. **Form** — a flag is an environment-variable
kill-switch; off is decided by exact literal (`'0'`, `'false'`), and any other
value, or none, follows the declared default. **Fail-open** — a flag governing
read-only UI fails open: a failed capability fetch must not hide the surface.
Fail-open is not extended to write operations. **Declaration** — every flag
declares its owner, default, rollback lever, and removal gate in the docstring
of the module that reads it. **Lifetime** — no rollout flag outlives G6 (legacy
removal); rollback is uniformly "set the variable to an off literal and
restart", never a per-flag procedure.

The shipped code matches this. `ari.viz.api_capabilities._api_capabilities`
returns the frozen payload `{"gui_v2": bool, "server_version": "wave1"}` and
computes `gui_v2` as `os.environ.get("ARI_GUI_V2", "1") not in ("0", "false")`;
`routes.py` dispatches `/api/capabilities` to it. On the client,
`ari-core/ari/viz/frontend/src/services/api/capabilities.ts` is the only
reader, and `App.tsx` initialises `guiV2` to `true`, lowers it only on an
explicit `caps.gui_v2 === false`, and swallows a failed fetch in an empty
`.catch` — the fail-open rule as executable code. Six further declaration
blocks carry the heading "(env kill-switch, ADR-07 register)" verbatim:
`ARI_GUI_BIND` in `server.py`, `ARI_GUI_AUTH` in `auth.py`, `ARI_GUI_CORS_ANY`
and `ARI_GUI_CSP` in `routes.py`, `ARI_GUI_HEALTH` in `health.py`,
`ARI_GUI_CHALLENGES` in `v1/challenges.py`; the seventh switch,
`ARI_GUI_TOKEN`, is documented inside the `ARI_GUI_AUTH` block rather than
carrying one of its own. `api_ollama.py` records the same
policy in the negative, stating that the Ollama relay deliberately has no
kill-switch because configuring the target is itself the opt-in.

The source record enumerated no rejected alternatives; it stated the decision,
its consequences and its supersedes line only. Nothing is reconstructed here,
because what the deciders weighed and set aside is not recoverable from the
decision or from the code.

Consequences: a new flag is only admissible when three things land together —
its entry in the capability payload if the frontend must see it, its docstring
declaration, and an assigned removal gate. Rollback support collapses to one
procedure, so no runbook branches per flag. The G6 gate review must take an
inventory of surviving flags as an exit condition, and the supported
combination matrix is fixed at the defaults, plus one lever at a time, plus the
documented remote-mode pair (`ARI_GUI_BIND` with `ARI_GUI_TOKEN`); anything
else is untested. Almost none of this is machine-checked. The only automated
part is narrower than the rule:
`ari-core/tests/test_setup_env.py::test_setup_env_covers_all_source_env_vars`
forces every environment variable read by first-party Python to be declared in
`scripts/setup/setup_env.sh`, which makes a new flag visible but says nothing
about its owner or its expiry. Owner, default, rollback lever, and removal gate
remain prose that a reviewer must check.

Supersedes / superseded-by: first decision on this subject; not superseded.
Later records register flags under it rather than revising it: ADR-13
(remote-mode bearer token) contributes `ARI_GUI_AUTH` as its rollback lever,
and ADR-09 (GUI mode selection for a new run) introduces no kill-switch of its
own, relying on the pre-existing `ARI_GUI_V2=0` to remove the v2 Studio
entirely.

Divergence from the code: three, all in the direction of the code being more
specific than the record.

1. *"No flag outlives G6" now applies only to rollout flags.* The eight
   switches split into one rollout flag and seven security kill-switches.
   `ARI_GUI_V2` declares removal gate G6. `ARI_GUI_CORS_ANY`, `ARI_GUI_CSP`,
   `ARI_GUI_CHALLENGES`, and `ARI_GUI_HEALTH` declare G5. `ARI_GUI_BIND` and
   `ARI_GUI_AUTH` declare "removal gate: none" — loopback-by-default and
   fail-secure remote auth are permanent policy, and the `ARI_GUI_AUTH` block
   states outright that the switch exists only as this ADR's rollback lever. So
   two flags are intended to outlive G6 by design.
   `docs/guides/gui_cutover_runbook.md`, section "6. Legacy removal",
   states the split and says nothing schedules the kill-switches' removal.
2. *Exact-literal off is not uniform.* `api_capabilities.py` compares the raw
   value, so `ARI_GUI_V2=FALSE` or a value with surrounding whitespace leaves
   the flag on. Every later *boolean* switch — `ARI_GUI_CSP`,
   `ARI_GUI_CHALLENGES`, `ARI_GUI_HEALTH`, `ARI_GUI_AUTH` — normalises first
   with `.strip().lower()` before comparing against `("0", "false")`, and
   `ARI_GUI_CORS_ANY` inverts polarity entirely — being default-off, it is
   read as an *on* literal, `in ("1", "true")`. The remaining two are not
   literal switches at all: `ARI_GUI_BIND` carries a bind address and
   `ARI_GUI_TOKEN` a bearer token, and for both the safe state is *unset*
   (`server.resolve_bind_hosts` returns the loopback default for an unset or
   blank value). The rule as written is literally true only of `ARI_GUI_V2`.
3. *The metrics limb is unimplemented.* The plan required each flag to carry
   metrics alongside owner, default, and rollback. ARI ships no telemetry
   pipeline; `api_capabilities.py` declares "metrics: none in Wave 1", and the
   runbook's scope note states that every rollout signal is something an
   operator reads from a local surface, making the rollout a supervised
   dogfood rather than an instrumented canary. The six kill-switch declaration
   blocks omit the metrics line altogether.

Scope note, not a divergence: only `ARI_GUI_V2` is published over
`/api/capabilities`. The seven security kill-switches change server behaviour
that the client does not need to branch on, so the endpoint is a capability
feed for the shell, not a general register of every flag.

Permanent references: `docs/guides/gui_cutover_runbook.md`, sections
"1. Levers", "5. Rollback procedure, by layer", "6. Legacy removal", and
"7. Compatibility matrix"; `docs/concepts/gui_architecture.md`, section
"9. Capabilities and kill-switches"; `docs/reference/environment_variables.md`,
section "GUI server (`ARI_GUI_*`)".

Owning tests: `ari-core/tests/test_gui_capabilities.py` —
`test_default_on_when_unset`, `test_zero_turns_flag_off`,
`test_false_turns_flag_off`, `test_other_values_stay_on`,
`test_payload_shape_frozen`;
`ari-core/tests/test_setup_env.py::test_setup_env_covers_all_source_env_vars`;
frontend `ari-core/ari/viz/frontend/src/__tests__/routeRenderBaseline.test.tsx`
(the `gui_v2 off` cases, which assert that each v2-only route falls back to
Home while its legacy counterpart still mounts) and
`ari-core/ari/viz/frontend/src/__tests__/routeNavParity.test.tsx` (the `guiV2`
nav markers).
