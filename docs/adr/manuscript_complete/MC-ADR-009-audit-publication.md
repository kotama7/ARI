# MC-ADR-009: audit publication semantics

Decision: audit emits the same shadow readiness and publication gate structure
but does not change legacy writer inputs, PaperBuild status, or publication
behavior. A shadow `publishable` is diagnostic and is not a lock. Alternatives
were suppressing the decision or enforcing it in audit; the former prevents
migration measurement and the latter violates shadow compatibility. Reverse
only with a new mode. Owning tests: audit writer-input identity, decision
logical-AND, and off/audit dispatch tests.
