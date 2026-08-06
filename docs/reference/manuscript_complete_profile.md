# `generic_empirical_v1` profile

The initial profile is for empirical papers. Applicability is derived from
typed context characteristics; a writer cannot opt a requirement out.

| Requirement | Applies when | Authoring | Publication | Primary resolver |
|---|---|---:|---:|---|
| MC-RQ-001 question/objective | always | block | block | method/human clarification |
| MC-RQ-002 hypothesis/falsification | hypothesis testing | block | block | method/human clarification |
| MC-ME-001 method | always | block | block | artifact recovery |
| MC-ME-002 configuration/environment | empirical | block | block | artifact recovery |
| MC-ME-003 protocol/workload/stopping | empirical | block | block | artifact recovery/validation |
| MC-RS-001 primary result identity | result claim | block | block | projection/validation |
| MC-RS-002 uncertainty | stochastic claim | block | block | repetition |
| MC-CP-001 baseline | comparative claim | block | block | baseline experiment |
| MC-CP-002 equivalent protocol | comparator exists | block | block | validation |
| MC-AB-001 component ablation | multi-component claim | block | block | ablation |
| MC-CL-001 claim coverage | result claim | block | block | projection rebuild |
| MC-CL-002 numeric reproducibility | numeric result | block | block | projection/validation |
| MC-NG-001 negative accounting | always | report | block | projection/disclosure |
| MC-SL-001 selection accounting | multiple candidates | report | block | projection rebuild |
| MC-RW-001 recorded related work | always | block | block | recorded retrieval |
| MC-RW-002 novelty distinction | novelty claim | block | block | recorded retrieval/human |
| MC-LM-001 limitations | always | block | block | disclosure |
| MC-LM-002 validity threats | empirical | report | block | disclosure |
| MC-RP-001 EAR/source/environment | empirical | block | block | artifact recovery |
| MC-RP-002 commands/locks | reproducibility claim | block | block | artifact recovery |
| MC-AS-001 current certification | assurance enforce | report | block | fixed certification |
| MC-OM-001 omission accounting | manuscript enabled | block | block | projection rebuild |

Characteristics such as `stochastic_claim`, `comparative_claim`, and
`multi_component_claim` come from recorded measurements, configurations,
metric vocabulary, contribution structure, and node labels. They are not
inferred from reviewer prose. A future profile change requires a new profile
ID/version and therefore a new attempt identity.
