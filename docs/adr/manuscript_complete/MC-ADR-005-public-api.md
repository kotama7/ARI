# MC-ADR-005: stable read API

Decision: export frozen V1 models and pure compiler/evaluator helpers through
`ari.public.manuscript`; keep mutable coordinator/state internals private.
Internal-only APIs would force consumers to import unstable modules, while
exporting the coordinator would freeze mutation semantics prematurely.
Compatibility is tracked by the public contract snapshot. Reverse by deprecating
symbols through the normal public-API policy. Owning tests: public API and
contract snapshot tests.
