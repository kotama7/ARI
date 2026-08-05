# SpMM Optimization

## When to use

Use for sparse-matrix times dense-matrix optimization with an explicit sparse
format and correctness contract.

## Preconditions

The CSR interface, index base, duplicate policy, dtype, dense right-hand-side
layout, hardware, and baseline metric are fixed by the Research Contract.

## Procedure

Inspect CSR structure and row-length distribution, establish a trusted reference,
then use semantic code-edit, compile, run, and benchmark capabilities. Evaluate
partitioning, vectorization, and format-specialization hypotheses over diverse
sparsity patterns without silently rewriting input semantics.

## Decision points

Select an optimization only when it improves the declared workload distribution
and preserves empty-row, duplicate, sorted/unsorted, and zero-nnz behavior.

## Failure conditions

Stop promotion on invalid CSR acceptance outside policy, index or memory errors,
incorrect duplicate handling, nondeterministic disagreement, or incomplete
pattern coverage.

## Expected artifacts

Record source/binary identity, CSR case manifest, reference outputs, sanitizer
logs, raw performance measurements, and execution environment.

## Scientific cautions

Average sparsity does not characterize irregularity. Do not select only favorable
matrices or treat a fast Provider response as scientific evidence.

## Evaluation obligations

Require structural validation, differential tests across sparse-pattern and RHS
width families, memory-safety checks, performance regression, and reproducibility.
