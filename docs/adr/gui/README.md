# GUI refresh decisions

These are the decision records of the GUI refresh program — the dashboard under
`ari-core/ari/viz/` and its `/api/v1` surface. Backend, frontend, tests and
scripts cite them by id (`ADR-01` … `ADR-13`) and never by path, so the id on
each title line is the stable reference and survives any move or rename. Each
record states its own supersedes / superseded-by relationship and names its
owning tests; there is no separate relationship index. Reversing one requires
those tests to change with it. `ADR-06` has no record: that id was reserved for
a read-model index decision that was never accepted.

- [GUI-ADR-01](GUI-ADR-01-router-and-server-state.md)
- [GUI-ADR-02](GUI-ADR-02-api-v1-transport.md)
- [GUI-ADR-03](GUI-ADR-03-sse-websocket-coexistence.md)
- [GUI-ADR-04](GUI-ADR-04-config-metadata-registry.md)
- [GUI-ADR-05](GUI-ADR-05-secret-provider.md)
- [GUI-ADR-07](GUI-ADR-07-feature-flag-policy.md)
- [GUI-ADR-08](GUI-ADR-08-default-project.md)
- [GUI-ADR-09](GUI-ADR-09-mode-selection.md)
- [GUI-ADR-10](GUI-ADR-10-workflow-write-guard.md)
- [GUI-ADR-11](GUI-ADR-11-secret-readiness-api.md)
- [GUI-ADR-12](GUI-ADR-12-config-store-location.md)
- [GUI-ADR-13](GUI-ADR-13-remote-bearer-token.md)
