# MC-ADR-006: applicability inputs

Decision: stochastic, comparative, and ablation applicability derives from
typed measurements/configurations, metric vocabulary, contributions, and node
labels. Reviewer or writer prose is not an applicability input. Alternatives
were manual free text and LLM classification; neither is replay-stable.
Compatibility: profile/evaluator versions bind the decision. Reverse only with
a new profile/evaluator version and labelled-fixture evaluation. Owning tests:
profile/readiness determinism and fixture evaluation tests.
