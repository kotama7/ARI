# GEMM Optimization

## When to use

Use this procedure when optimizing dense matrix multiplication while numerical
equivalence and reproducible measurement remain mandatory.

## Preconditions

The Research Contract identifies the target interface, data types, supported
hardware, baseline implementation, and admissible performance metric.

## Procedure

Inspect the code and data layout, state the GEMM equation including transpose,
leading-dimension, alpha, and beta semantics, then use code-edit, compile, run,
benchmark, and—when bound—hardware-counter capabilities. Change one optimization
hypothesis at a time and retain the exact source and binary artifacts.

## Decision points

Choose blocking, vectorization, threading, or accelerator specialization only
after the measured bottleneck and target architecture justify it. Prefer the
least side-effecting bound Provider that satisfies the required capability.

## Failure conditions

Stop scientific promotion on ABI mismatch, sanitizer finding, numerical error
outside the dtype/accumulation-length model, nondeterministic disagreement, or
missing performance provenance.

## Expected artifacts

Produce source, compiler invocation, binary identity, test-case manifest,
correctness evidence, raw timings, summarized measurements, and environment
identity.

## Scientific cautions

Do not tune to one square shape, conflate correctness with performance, relax a
tolerance after observing failures, or treat Provider success as correctness.

## Evaluation obligations

Require numerical equivalence through differential and metamorphic testing,
performance-regression checks, memory-safety checks, and reproducibility across
the declared shape/thread matrix.
